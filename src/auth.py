"""Autenticacion simple por API key para los endpoints que modifican datos
(POST/PATCH/DELETE). Los GET quedan abiertos: el uso es de lectura interna
(dashboard/reportes) y no exponen ninguna operacion destructiva.

Fail-closed: si la variable de entorno API_KEY no esta configurada, TODAS
las solicitudes a los endpoints protegidos se rechazan (401) en vez de
dejarlas pasar sin proteccion. En produccion hay que exportar API_KEY en
ambos lados (servidor y cliente -- ver app_ui.py::api_request, que agrega
el header X-API-Key automaticamente si esa misma variable esta definida en
el entorno donde corre Streamlit); en desarrollo/tests, quien necesite
ejercitar esos endpoints debe configurar igualmente una API_KEY de prueba
(ver tests/conftest.py)."""
import os
import secrets

from dotenv import load_dotenv
from fastapi import Header, HTTPException, status

load_dotenv()

API_KEY = os.environ.get("API_KEY")


def verificar_api_key(x_api_key: str | None = Header(default=None)) -> None:
    # secrets.compare_digest en vez de != : una comparacion de strings comun
    # corta apenas encuentra el primer caracter distinto, filtrando por
    # temporizacion cuanto de la clave correcta se acerto (timing attack);
    # compare_digest compara en tiempo constante.
    clave_valida = bool(API_KEY) and secrets.compare_digest(x_api_key or "", API_KEY)
    if not clave_valida:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key invalida o faltante (header X-API-Key)",
        )
