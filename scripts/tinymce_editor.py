"""Componente Streamlit propio (assets/tinymce_editor/index.html) que
envuelve TinyMCE real (Community, LGPL-2.0, vendorizado en
assets/tinymce_editor/vendor/ -- sin CDN ni API key) como editor de texto enriquecido -- "streamlit-tinymce" no existe
como paquete de PyPI, asi que en vez de un pip install se construyo un
componente estatico (protocolo crudo de Streamlit Components, sin
build de Node) que carga TinyMCE con los plugins paste/table/image y
paste_data_images=True, para poder pegar tablas e imagenes copiadas
desde Excel/Word manteniendo su estructura.

No requiere internet: los archivos de TinyMCE 6.8.3 son locales (ver assets/tinymce_editor/vendor/README.md)."""
from pathlib import Path

import streamlit.components.v1 as components

_DIRECTORIO_COMPONENTE = Path(__file__).resolve().parent.parent / "assets" / "tinymce_editor"

_editor_enriquecido = components.declare_component(
    "tinymce_editor", path=str(_DIRECTORIO_COMPONENTE)
)


def tinymce_editor(value: str = "", height: int = 400, key: str | None = None) -> str:
    """Renderiza el editor y devuelve el HTML actual (se actualiza en cada
    rerun a medida que el usuario edita). `value` solo se usa para el
    contenido INICIAL del editor -- una vez montado, el componente
    conserva su propio estado interno (igual que cualquier widget nativo)
    hasta que Streamlit lo desmonte."""
    return _editor_enriquecido(value=value, height=height, key=key, default=value)
