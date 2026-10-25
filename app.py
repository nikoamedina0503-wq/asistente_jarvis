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

MODEL = "gemini-2.5-flash"
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

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        max_output_tokens=1024,
        thinking_config=types.ThinkingConfig(thinking_budget=0),  # respuestas más rápidas
    )

    for intento in range(3):
        try:
            r = client.models.generate_content(
                model=MODEL,
                contents=build_contents(historial, mensaje),
                config=config,
            )
            texto = (r.text or "").strip()
            return jsonify({
                "respuesta": texto or "No pude generar una respuesta. ¿Puedes repetirlo?"
            })
        except Exception as e:
            print(f"Intento {intento + 1} falló: {e}")
            if getattr(e, "code", None) in (429, 503) and intento < 2:
                time.sleep(2 ** intento)  # espera 1 s y luego 2 s
                continue
            break

    return jsonify({"error": "Jarvis tuvo un retraso temporal. Intenta de nuevo."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
