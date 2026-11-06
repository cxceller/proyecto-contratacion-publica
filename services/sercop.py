"""Capa de servicios: toda llamada a la API de FastAPI (Contratación
Pública Ecuador / SERCOP Analytics) vive acá -- `app_ui.py` (la capa de
UI de Streamlit) solo importa y usa estas funciones, sin conocer URLs,
métodos HTTP ni la estructura de la base de datos (Fase 6 del refactor
UI: "separar la capa de datos del backend").

Los reads que alimentan gráficos/tablas y se consultan al navegar entre
vistas (`obtener_contrataciones`) quedan cacheados con
`@st.cache_data(ttl=600)` para no volver a golpear el backend en cada
rerun. Los CRUD de borradores (`listar_borradores`, `obtener_borrador`,
`guardar_borrador`, `eliminar_borrador`) se dejan SIN cache a propósito:
deben reflejar de inmediato cualquier guardado/eliminado hecho en el
propio rerun anterior -- un TTL, por corto que sea, mostraría el
selectbox de borradores desactualizado justo después de guardar o
borrar."""

import os

import requests
import streamlit as st

from src.logging_config import obtener_logger

logger = obtener_logger(__name__)

API_URL = os.environ.get("API_URL", "http://localhost:8000")


def api_request(method: str, path: str, timeout: int = 10, **kwargs):
    """Wrapper HTTP de bajo nivel, único punto del módulo (y de toda la
    app) que sabe que el backend es FastAPI sobre HTTP: agrega la
    cabecera X-API-Key si la variable de entorno API_KEY está configurada
    del lado del servidor (ver src/auth.py) y muestra un st.error si la
    API no responde. Devuelve el `requests.Response` crudo (o None si la
    conexión falló) -- las funciones de este módulo interpretan el status
    code, no la UI."""
    api_key = os.environ.get("API_KEY")
    if api_key:
        headers = {"X-API-Key": api_key, **kwargs.pop("headers", {})}
        kwargs["headers"] = headers
    try:
        response = requests.request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
    except requests.exceptions.RequestException as exc:
        # El detalle (URL interna, mensaje de requests) va al log, no a la UI.
        logger.error("Fallo la llamada a la API (%s %s): %s", method, path, type(exc).__name__)
        st.error("No se pudo conectar con el servicio de datos. Verifica que la API esté en ejecución e inténtalo de nuevo.")
        return None
    return response


@st.cache_data(ttl=600)
def obtener_contrataciones(status=None, fecha_inicio=None, fecha_fin=None, palabra_clave=None) -> list[dict]:
    params = {}
    if status:
        # El query param se llama "estado" en la API (ver
        # src/main.py::listar_contrataciones) -- se renombro para no
        # colisionar con el modulo `status` de FastAPI importado ahi mismo.
        params["estado"] = status
    if fecha_inicio:
        params["fecha_inicio"] = fecha_inicio.isoformat()
    if fecha_fin:
        params["fecha_fin"] = fecha_fin.isoformat()
    if palabra_clave:
        params["palabra_clave"] = palabra_clave

    response = api_request("GET", "/api/todos", params=params)
    if response is None:
        return []
    if response.status_code != 200:
        st.error(f"Error al consultar la API: {response.status_code}")
        return []
    return response.json()


def listar_borradores_especificaciones_tecnicas() -> list[dict]:
    response = api_request("GET", "/api/borradores")
    if response is None:
        return []
    if response.status_code != 200:
        st.error(f"Error al consultar los borradores guardados: {response.status_code}")
        return []
    return response.json()


def obtener_borrador_especificaciones_tecnicas(borrador_id: int) -> dict | None:
    response = api_request("GET", f"/api/borradores/{borrador_id}")
    if response is None:
        return None
    if response.status_code != 200:
        st.error(f"Error al cargar el borrador: {response.status_code}")
        return None
    return response.json()


def guardar_borrador_especificaciones_tecnicas(borrador_id: int | None, nombre_contratacion: str, datos_json: str) -> dict | None:
    """Crea (borrador_id is None) o reemplaza (borrador_id dado) un
    borrador. Siempre manda el registro completo -- no hay actualizacion
    parcial de un borrador, ver BorradorContratacionUpsert."""
    payload = {"nombre_contratacion": nombre_contratacion, "datos_json": datos_json}
    if borrador_id is None:
        response = api_request("POST", "/api/borradores", json=payload)
    else:
        response = api_request("PUT", f"/api/borradores/{borrador_id}", json=payload)
    if response is None:
        return None
    if response.status_code not in (200, 201):
        st.error(f"Error al guardar el progreso: {response.status_code} {response.text}")
        return None
    return response.json()


def eliminar_borrador_especificaciones_tecnicas(borrador_id: int) -> bool:
    response = api_request("DELETE", f"/api/borradores/{borrador_id}")
    if response is None:
        return False
    if response.status_code != 204:
        st.error(f"Error al eliminar la contratación: {response.status_code}")
        return False
    return True


def generar_reporte(payload: dict, timeout: int = 60):
    """POST /api/generar-reporte -- devuelve el `requests.Response` crudo
    (o None si la API no respondió): la UI interpreta el status code
    (200/404/422/otro) y decide qué mostrar, esta funcion solo hace la
    llamada."""
    return api_request("POST", "/api/generar-reporte", json=payload, timeout=timeout)


def vaciar_base_datos():
    """DELETE /api/todos -- devuelve el `requests.Response` crudo (o
    None): la UI interpreta el status code (204 = éxito) y decide qué
    mostrar."""
    return api_request("DELETE", "/api/todos")
