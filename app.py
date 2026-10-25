import os
from flask import Flask, request, jsonify, send_file
from google import genai

app = Flask(__name__)

# Leemos la clave de entorno de forma segura al iniciar la aplicación
api_key = os.environ.get("asistente_jarvis")

# Línea de diagnóstico para ver si la clave está llegando correctamente a los logs de Render
print(f"DEBUG - API KEY leída: {api_key[:5] if api_key else 'NO EXISTE'}")

if not api_key:
    raise ValueError("No se encontró la variable de entorno 'asistente_jarvis' en el servidor.")

# Inicializamos el cliente correctamente fuera de las rutas
client = genai.Client(api_key=api_key)

@app.route("/")
def home():
    return send_file("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        mensaje_usuario = data.get("mensaje", "")
        
        if not mensaje_usuario:
            return jsonify({"error": "No enviaste ningún mensaje"}), 400

        # Personalidad de tu asistente
        instrucciones_asistente = (
            "Eres un asistente virtual de desarrollo web frontend muy amigable, entusiasta, "
            "cercano y servicial, exactamente con la personalidad conversacional de Gemini. "
            "Te encanta ayudar a los desarrolladores, usas un tono alegre y motivador (puedes usar emojis con moderación). "
            "Cuando te pidan código HTML, CSS o JavaScript, entrégalo limpio, moderno y funcional, "
            "acompañado de explicaciones claras y sencillas, hablando de 'tú' de forma muy cordial."
        )

        # Llamada al modelo con las instrucciones y el mensaje del usuario
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{instrucciones_asistente}\n\nPregunta del usuario: {mensaje_usuario}",
        )
        
        return jsonify({"respuesta": response.text})

    except Exception as e:
        print(f"Error detallado: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)