"""Construye la Content-Security-Policy recomendada para servir la app detras de un HTTPS Load Balancer.

Sin 'unsafe-inline' en script-src: los unicos scripts inline que existen se permiten por HASH SHA-256:
- los scripts propios de iframes invisibles (ui/componentes.py::SCRIPT_NO_TRADUCIR y SCRIPT_REVELAR_SIDEBAR);
- los scripts inline del index.html de la version de Streamlit instalada (el hash cambia al actualizar Streamlit).

Uso (desde la raiz del proyecto):

    .venv/Scripts/python.exe scripts/calcular_hashes_csp.py --dominio app.ejemplo.com

Imprime la politica lista para pegar en la cabecera `Content-Security-Policy` del backend service del Load Balancer.
Vuelve a ejecutarlo cada vez que cambies de version de Streamlit o edites esos scripts.
"""
import argparse
import base64
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit  # noqa: E402

from ui.componentes import SCRIPT_NO_TRADUCIR, SCRIPT_REVELAR_SIDEBAR  # noqa: E402

CARTO = "https://basemaps.cartocdn.com https://*.basemaps.cartocdn.com"
PATRON_SCRIPT_INLINE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def hash_csp(texto: str) -> str:
    """'sha256-<base64>' del texto EXACTO entre <script> y </script>."""
    digest = hashlib.sha256(texto.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode() + "'"


def scripts_inline_de_streamlit() -> list[str]:
    index = Path(streamlit.__file__).resolve().parent / "static" / "index.html"
    html = index.read_text(encoding="utf-8")
    return [m for m in PATRON_SCRIPT_INLINE.findall(html) if m.strip()]


def hashes_de_scripts_inline() -> list[str]:
    textos = [SCRIPT_NO_TRADUCIR, SCRIPT_REVELAR_SIDEBAR, *scripts_inline_de_streamlit()]
    return [hash_csp(t) for t in textos]


def construir_csp(dominio: str = "DOMINIO", hashes: list[str] | None = None, frame_ancestors: str = "none") -> str:
    """CSP compatible con Streamlit (websocket, estilos inline de emotion, workers blob:, fuentes de Google
    usadas por estilos_sercop.py), con los iframes del componente TinyMCE vendorizado (mismo origen).

    `frame_ancestors`: "none" (anticlickjacking estricto, pero bloquea el iframe del MISMO origen del
    editor TinyMCE: usarlo solo con una excepcion para /component/*) o "self" (recomendado)."""
    if frame_ancestors not in ("none", "self"):
        raise ValueError("frame_ancestors debe ser 'none' o 'self'")
    hashes = hashes_de_scripts_inline() if hashes is None else hashes
    directivas = [
        "default-src 'self'",
        # 'wasm-unsafe-eval': el cliente de Streamlit (protobuf) compila WebAssembly.
        "script-src 'self' 'wasm-unsafe-eval' " + " ".join(hashes),
        # Streamlit/emotion e TinyMCE escriben estilos inline; no hay forma practica de usar hashes ahi.
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        f"img-src 'self' data: blob: {CARTO}",
        # CARTO: mapa de burbujas/coropletico del Dashboard (estilo y teselas vectoriales dark-matter).
        f"connect-src 'self' wss://{dominio} {CARTO}",
        "worker-src 'self' blob:",
        "frame-src 'self' blob: data:",
        "media-src 'self' blob: data:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        f"frame-ancestors '{frame_ancestors}'",
    ]
    return "; ".join(directivas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dominio", default="DOMINIO", help="Dominio publico del Load Balancer (sin https://)")
    parser.add_argument("--frame-ancestors", choices=("none", "self"), default="none")
    args = parser.parse_args()
    print(construir_csp(args.dominio, frame_ancestors=args.frame_ancestors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
