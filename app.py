import os
import time
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from google import genai
from google.genai import types

load_dotenv()

app = Flask(__name__)  # sirve automáticamente /static/...
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 86400  # caché de 1 día para imágenes y CSS

api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("asistente_jarvis")
if not api_key:
    raise ValueError("Falta la variable de entorno GEMINI_API_KEY en el servidor.")

client = genai.Client(api_key=api_key)

# Se pueden cambiar desde Render > Environment sin tocar el código
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
# Si el modelo principal está saturado (503) o no existe (404), prueba estos en orden
FALLBACKS = [m.strip() for m in os.environ.get(
    "GEMINI_FALLBACKS", "gemini-3.5-flash,gemini-3.5-flash-lite").split(",") if m.strip()]
MODELS = [MODEL] + [m for m in FALLBACKS if m != MODEL]
THINKING = os.environ.get("THINKING_LEVEL", "LOW")  # LOW = respuestas rápidas
MAX_HISTORY = 12

SYSTEM = (
    "Eres Jarvis, un asistente virtual experto en desarrollo web frontend. "
    "Hablas en español, con tono amigable, cercano y motivador, y usas emojis con moderación. "
    "Tus respuestas se leen en voz alta, así que sé breve (máximo 4 o 5 frases) "
    "salvo que te pidan código o más detalle. "
    "Solo pregunta el nombre del usuario si no aparece en la conversación previa."
)


@app.route("/")
def home():
    return send_from_directory(app.root_path, "index.html", max_age=0)


@app.route("/health")
def health():
    return "ok"


@app.route("/config")
def config_info():
    return jsonify({"model": MODEL})


def build_contents(history, mensaje):
    contents = []
    for m in history[-MAX_HISTORY:]:
        if not isinstance(m, dict):
            continue
        text = str(m.get("text", ""))[:2000].strip()
        if not text:
            continue
        role = "user" if m.get("sender") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=text)]))

    # El historial debe empezar con un mensaje del usuario
    while contents and contents[0].role == "model":
        contents.pop(0)

    contents.append(types.Content(role="user", parts=[types.Part(text=mensaje)]))
    return contents


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    mensaje = str(data.get("mensaje", "")).strip()[:4000]
    historial = data.get("historial", [])

    if not mensaje:
        return jsonify({"error": "No enviaste ningún mensaje"}), 400
    if not isinstance(historial, list):
        historial = []

    for modelo in MODELS:
        usar_thinking = True
        for intento in range(2):
            try:
                kwargs = dict(system_instruction=SYSTEM, max_output_tokens=2048)
                if usar_thinking:
                    kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=THINKING)

                r = client.models.generate_content(
                    model=modelo,
                    contents=build_contents(historial, mensaje),
                    config=types.GenerateContentConfig(**kwargs),
                )
                texto = (r.text or "").strip()
                return jsonify({
                    "respuesta": texto or "No pude generar una respuesta. ¿Puedes repetirlo?",
                    "modelo": modelo,
                })

            except Exception as e:
                print(f"[{modelo}] intento {intento + 1} falló: {e}")
                code = getattr(e, "code", None)

                # El modelo no acepta el ajuste de razonamiento: reintenta sin él
                if usar_thinking and (code == 400 or "thinking" in str(e).lower()):
                    usar_thinking = False
                    continue

                # Saturado o con límite: una pausa corta y un segundo intento
                if code in (429, 503) and intento < 1:
                    time.sleep(1)
                    continue

                break  # pasa al siguiente modelo de la lista

    return jsonify({"error": "Jarvis tuvo un retraso temporal. Intenta de nuevo."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
