#!/usr/bin/env bash

# Iniciar Uvicorn en segundo plano
uvicorn src.main:app --host 0.0.0.0 --port 8000 &

# Esperar activamente hasta que FastAPI responda en el puerto 8000
# (sin depender de netcat, que no viene en la imagen python:3.11-slim;
# se usa el /dev/tcp built-in de bash para probar la conexion)
echo "Esperando a que la API de FastAPI esté lista..."
while ! (exec 3<>/dev/tcp/localhost/8000) 2>/dev/null; do
  sleep 0.5
done
exec 3<&- 3>&-
echo "¡API lista! Iniciando Streamlit..."

# Iniciar Streamlit usando el puerto dinámico de Cloud Run
streamlit run app_ui.py --server.port=${PORT:-8080} --server.address=0.0.0.0
