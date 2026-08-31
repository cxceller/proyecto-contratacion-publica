#!/usr/bin/env bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 &

echo "Esperando a que la API (uvicorn, puerto 8000) este lista..."
for i in $(seq 1 30); do
    if (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; then
        exec 3<&- 3>&-
        echo "API lista."
        break
    fi
    sleep 1
done

streamlit run app_ui.py --server.port=${PORT:-8080} --server.address=0.0.0.0
