"""Politica CSP recomendada (scripts/calcular_hashes_csp.py): sin 'unsafe-inline'/'unsafe-eval' en script-src, con
hashes de TODOS los scripts inline y compatible con el componente TinyMCE vendorizado (sin scripts inline)."""
import base64
import hashlib
import re
from pathlib import Path

from scripts import calcular_hashes_csp as csp
from ui.componentes import SCRIPT_NO_TRADUCIR, SCRIPT_REVELAR_SIDEBAR

RAIZ = Path(__file__).resolve().parent.parent


def _directiva(politica: str, nombre: str) -> str:
    return next(d for d in politica.split("; ") if d.startswith(nombre + " ") or d == nombre)


def test_hash_csp_es_sha256_base64_del_texto_exacto():
    esperado = "'sha256-" + base64.b64encode(hashlib.sha256(b"alert(1)").digest()).decode() + "'"
    assert csp.hash_csp("alert(1)") == esperado


def test_script_src_sin_unsafe_inline_ni_unsafe_eval():
    script = _directiva(csp.construir_csp("app.ejemplo.com"), "script-src")
    assert "'unsafe-inline'" not in script and "'unsafe-eval'" not in script
    assert "'self'" in script and "'wasm-unsafe-eval'" in script  # protobuf de Streamlit usa WebAssembly


def test_incluye_el_hash_de_cada_script_inline_propio_y_de_streamlit():
    politica = csp.construir_csp("app.ejemplo.com")
    assert csp.hash_csp(SCRIPT_NO_TRADUCIR) in politica and csp.hash_csp(SCRIPT_REVELAR_SIDEBAR) in politica
    inline_streamlit = csp.scripts_inline_de_streamlit()
    assert inline_streamlit, "el index.html de Streamlit trae al menos un script inline"
    assert all(csp.hash_csp(t) in politica for t in inline_streamlit)


def test_directivas_clave():
    politica = csp.construir_csp("app.ejemplo.com")
    assert "default-src 'self'" in politica and "object-src 'none'" in politica and "base-uri 'self'" in politica
    assert "frame-ancestors 'none'" in politica and "form-action 'self'" in politica
    assert "connect-src 'self' wss://app.ejemplo.com" in politica  # websocket de Streamlit
    assert "worker-src 'self' blob:" in politica
    assert "http://" not in politica  # nada cargado sin TLS


def test_el_componente_tinymce_no_tiene_scripts_inline():
    html = (RAIZ / "assets" / "tinymce_editor" / "index.html").read_text(encoding="utf-8")
    inline = [m for m in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.DOTALL) if m.strip()]
    assert inline == []
    assert (RAIZ / "assets" / "tinymce_editor" / "editor.js").is_file()


def test_los_scripts_invisibles_se_ejecutan_desde_constantes():
    fuentes = (RAIZ / "app_ui.py").read_text(encoding="utf-8") + (RAIZ / "ui" / "reportes.py").read_text(encoding="utf-8")
    # ningun literal HTML/JS suelto pasa a ejecutar_html_invisible: todos van por ui/componentes.py (hasheables)
    assert not re.search(r"ejecutar_html_invisible\(\s*(f?\"\"\"|f?\"|f?')", fuentes)
