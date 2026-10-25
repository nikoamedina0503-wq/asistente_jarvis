from dotenv import load_dotenv
load_dotenv()

import os
from flask import Flask, request, jsonify, send_file
from google import genai

app = Flask(__name__)

api_key = os.environ.get("asistente_jarvis")
print(f"DEBUG - API KEY leída: {api_key[:5] if api_key else 'NO EXISTE'}")

if not api_key:
    raise ValueError("No se encontró la variable de entorno 'asistente_jarvis' en el servidor.")

client = genai.Client(api_key=api_key)

@app.route("/")
def home():
    return send_file("index.html")

# Ruta para servir el archivo CSS separado
@app.route("/style.css")
def serve_css():
    return send_file("style.css")

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        mensaje_usuario = data.get("mensaje", "")
        
        if not mensaje_usuario:
            return jsonify({"error": "No enviaste ningún mensaje"}), 400

        instrucciones_asistente = (
            "Eres Jarvis, un asistente virtual de desarrollo web frontend muy amigable, entusiasta, "
            "cercano y servicial. "
            "Si el usuario aún no te ha dicho su nombre, pregúntaselo de forma cordial al inicio "
            "para poder dirigirte a él o ella por su nombre en adelante. "
            "Te encanta ayudar a los desarrolladores, usas un tono alegre y motivador (puedes usar emojis con moderación). "
            "Cuando te pidan código HTML, CSS o JavaScript, entrégalo limpio, moderno y funcional, "
            "acompañado de explicaciones claras y sencillas, hablando de 'tú' de forma muy cordial."
        )

        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=f"{instrucciones_asistente}\n\nPregunta del usuario: {mensaje_usuario}",
        )
        
        return jsonify({"respuesta": response.text})

    except Exception as e:
        print(f"Error detallado: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)