"""Lista blanca de URLs que los scripts de Playwright pueden visitar.

Los scripts de actualizacion leen la `url` de cada proceso desde la base de
datos; si esa columna se envenena (POST con API key, CSV importado), el
navegador visitaria cualquier direccion (SSRF hacia la red local, por
ejemplo). Solo se aceptan URLs https del portal oficial de SERCOP."""
from urllib.parse import urlparse

HOSTS_PERMITIDOS = frozenset({"www.compraspublicas.gob.ec", "compraspublicas.gob.ec"})


def url_portal_valida(url: str | None) -> bool:
    """True solo para https://[www.]compraspublicas.gob.ec[:443]/... sin
    credenciales embebidas (usuario:clave@)."""
    if not url or not isinstance(url, str):
        return False
    try:
        partes = urlparse(url.strip())
        puerto = partes.port  # puede lanzar ValueError si es invalido
    except ValueError:
        return False
    return (
        partes.scheme == "https"
        and (partes.hostname or "").lower() in HOSTS_PERMITIDOS
        and puerto in (None, 443)
        and partes.username is None
        and partes.password is None
    )
