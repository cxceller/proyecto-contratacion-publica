"""Widgets pequeños reutilizados por mas de una pagina de app_ui.py (P1-2
del plan de mejoras) -- separados aca en vez de en ui/tema.py (que son
constantes, no funciones) o repetidos en cada pagina."""
from collections.abc import Callable

import streamlit as st
import streamlit.components.v1 as components


def boton_limpiar_filtros(claves: list[str], key: str, *, on_clear: Callable[[], None] | None = None) -> None:
    """Boton "Limpiar filtros": popea `claves` de session_state y hace
    st.rerun(). Antes esta misma mecanica (popear claves de los widgets de
    filtro + rerun) estaba escrita por separado en el Dashboard, Procesos
    y Reportes -- un solo lugar evita que diverjan sin querer.

    `on_clear` (opcional) corre ademas del pop de `claves`, para limpiar
    estado adicional que no es una simple key de widget de filtro (ej. en
    Procesos, "Limpiar filtros" tambien debe resetear
    `st.session_state.resultados` a None, no solo las keys de los campos
    de busqueda).

    El placement (columna, contenedor) lo decide el caller envolviendo el
    llamado en un `with columna:` si hace falta -- esta funcion solo usa
    `st.button` sobre el contenedor "actual", no crea su propia columna."""
    # Solo icono + tooltip: con el texto completo se truncaba ("Limpiar fil...") en columnas
    # angostas; `help` lo explica al pasar el cursor.
    if st.button(":material/filter_alt_off:", key=key, help="Limpiar filtros", width="stretch"):
        for clave in claves:
            st.session_state.pop(clave, None)
        if on_clear:
            on_clear()
        st.rerun()


def ejecutar_html_invisible(codigo_html: str) -> None:
    """Inserta un <script>/HTML PROPIO (nunca contenido de usuario: el iframe
    ejecuta JavaScript con acceso al documento de la app) en un iframe de altura 0.
    `components.html` esta deprecado y se elimina (fecha de remocion ya vencida);
    `st.iframe` (Streamlit >= 1.56) lo reemplaza. Se conserva el respaldo para
    versiones anteriores."""
    if hasattr(st, "iframe"):
        # st.iframe no admite height=0 (minimo 1 px); el CSS de app_ui.py/ui.reportes
        # saca de flujo estos contenedores para que no sumen espacio vertical.
        st.iframe(codigo_html, height=1)
    else:  # pragma: no cover -- solo Streamlit < 1.56
        components.html(codigo_html, height=0)


# JavaScript PROPIO que corre en un iframe invisible (acceso al documento padre). Constantes
# (no literales sueltos) para poder calcular su hash SHA-256 y permitirlas en la CSP sin
# 'unsafe-inline' -- ver scripts/calcular_hashes_csp.py y la seccion "HTTPS Load Balancer" del README.
# Evita que Google Translate mangle los iconos (ligaduras de texto de Material Symbols).
SCRIPT_NO_TRADUCIR = """
const meta = window.parent.document.createElement('meta');
meta.name = 'google';
meta.content = 'notranslate';
window.parent.document.head.appendChild(meta);
window.parent.document.documentElement.setAttribute('translate', 'no');
window.parent.document.documentElement.classList.add('notranslate');
"""

# Revela el contenido del sidebar (opacity:1) cuando la fuente de iconos ya cargo, para evitar el
# flash del nombre crudo del icono. Con try/except y respaldo si `document.fonts` no existe.
SCRIPT_REVELAR_SIDEBAR = """
(function () {
    function revelar() {
        try {
            var el = window.parent.document.querySelector('[data-testid="stSidebarUserContent"]');
            if (el) { el.style.opacity = '1'; }
        } catch (e) { /* nada mas que hacer desde aca */ }
    }
    try {
        window.parent.document.fonts.ready.then(revelar);
    } catch (e) {
        revelar();
    }
})();
"""


def ejecutar_script_invisible(js: str) -> None:
    """Ejecuta `js` (constante propia, ver arriba) en un iframe invisible."""
    ejecutar_html_invisible(f"<script>{js}</script>")
