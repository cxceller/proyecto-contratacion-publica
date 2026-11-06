"""Logging central de la app (API, UI Streamlit y scripts).

El detalle tecnico de cualquier fallo (rutas, SQL, mensajes de librerias)
va SOLO al log; al usuario se le muestra un mensaje generico. Nivel desde la
variable de entorno LOG_LEVEL (DEBUG/INFO/WARNING/ERROR, default INFO).

Nunca registrar secretos (API_KEY, ANTHROPIC_API_KEY, APP_CLAVE, hashes),
cabeceras Authorization/X-API-Key ni contenido completo de borradores o
archivos subidos."""
import logging
import os

_FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configurado = False


def configurar_logging() -> None:
    """Idempotente: Streamlit re-ejecuta el script en cada rerun, y no debe
    duplicar handlers."""
    global _configurado
    if _configurado:
        return
    nivel = os.environ.get("LOG_LEVEL", "INFO").upper()
    if nivel not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        nivel = "INFO"
    raiz = logging.getLogger()
    if not raiz.handlers:
        logging.basicConfig(level=nivel, format=_FORMATO)
    else:
        raiz.setLevel(nivel)
    _configurado = True


def obtener_logger(nombre: str) -> logging.Logger:
    configurar_logging()
    return logging.getLogger(nombre)
