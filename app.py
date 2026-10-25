import os
import json
import time
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from google import genai
from google.genai import types

load_dotenv()

app = Flask(__name__)  # sirve automáticamente /static/...
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 86400  # caché de 1 día para imágenes y CSS

# Render está detrás de un proxy: así Flask ve la IP real del visitante
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

# ---------- Límite de uso (por IP) ----------
CHAT_LIMIT = os.environ.get("CHAT_LIMIT", "10 per minute;100 per day")
limiter = Limiter(key_func=get_remote_address, app=app, storage_uri="memory://")

# ---------- Gemini ----------
api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("asistente_jarvis")
if not api_key:
    raise ValueError("Falta la variable de entorno GEMINI_API_KEY en el servidor.")

client = genai.Client(api_key=api_key)

# Se pueden cambiar desde Render > Environment sin tocar el código
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
FALLBACKS = [m.strip() for m in os.environ.get(
    "GEMINI_FALLBACKS", "gemini-3.8-flash,gemini-3.5-flash-lite").split(",") if m.strip()]
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


@app.errorhandler(429)
def demasiadas_solicitudes(e):
    return jsonify({"error": "Demasiadas solicitudes. Espera un momento e intenta de nuevo."}), 429


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


def sse(obj):
    """Formatea un evento Server-Sent Events."""
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def generar_stream(historial, mensaje):
    contents = build_contents(historial, mensaje)

    for modelo in MODELS:
        usar_thinking = True
        ya_reintento = False

        for _ in range(3):
            enviado = False
            try:
                kwargs = dict(system_instruction=SYSTEM, max_output_tokens=2048)
                if usar_thinking:
                    kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=THINKING)

                stream = client.models.generate_content_stream(
                    model=modelo,
                    contents=contents,
                    config=types.GenerateContentConfig(**kwargs),
                )
                for chunk in stream:
                    texto = chunk.text or ""
                    if texto:
                        enviado = True
                        yield sse({"t": texto})

                if not enviado:
                    yield sse({"t": "No pude generar una respuesta. ¿Puedes repetirlo?"})
                yield sse({"done": True, "modelo": modelo})
                return

            except Exception as e:
                print(f"[{modelo}] falló: {e}")
                if enviado:
                    # Ya se envió texto parcial: no se puede cambiar de modelo
                    yield sse({"error": "La respuesta se cortó. Intenta de nuevo."})
                    return

                code = getattr(e, "code", None)

                # El modelo no acepta el ajuste de razonamiento: reintenta sin él
                if usar_thinking and (code == 400 or "thinking" in str(e).lower()):
                    usar_thinking = False
                    continue

                # Saturado o con límite: una pausa corta y un segundo intento
                if code in (429, 503) and not ya_reintento:
                    ya_reintento = True
                    time.sleep(1)
                    continue

                break  # pasa al siguiente modelo de la lista

    yield sse({"error": "Jarvis tuvo un retraso temporal. Intenta de nuevo."})


@app.route("/chat", methods=["POST"])
@limiter.limit(CHAT_LIMIT)
def chat():
    data = request.get_json(silent=True) or {}
    mensaje = str(data.get("mensaje", "")).strip()[:4000]
    historial = data.get("historial", [])

    if not mensaje:
        return jsonify({"error": "No enviaste ningún mensaje"}), 400
    if not isinstance(historial, list):
        historial = []

    return Response(
        stream_with_context(generar_stream(historial, mensaje)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
