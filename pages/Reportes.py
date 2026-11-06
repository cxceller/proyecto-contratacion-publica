"""Pagina Streamlit "Reportes" -- URL /Reportes del mismo proceso que
app_ui.py (Streamlit auto-descubre pages/*.py como paginas adicionales,
cada una con su propia URL). Entrypoint minimo: toda la logica vive en
ui/reportes.py.

Se abre en pestaña nueva del navegador desde el boton "Reportes" del
sidebar de app_ui.py (st.link_button a la URL relativa "Reportes"): no
hay que iniciar ningun proceso/puerto aparte, es la misma app.
"""
import streamlit as st

from ui.autenticacion import requerir_login
from ui.reportes import (
    deshabilitar_traduccion_automatica,
    inyectar_estilos_sidebar,
    inyectar_precarga_fuente_iconos,
    render_generador_reportes,
    render_navegacion_sidebar,
    revelar_sidebar_cuando_cargue_fuente_iconos,
)

st.set_page_config(page_title="Reportes - SERCOP Analytics", layout="wide")

requerir_login()

deshabilitar_traduccion_automatica()
inyectar_precarga_fuente_iconos()
inyectar_estilos_sidebar()
revelar_sidebar_cuando_cargue_fuente_iconos()

render_navegacion_sidebar()

st.header(":material/description: Generación de Reportes")
render_generador_reportes()
