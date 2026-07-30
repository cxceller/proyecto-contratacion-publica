"""Autenticacion simple por API key para los endpoints que modifican datos
(POST/PATCH/DELETE). Los GET quedan abiertos: el uso es de lectura interna
(dashboard/reportes) y no exponen ninguna operacion destructiva.

Si la variable de entorno API_KEY no esta configurada, la proteccion queda
desactivada (asi los tests y el desarrollo local siguen funcionando sin
configuracion extra); en produccion basta con exportar API_KEY para
activarla en ambos lados (servidor y cliente -- ver app_ui.py::api_request,
que agrega el header X-API-Key automaticamente si esa misma variable esta
definida en el entorno donde corre Streamlit)."""
import os

from fastapi import Header, HTTPException, status

API_KEY = os.environ.get("API_KEY")


def verificar_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key invalida o faltante (header X-API-Key)",
        )
