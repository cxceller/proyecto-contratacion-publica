#!/usr/bin/env bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 &
streamlit run app_ui.py --server.port=${PORT:-8080} --server.address=0.0.0.0
