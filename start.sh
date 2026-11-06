#!/usr/bin/env bash

# Si corre en Cloud Run, bajar el snapshot de la base de datos desde Cloud
# Storage a /tmp/sercop.db (ruta que usa DB_PATH ahi, ver src/database.py)
# antes de levantar la API -- solo si /tmp/sercop.db no existe ya (una
# instancia que sigue viva conserva los cambios hechos en vivo; un cold
# start siempre repone el snapshot). Si la descarga falla, se aborta el
# arranque del contenedor en vez de seguir con una base vacia en silencio.
if [ -n "$K_SERVICE" ]; then
    python3 scripts/descargar_snapshot_db.py || exit 1
fi

# Iniciar Uvicorn en segundo plano. SOLO en loopback (127.0.0.1): API y Streamlit
# corren en este mismo contenedor y Streamlit la llama por localhost, asi que la
# API no debe quedar expuesta fuera de el (Cloud Run solo publica $PORT).
uvicorn src.main:app --host 127.0.0.1 --port 8000 &
UVICORN_PID=$!

# Esperar activamente hasta que FastAPI responda en el puerto 8000
# (sin depender de netcat, que no viene en la imagen python:3.11-slim;
# se usa el /dev/tcp built-in de bash para probar la conexion). Si uvicorn
# se cae antes de quedar listo, no tiene sentido levantar streamlit sobre
# una API muerta -- se aborta el contenedor propagando su codigo de salida.
echo "Esperando a que la API de FastAPI esté lista..."
while ! (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; do
    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
        wait "$UVICORN_PID"
        CODIGO=$?
        echo "uvicorn se cerro antes de levantar la API (codigo $CODIGO). Abortando." >&2
        exit "$CODIGO"
    fi
    sleep 0.5
done
exec 3<&- 3>&-
echo "¡API lista! Iniciando Streamlit..."

# Iniciar Streamlit usando el puerto dinámico de Cloud Run
streamlit run app_ui.py --server.port=${PORT:-8080} --server.address=0.0.0.0
