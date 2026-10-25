from flask import Flask, request, jsonify, send_file
from google import genai

app = Flask(__name__)

# Tu clave de Google AI Studio
client = genai.Client(api_key="GEMINI_API_KEY")

@app.route("/")
def home():
    return send_file("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    mensaje_usuario = data.get("mensaje", "")
    
    if not mensaje_usuario:
        return jsonify({"error": "No enviaste ningún mensaje"}), 400

    try:
        # AQUÍ CAMBIAMOS EL TONO PARA QUE SEA SÚPER AMIGABLE Y CERCANO
        instrucciones_asistente = (
            "Eres un asistente virtual de desarrollo web frontend muy amigable, entusiasta, "
            "cercano y servicial, exactamente con la personalidad conversacional de Gemini. "
            "Te encanta ayudar a los desarrolladores, usas un tono alegre y motivador (puedes usar emojis con moderación). "
            "Cuando te pidan código HTML, CSS o JavaScript, entrégalo limpio, moderno y funcional, "
            "acompañado de explicaciones claras y sencillas, hablando de 'tú' de forma muy cordial."
        )

        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=mensaje_usuario,
            config={
                "system_instruction": instrucciones_asistente
            }
        )
        
        return jsonify({"respuesta": response.text})

    except Exception as e:
        print(f"Error detallado: {str(e)}")
        return jsonify({"error": str(e)}), 500

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)