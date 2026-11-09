"""Guardas de despliegue: la imagen instala solo requirements.txt, incluye las
dependencias de seguridad y los assets de TinyMCE, y no copia secretos/datos."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _requirements() -> dict[str, str]:
    texto = (RAIZ / "requirements.txt").read_bytes().decode("utf-16")
    return {
        re.split(r"[=<>~]", linea)[0].lower().replace("_", "-"): linea
        for linea in texto.splitlines()
        if linea.strip() and not linea.startswith("#")
    }


def test_dockerfile_instala_requirements_txt_no_dev():
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir -r requirements.txt" in dockerfile
    assert "requirements-dev" not in dockerfile


def test_dependencias_de_seguridad_estan_fijadas_en_requirements():
    req = _requirements()
    for paquete in ("nh3", "argon2-cffi", "argon2-cffi-bindings", "cffi", "pycparser", "pydantic"):
        assert paquete in req and "==" in req[paquete], paquete


def test_paquetes_de_desarrollo_no_van_en_la_imagen():
    req = _requirements()
    for paquete in ("pytest", "ruff", "pip-audit", "iniconfig", "pluggy"):
        assert paquete not in req, paquete


def test_tinymce_vendorizado_existe_y_el_editor_no_usa_cdn():
    base = RAIZ / "assets" / "tinymce_editor"
    for ruta in ("vendor/tinymce/tinymce.min.js", "vendor/tinymce/themes/silver/theme.min.js",
                 "vendor/tinymce/skins/ui/oxide/skin.min.css", "vendor/tinymce/license.txt"):
        assert (base / ruta).is_file(), ruta
    assert "cdnjs" not in (base / "index.html").read_text(encoding="utf-8").replace("antes cargado desde cdnjs", "")


def test_dockerfile_copia_todo_el_arbol_asi_que_los_assets_viajan():
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY \. \.$", dockerfile, re.MULTILINE)
    dockerignore = (RAIZ / ".dockerignore").read_text(encoding="utf-8")
    assert "assets" not in dockerignore.replace("\r", "")


def test_dockerignore_excluye_secretos_y_datos():
    ignorados = (RAIZ / ".dockerignore").read_text(encoding="utf-8")
    for patron in (".env", "respaldos/", "salidas/", "data/*.db", "capturas/", ".streamlit/secrets.toml"):
        assert patron in ignorados, patron


def test_gitignore_excluye_datos_personales():
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    for patron in ("/respaldos/", "/salidas/", "capturas/", "data/*.db", "data/*.sqlite3",
                   "data/oficios_txt/", ".env", ".streamlit/secrets.toml"):
        assert patron in ignorados, patron


def test_dockerfile_actualiza_pip_antes_de_instalar_requirements():
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.index("--upgrade pip") < dockerfile.index("-r requirements.txt")


def test_toml_ya_no_esta_fijado():
    assert "toml" not in _requirements()
