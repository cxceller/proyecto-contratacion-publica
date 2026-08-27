"""Widgets pequeños reutilizados por mas de una pagina de app_ui.py (P1-2
del plan de mejoras) -- separados aca en vez de en ui/tema.py (que son
constantes, no funciones) o repetidos en cada pagina."""
from collections.abc import Callable

import streamlit as st


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
    if st.button(":material/filter_alt_off: Limpiar filtros", key=key, use_container_width=True):
        for clave in claves:
            st.session_state.pop(clave, None)
        if on_clear:
            on_clear()
        st.rerun()
