"""Pagina 'Reportes' -- Generación de Reportes Automáticos (.docx).

Vivio un tiempo como proyecto independiente ("Estudio de Mercado SERCOP",
tema_5/Estudio de mercado SERCOP) que leia esta misma base de datos y
capturas/ en modo solo lectura via variables de entorno cruzadas, en su
propio proceso Streamlit (puerto 8502) -- volvio a este proyecto para no
depender de arrancar un segundo servidor aparte. Ahora es una pagina mas
de Streamlit (ver pages/Reportes.py), servida por el MISMO proceso que
app_ui.py (`streamlit run app_ui.py`), en la URL /Reportes -- el boton
"Reportes" del sidebar de app_ui.py apunta ahi con st.link_button, que
abre en pestaña nueva del navegador por defecto (mismo origen/puerto que
la app principal, no una URL/IP externa).

Requiere login (APP_USUARIO/APP_CLAVE_HASH en .env, ver
ui/autenticacion.py::requerir_login), el mismo que el resto de la app --
fail-closed: si no estan configurados, nadie puede entrar.
"""
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from scripts import reportes_capturas as capturas
from scripts.formato_ec import limpiar_texto_libre
from scripts.reportes_generator import generar_reporte
from src import database
from src.logging_config import obtener_logger
from ui.componentes import (
    SCRIPT_NO_TRADUCIR,
    SCRIPT_REVELAR_SIDEBAR,
    boton_limpiar_filtros,
    ejecutar_script_invisible,
)
from ui.tema import COLOR_SIDEBAR_ACENTO, COLOR_SIDEBAR_FONDO, COLOR_SIDEBAR_TEXTO, COLOR_SIDEBAR_TEXTO_ACTIVO

load_dotenv()

logger = obtener_logger(__name__)

MAX_LARGO_PALABRA_CLAVE_REPORTE = 100
MAX_LARGO_TEXTO_PALABRAS_CLAVE = 1000
SIN_LOTE_ESPECIFICO = "(Ninguno — usar todo el rango de fechas)"
DIRECTORIO_SALIDAS_REPORTES = Path(__file__).resolve().parent.parent / "salidas" / "reportes"


def validar_rango_fechas(fecha_inicio, fecha_fin) -> None:
    """Sin esto, un rango invertido no da error aca, llega intacto a la
    consulta SQL (BETWEEN con limites cruzados no devuelve filas) y el
    resultado es "no se encontraron procesos", un mensaje confuso que no
    explica la causa real."""
    if fecha_inicio > fecha_fin:
        raise ValueError("La fecha de inicio debe ser anterior a la fecha de fin")


def inyectar_estilos_sidebar() -> None:
    """CSS del panel lateral -- calcado de
    app_ui.py::_inyectar_estilos_sidebar (sin la regla especifica del
    logo de Municipalidad de Guayaquil, que no aplica aca). Se duplica en
    vez de importarse de app_ui.py para que esta pagina no dependa de que
    ese modulo (con toda la logica del Dashboard/Procesos) se importe
    entero solo por un helper de CSS."""
    st.markdown(
        f"""
        <style>
        [data-testid="stSidebar"] {{
            background-color: {COLOR_SIDEBAR_FONDO};
        }}
        [data-testid="stSidebar"] * {{
            color: {COLOR_SIDEBAR_TEXTO};
        }}
        .st-key-sercop_brand {{
            padding: 0.25rem 0 1.5rem 0;
        }}
        .st-key-sercop_brand p {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 1.05rem;
            font-weight: 700;
            color: {COLOR_SIDEBAR_TEXTO_ACTIVO} !important;
            letter-spacing: 0.02em;
            margin: 0;
        }}
        .st-key-sercop_brand [role="img"] {{
            font-size: 1.3rem;
        }}
        .sercop-nav-label {{
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.09em;
            color: {COLOR_SIDEBAR_TEXTO} !important;
            text-transform: uppercase;
            border-bottom: 2px solid {COLOR_SIDEBAR_ACENTO};
            padding-bottom: 0.6rem;
            margin-bottom: 0.85rem;
        }}
        .st-key-sercop_nav_item_activo {{
            background-color: rgba(255, 255, 255, 0.10);
            border-left: 3px solid {COLOR_SIDEBAR_ACENTO};
            border-radius: 4px;
            padding: 0.55rem 0.8rem;
            margin-bottom: 0.15rem;
        }}
        /* Streamlit fija un ancho en px (via CSS-in-JS) a TODA la cadena de
        wrappers de un st.markdown (stMarkdown, stMarkdownContainer, el
        <p>...) igual al ancho del contenedor medido ANTES de aplicar el
        padding de arriba -- por eso el padding-left corre el texto hacia
        la derecha pero su ancho no se achica, y termina saliendose por
        fuera del recuadro (pegado/"cortado" contra el borde derecho en
        vez de tener aire alrededor). El "*" fuerza a TODOS los
        descendientes a re-calcular su ancho de forma normal (auto, segun
        el padre real) en vez de copiar ese valor fijo -- confirmado
        midiendo los bounding boxes con Playwright: sin esto el texto
        sobresalia 15.8px del recuadro, con esto queda con el mismo aire
        (12.8px = 0.8rem) que el padding-left.*/
        .st-key-sercop_nav_item_activo * {{
            width: auto !important;
            max-width: 100% !important;
        }}
        .st-key-sercop_nav_item_activo p {{
            color: {COLOR_SIDEBAR_TEXTO_ACTIVO} !important;
            font-weight: 600;
            letter-spacing: 0.02em;
            margin: 0;
        }}
        [data-testid="stSidebar"] hr {{
            border-color: rgba(255, 255, 255, 0.12);
        }}
        [data-testid="stSidebarUserContent"] {{
            opacity: 0;
            transition: opacity 0.15s ease-in;
        }}
        @keyframes sercop-sidebar-respaldo-revelar {{
            to {{ opacity: 1; }}
        }}
        [data-testid="stSidebarUserContent"] {{
            animation: sercop-sidebar-respaldo-revelar 0.01s linear 4s forwards;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def revelar_sidebar_cuando_cargue_fuente_iconos() -> None:
    """Ver app_ui.py::_revelar_sidebar_cuando_cargue_fuente_iconos
    (copiada tal cual)."""
    ejecutar_script_invisible(SCRIPT_REVELAR_SIDEBAR)


def deshabilitar_traduccion_automatica() -> None:
    """Ver app_ui.py::_deshabilitar_traduccion_automatica (copiada tal
    cual: evita que Google Translate mangle los iconos de Material
    Symbols, que son ligaduras de texto)."""
    ejecutar_script_invisible(SCRIPT_NO_TRADUCIR)


def _url_preload_fuente_material_symbols() -> str | None:
    """Ver app_ui.py::_url_preload_fuente_material_symbols (copiada tal
    cual: localiza el .woff2 de Material Symbols dentro del propio
    paquete de Streamlit instalado, para precargarlo y evitar el flash de
    texto crudo del nombre del icono en la carga inicial)."""
    directorio_media = Path(st.__file__).resolve().parent / "static" / "static" / "media"
    try:
        candidatos = sorted(directorio_media.glob("MaterialSymbols-Rounded*.woff2"))
    except OSError:
        return None
    if not candidatos:
        return None
    return f"./static/media/{candidatos[0].name}"


def inyectar_precarga_fuente_iconos() -> None:
    url_fuente = _url_preload_fuente_material_symbols()
    if url_fuente is None:
        return
    st.markdown(
        f'<link rel="preload" as="font" type="font/woff2" crossorigin href="{url_fuente}">',
        unsafe_allow_html=True,
    )


def render_navegacion_sidebar() -> None:
    with st.sidebar:
        with st.container(key="sercop_brand"):
            st.markdown(":material/description: **REPORTES SERCOP**")
        st.markdown('<div class="sercop-nav-label">MÓDULOS</div>', unsafe_allow_html=True)
        # Item de navegacion unico (no hay mas paginas en este modulo
        # todavia): se muestra como texto ya activo, no como boton -- nada
        # a lo que hacer clic. El shortcode :material/...: solo se
        # resuelve en texto "normal" de st.markdown, no dentro de HTML
        # crudo (unsafe_allow_html) -- por eso el icono va en un
        # st.markdown aparte, dentro de un container con key (mismo
        # patron que sercop_brand arriba) para poder darle estilo de
        # "item activo" via CSS (.st-key-sercop_nav_item_activo).
        with st.container(key="sercop_nav_item_activo"):
            st.markdown(":material/description:&nbsp;&nbsp;GENERACIÓN DE REPORTES")


def render_generador_reportes() -> None:
    """Seccion 'Generación de Reportes Automáticos': arma el .docx
    directamente con scripts/reportes_generator.py, consultando
    src/database.py (la misma base de datos que el resto de la app, sin
    variables de entorno ni conexion de solo lectura aparte -- ya es el
    mismo proyecto)."""
    st.subheader(":material/description: Generación de Reportes Automáticos")
    st.caption(
        "Genera un informe Word (.docx) con las capturas de pantalla y la "
        "tabla de procesos de una o varias palabras clave."
    )

    try:
        capturas.verificar_capturas_dir_disponible()
    except capturas.CapturasNoDisponiblesError as exc:
        st.warning(
            f":material/warning: {exc} El reporte se generará sin capturas de pantalla."
        )

    if "reporte_docx_bytes" not in st.session_state:
        st.session_state.reporte_docx_bytes = None
    if "reporte_docx_nombre" not in st.session_state:
        st.session_state.reporte_docx_nombre = None

    claves_filtro_reportes = [
        "reportes_palabras_clave",
        "reportes_fecha_inicio",
        "reportes_fecha_fin",
        "reportes_lote_id",
        "reportes_llenar_observaciones",
    ]
    boton_limpiar_filtros(claves_filtro_reportes, key="reportes_limpiar_filtros")

    with st.form("form_generar_reporte"):
        palabras_clave_texto = st.text_input(
            "Palabras clave (separadas por comas)",
            placeholder="Ej: luminarias, repotenciacion",
            key="reportes_palabras_clave",
            max_chars=MAX_LARGO_TEXTO_PALABRAS_CLAVE,
            help="Hasta 10 palabras clave de máximo 100 caracteres cada una.",
        )
        col_inicio, col_fin = st.columns(2)
        fecha_inicio = col_inicio.date_input(
            "Fecha inicio", value=None, key="reportes_fecha_inicio", format="DD/MM/YYYY"
        )
        fecha_fin = col_fin.date_input("Fecha fin", value=None, key="reportes_fecha_fin", format="DD/MM/YYYY")

        with st.expander("Opciones avanzadas", expanded=False):
            opciones_lote = capturas.opciones_lote_id(database.get_all_contrataciones())
            etiqueta_lote_sel = st.selectbox(
                "Lote de carga específico (opcional)",
                [SIN_LOTE_ESPECIFICO] + list(opciones_lote.keys()),
                key="reportes_lote_id",
                help=(
                    "Si se indica, acota el reporte a una única ejecución de "
                    "scraping/importación en vez de todo el rango de fechas."
                ),
            )
            llenar_observaciones = st.checkbox(
                "Llenar Observaciones con 'NO APLICA'",
                value=True,
                key="reportes_llenar_observaciones",
                help=(
                    "Si está marcado (por defecto), la columna Observaciones de la "
                    "tabla lleva el texto fijo de exclusión + el objeto del proceso "
                    "completo en todas las filas. Destildar para dejarla vacía."
                ),
            )
        enviado = st.form_submit_button(
            ":material/edit_document: Generar Reporte Word", type="primary", width="stretch"
        )

    if enviado:
        # Saneado (Unicode NFC, sin caracteres de control) y acotado: cada palabra
        # genera un LIKE, asi que se limita cantidad y largo.
        palabras_clave = [
            limpiar_texto_libre(p, max_len=MAX_LARGO_PALABRA_CLAVE_REPORTE)
            for p in palabras_clave_texto.split(",")
            if limpiar_texto_libre(p)
        ]
        if not palabras_clave:
            st.warning("Ingresa al menos una palabra clave.")
        elif len(palabras_clave) > database.MAX_PALABRAS_CLAVE_REPORTE:
            st.warning(f"Ingresa como máximo {database.MAX_PALABRAS_CLAVE_REPORTE} palabras clave.")
        elif not fecha_inicio or not fecha_fin:
            st.warning("Selecciona la fecha de inicio y la fecha de fin.")
        else:
            try:
                validar_rango_fechas(fecha_inicio, fecha_fin)
            except ValueError as exc:
                st.error(f"Datos inválidos: {exc}")
                return

            lote_id = opciones_lote.get(etiqueta_lote_sel) if etiqueta_lote_sel != SIN_LOTE_ESPECIFICO else None

            with st.spinner("Generando reporte..."):
                registros = database.get_contrataciones_para_reporte(
                    palabras_clave=palabras_clave,
                    fecha_inicio=fecha_inicio.isoformat(),
                    fecha_fin=fecha_fin.isoformat(),
                    lote_id=lote_id,
                )

                if not registros:
                    st.session_state.reporte_docx_bytes = None
                    st.warning(
                        "No se encontraron procesos para las palabras clave y el "
                        "rango de fechas indicados."
                    )
                else:
                    DIRECTORIO_SALIDAS_REPORTES.mkdir(parents=True, exist_ok=True)
                    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
                    nombre_archivo = f"reporte_{marca_tiempo}_{uuid.uuid4().hex[:8]}.docx"
                    ruta_salida = DIRECTORIO_SALIDAS_REPORTES / nombre_archivo
                    try:
                        generar_reporte(
                            df=pd.DataFrame(registros),
                            palabras_clave=palabras_clave,
                            fecha_inicio_global=fecha_inicio,
                            fecha_fin_global=fecha_fin,
                            ruta_salida=ruta_salida,
                            capturas_dir=capturas.CAPTURAS_DIR,
                            llenar_observaciones=llenar_observaciones,
                        )
                    except Exception as exc:  # noqa: BLE001 -- cualquier fallo de
                        # python-docx/imagenes se muestra como error controlado, sin
                        # dejar un .docx a medio escribir.
                        ruta_salida.unlink(missing_ok=True)
                        st.session_state.reporte_docx_bytes = None
                        logger.exception("Fallo la generacion del reporte: %s", type(exc).__name__)
                        st.error("Ocurrió un error al generar el reporte. Inténtalo de nuevo; si persiste, revisa el log.")
                    else:
                        st.session_state.reporte_docx_bytes = ruta_salida.read_bytes()
                        st.session_state.reporte_docx_nombre = nombre_archivo
                        st.success(f"Reporte generado correctamente en salidas/reportes/{nombre_archivo}")

    if st.session_state.reporte_docx_bytes:
        st.download_button(
            label=":material/download: Descargar Reporte_SERCOP.docx",
            data=st.session_state.reporte_docx_bytes,
            file_name="Reporte_SERCOP.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
