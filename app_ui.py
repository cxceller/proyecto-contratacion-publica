"""Interfaz Streamlit para visualizar procesos de contratacion publica.

Consume la API FastAPI (src/main.py) via services/sercop.py -- esta capa
de UI no llama a `requests` ni conoce URLs/endpoints directamente, ver
ese modulo. Arranque:

    uvicorn src.main:app --port 8000
    streamlit run app_ui.py --server.port 8501
"""
import html
import json
import re
import subprocess
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from scripts.dashboard_analitico import construir_datos_gantt_procesos, construir_datos_treemap_presupuesto
from scripts.formato_ec import (
    formatear_moneda_ec,
    formatear_numero_ec,
    formatear_porcentaje_ec,
    limpiar_texto_libre,
)
from services.sercop import generar_reporte, obtener_contrataciones, vaciar_base_datos
from src.logging_config import obtener_logger
from ui.componentes import boton_limpiar_filtros
from ui.especificaciones_tecnicas import (
    _dataframe_items_especificaciones_tecnicas_vacio,
    render_formularios_y_registro,
    render_treemap_items_especificaciones_tecnicas,
)
from ui.tema import (
    ALTURA_KPI_REM,
    COLOR_AXIS,
    COLOR_BARRA_DATO,
    COLOR_BARRA_DESTACADA,
    COLOR_ESTADO_AVISO,
    COLOR_ESTADO_CRITICO,
    COLOR_ESTADO_OK,
    COLOR_GRID,
    COLOR_LIENZO,
    COLOR_NEUTRO_BORDE,
    COLOR_NEUTRO_TEXTO_SUAVE,
    COLOR_PELIGRO,
    COLOR_SIDEBAR_ACENTO,
    COLOR_SIDEBAR_FONDO,
    COLOR_SIDEBAR_TEXTO,
    COLOR_SIDEBAR_TEXTO_ACTIVO,
    COLOR_TEXTO_EJE,
    PALETA_DATOS,
)

load_dotenv()

logger = obtener_logger(__name__)

# Largo maximo de la palabra clave del filtro de Procesos (el modelo del
# backend admite hasta 200, ver src/models.py).
MAX_LARGO_PALABRA_CLAVE = 100

NAV_ITEMS = [
    ("Dashboard", ":material/monitoring:"),
    ("Procesos", ":material/assignment:"),
    ("Reportes", ":material/description:"),
    ("Municipalidad de Guayaquil", ":material/location_city:"),
    ("Configuración", ":material/settings:"),
]

# Nombre de pagina para la vista dedicada de Importación SERCOP -- vive
# fuera de NAV_ITEMS (se renderiza aparte, debajo de un st.divider() propio
# en el sidebar, ver render_importacion_sercop_sidebar) pero participa del
# mismo mecanismo de enrutado session_state.pagina_activa + st.rerun() que
# usa render_navegacion_sidebar para el resto de items.
PAGINA_IMPORTACION_SERCOP = "Importación SERCOP"

# Carpeta donde _iniciar_importacion_sercop() redirige el stdout/stderr de
# scripts/scrape_portal.py: es la unica forma de que la UI sepa despues
# cuantos registros se importaron o si el proceso fallo, ya que corre
# desacoplado (subprocess.Popen) del hilo de Streamlit.
DIRECTORIO_LOGS_IMPORTACION_SERCOP = Path(__file__).resolve().parent / "logs"

# Umbral, en segundos, a partir del cual render_pagina_importacion_sercop
# avisa que la importacion esta tardando de mas -- NO mata el proceso
# automaticamente (el usuario puede seguir interactuando con el CAPTCHA en
# la ventana de Chromium), solo hace visible que algo puede haberse
# atascado. 10 minutos es holgado frente al caso normal (ESPERA_POR_DEFECTO_S
# = 90s de espera al captcha en scrape_portal.py + tiempo de paginar hasta
# MAX_PAGINAS=50 resultados).
TIMEOUT_AVISO_IMPORTACION_SERCOP_S = 600

# Cada cuantos segundos la vista de Importación SERCOP se refresca sola
# (time.sleep + st.rerun()) mientras el proceso sigue corriendo, para no
# depender de que el usuario haga clic manualmente en "Actualizar estado".
INTERVALO_AUTOREFRESCO_IMPORTACION_SERCOP_S = 3

# Coincide con la linea final que imprime scripts/scrape_portal.py al
# terminar sin errores (ver la funcion main() de ese script) -- SIN tildes,
# tal como la imprime el script real.
PATRON_RESUMEN_IMPORTACION_SERCOP = re.compile(
    r"Busqueda completa: (\d+) registro\(s\) insertado\(s\) en (\d+) pagina\(s\) de resultados, "
    r"(\d+) omitido\(s\) por error de validacion"
)

# Coincide con la linea final que imprime scripts/actualizar_montos_adjudicados.py
# al terminar (ver ese script) -- SIN tildes, tal como la imprime el script real.
PATRON_RESUMEN_ACTUALIZAR_MONTOS = re.compile(
    r"Completo en \d+s: (\d+) actualizado\(s\), (\d+) sin adjudicar todavia, (\d+) con error"
)

# Nombre exacto de la Entidad Contratante para la seccion "Municipalidad
# de Guayaquil" (verificado contra la base real: un unico valor de
# escritura, "Municipalidad de Guayaquil", 5 registros -- ver
# filtrar_por_entidad, que igual normaliza tildes/mayusculas por si
# aparecen variantes de escritura en datos futuros).
ENTIDAD_MUNICIPALIDAD_GUAYAQUIL = "Municipalidad de Guayaquil"

# Escudo institucional oficial para el item de menu "Municipalidad de
# Guayaquil", en vez de un emoji. Recortado del logo apaisado original
# (600x210px, "Muy Ilustre Municipalidad de Guayaquil") para quedarse
# solo con el emblema (circulo + estrella + corona de laurel, 196x200px):
# el wordmark de texto del logo completo, a tamaño de icono de menu, no
# se leia (texto navy sobre el fondo navy del sidebar, y demasiado chico
# de por si) -- el nombre ya esta como texto en el boton de al lado.
# st.image solo permite fijar el ancho (la altura se escala sola
# preservando el aspecto), asi que el ancho se calcula a partir de la
# altura deseada y la relacion de aspecto real del recorte.
LOGO_MUNICIPALIDAD_PATH = Path(__file__).resolve().parent / "assets" / "mimg_escudo.png"
LOGO_MUNICIPALIDAD_ALTO_PX = 30
LOGO_MUNICIPALIDAD_ANCHO_PX = round(LOGO_MUNICIPALIDAD_ALTO_PX * 196 / 200)

# Estados tal como los expone el portal de Compras Publicas (algunos truncados).
ESTADOS = [
    "Cancelado",
    "Finalizada",
    "Ejecución de",
    "Desierta",
    "En Recepción",
    "Terminado U",
    "Adjudicado -",
    "Adjudicada",
    "Suspendido",
    "Por Adjudicar",
]

# Subconjunto de ESTADOS visible por defecto en render_contadores (revelacion
# progresiva: 4 tarjetas en vez de las ~12 de antes) -- las 3 categorias mas
# consultadas de un vistazo, el resto queda dentro de un expander.
ESTADOS_DESTACADOS = ["Adjudicada", "Ejecución de", "Desierta"]

# Nombre completo (no truncado) de cada categoria de ESTADOS, para mostrar
# en las tarjetas de render_contadores en vez del prefijo truncado
# ("Ejecución de", "Terminado U", "Adjudicado -"). Confirmado contra los
# valores reales de la columna `estado` en la base de datos.
NOMBRES_ESTADO_COMPLETOS = {
    "Cancelado": "Cancelado",
    "Finalizada": "Finalizada",
    "Ejecución de": "Ejecución de Contrato",
    "Desierta": "Desierta",
    "En Recepción": "En Recepción",
    "Terminado U": "Terminado Unilateralmente",
    "Adjudicado -": "Adjudicado - Registro de Contratos",
    "Adjudicada": "Adjudicada",
    "Suspendido": "Suspendido",
    "Por Adjudicar": "Por Adjudicar",
}

# Icono (nombre de Material Symbols, mismo set que ya usa toda la app via
# los shortcodes :material/xxx: del sidebar -- ver _span_icono_material) y
# color semantico por categoria de estado, para las tarjetas KPI de
# render_contadores. Clave = misma clave truncada de ESTADOS (no el nombre
# completo de NOMBRES_ESTADO_COMPLETOS), para poder buscar en el mismo
# punto del loop antes de mapear al nombre a mostrar. "Otros" tiene entrada
# propia (no es parte de ESTADOS, se agrega aparte en render_contadores);
# "Total" NO tiene icono a proposito (es el agregado, no un estado
# individual). Solo 3 colores posibles -- COLOR_ESTADO_OK/_AVISO/_CRITICO --
# en vez de un tono distinto por estado: el color pasa a comunicar
# unicamente severidad (ok/aviso/critico), la categoria especifica la
# distingue el icono + la etiqueta de texto (nunca el color solo). Los
# rojos de aca son el mismo tono que COLOR_PELIGRO (critico) a proposito
# -- misma severidad semantica, ya no tonos Tailwind sueltos.
ICONOS_ESTADO = {
    "Cancelado": ("cancel", COLOR_ESTADO_CRITICO),
    "Finalizada": ("check_circle", COLOR_ESTADO_OK),
    "Ejecución de": ("engineering", COLOR_ESTADO_OK),
    "Desierta": ("block", COLOR_ESTADO_CRITICO),
    "En Recepción": ("inbox", COLOR_ESTADO_AVISO),
    "Terminado U": ("report", COLOR_ESTADO_CRITICO),
    "Adjudicado -": ("task_alt", COLOR_ESTADO_OK),
    "Adjudicada": ("task_alt", COLOR_ESTADO_OK),
    "Suspendido": ("pause_circle", COLOR_ESTADO_AVISO),
    "Por Adjudicar": ("hourglass_top", COLOR_ESTADO_AVISO),
    "Otros": ("more_horiz", COLOR_NEUTRO_TEXTO_SUAVE),
}

COLUMNAS_TABLA = {
    "codigo": "Código",
    "entidad_contratante": "Entidad Contratante",
    "objeto_proceso": "Objeto del Proceso",
    "estado": "Estado del Proceso",
    # Solo se completa para procesos "Desierta" (ver
    # scripts/explicar_estado_desierta.py) -- queda vacia para el resto,
    # sin necesidad de ningun filtro especial aca: simplemente no hay dato
    # que mostrar. Restringida a la vista de Municipalidad de Guayaquil,
    # igual que "monto_adjudicado" -- ver el gate de mostrar_monto_adjudicado
    # en render_tabla_con_color.
    "explicacion_estado": "Explicación (Desierta)",
    "provincia_canton": "Provincia/Cantón",
    "presupuesto_referencial": "Presupuesto Referencial (sin IVA)",
    "monto_adjudicado": "Monto Adjudicado",
    "fecha_publicacion": "Fecha de Publicación",
    "palabra_clave": "Palabra Clave",
    "url": "URL",
}

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# Opciones del selector "Comparar por" de render_grafico_comparativo: cada
# etiqueta visible mapea a la columna real de df_filtrado por la que agrupar.
DIMENSIONES_COMPARATIVAS = {
    "Provincia/Cantón": "provincia_canton",
    "Tipo de Compra": "tipo_compra",
    "Estado del Proceso": "estado",
}
# Opciones del selector "Métrica" de render_grafico_comparativo: agregacion
# a aplicar (columna + funcion) y el formateador Ecuador correspondiente.
METRICAS_COMPARATIVAS = {
    "Número de procesos": {
        "columna": "id", "agg": "count",
        "formato": formatear_numero_ec, "es_moneda": False,
    },
    "Presupuesto Referencial (total)": {
        "columna": "presupuesto_referencial", "agg": "sum",
        "formato": formatear_moneda_ec, "es_moneda": True,
    },
}

# Capital y coordenadas (lat, lon) de cada una de las 24 provincias del
# Ecuador, para ubicar el mapa de burbujas del Dashboard Analitico. Clave
# normalizada (mayusculas, sin tildes) para no depender de como venga
# escrito "provincia_canton" en el dato crudo del portal (ver
# `extraer_provincia`).
CAPITALES_PROVINCIA = {
    "AZUAY": {"nombre": "Azuay", "capital": "Cuenca", "lat": -2.9001, "lon": -79.0059},
    "BOLIVAR": {"nombre": "Bolívar", "capital": "Guaranda", "lat": -1.5905, "lon": -79.0011},
    "CANAR": {"nombre": "Cañar", "capital": "Azogues", "lat": -2.7397, "lon": -78.8483},
    "CARCHI": {"nombre": "Carchi", "capital": "Tulcán", "lat": 0.8117, "lon": -77.7172},
    "CHIMBORAZO": {"nombre": "Chimborazo", "capital": "Riobamba", "lat": -1.6636, "lon": -78.6546},
    "COTOPAXI": {"nombre": "Cotopaxi", "capital": "Latacunga", "lat": -0.9345, "lon": -78.6157},
    "EL ORO": {"nombre": "El Oro", "capital": "Machala", "lat": -3.2581, "lon": -79.9553},
    "ESMERALDAS": {"nombre": "Esmeraldas", "capital": "Esmeraldas", "lat": 0.9592, "lon": -79.6564},
    "GALAPAGOS": {
        "nombre": "Galápagos", "capital": "Pto. Baquerizo Moreno", "lat": -0.9014, "lon": -89.6089,
    },
    "GUAYAS": {"nombre": "Guayas", "capital": "Guayaquil", "lat": -2.1962, "lon": -79.8862},
    "IMBABURA": {"nombre": "Imbabura", "capital": "Ibarra", "lat": 0.3517, "lon": -78.1223},
    "LOJA": {"nombre": "Loja", "capital": "Loja", "lat": -3.9931, "lon": -79.2042},
    "LOS RIOS": {"nombre": "Los Ríos", "capital": "Babahoyo", "lat": -1.8021, "lon": -79.5346},
    "MANABI": {"nombre": "Manabí", "capital": "Portoviejo", "lat": -1.0546, "lon": -80.4545},
    "MORONA SANTIAGO": {"nombre": "Morona Santiago", "capital": "Macas", "lat": -2.3072, "lon": -78.1136},
    "NAPO": {"nombre": "Napo", "capital": "Tena", "lat": -0.9948, "lon": -77.8134},
    "ORELLANA": {
        "nombre": "Orellana", "capital": "Pto. Fco. de Orellana", "lat": -0.4653, "lon": -76.9836,
    },
    "PASTAZA": {"nombre": "Pastaza", "capital": "Puyo", "lat": -1.4924, "lon": -78.0022},
    "PICHINCHA": {"nombre": "Pichincha", "capital": "Quito", "lat": -0.1807, "lon": -78.4678},
    "SANTA ELENA": {"nombre": "Santa Elena", "capital": "Santa Elena", "lat": -2.2270, "lon": -80.8592},
    "SANTO DOMINGO DE LOS TSACHILAS": {
        "nombre": "Sto. Domingo de los Tsáchilas", "capital": "Santo Domingo",
        "lat": -0.2542, "lon": -79.1719,
    },
    "SUCUMBIOS": {"nombre": "Sucumbíos", "capital": "Nueva Loja", "lat": 0.0842, "lon": -76.8897},
    "TUNGURAHUA": {"nombre": "Tungurahua", "capital": "Ambato", "lat": -1.2543, "lon": -78.6229},
    "ZAMORA CHINCHIPE": {"nombre": "Zamora Chinchipe", "capital": "Zamora", "lat": -4.0669, "lon": -78.9558},
}

# Limites provinciales (ADM1) del Ecuador, para el mapa coropletico.
# Fuente: "Ecuador - Subnational Administrative Boundaries", Humanitarian
# Data Exchange (HDX) -- https://data.humdata.org/dataset/cod-ab-ecu --
# originado en el INEC. Licencia CC BY-IGO (uso libre, incluido
# comercial, con atribucion -- ver el st.caption que acompaña al mapa).
# Geometria simplificada (tolerance=0.01) para que cargue liviano en el
# navegador; cada feature ya trae la propiedad "provincia_clave"
# normalizada (mismo formato que las claves de CAPITALES_PROVINCIA) para
# poder cruzar contra los datos sin depender de tildes/mayusculas.
GEOJSON_PROVINCIAS_PATH = Path(__file__).resolve().parent / "data" / "provincias_ecuador.geojson"


@st.cache_data(ttl=86400, show_spinner=False)
def cargar_geojson_provincias() -> dict:
    """Archivo geografico estatico (limites provinciales, no cambia en
    tiempo de ejecucion): ttl=86400 igual que _cargar_catalogo_cpc.
    show_spinner=False porque se llama dentro de la pestaña "Ver detalle
    por provincia" del dashboard, a mitad de pagina ya renderizada."""
    with open(GEOJSON_PROVINCIAS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _normalizar_texto_provincia(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(texto or ""))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return sin_acentos.strip().upper()


def extraer_provincia(provincia_canton: str) -> str:
    """'GUAYAS / GUAYAQUIL' -> 'GUAYAS' (clave normalizada, sin tildes,
    para buscar en CAPITALES_PROVINCIA)."""
    texto = str(provincia_canton or "").split("/")[0]
    return _normalizar_texto_provincia(texto)


# Indicador de estado como emoji + texto (en vez de pintar el fondo de toda
# la celda, que saturaba visualmente la tabla). Claves normalizadas
# (minusculas, espacios colapsados) para el lookup; el texto mostrado usa la
# grafia canonica de esta lista, no la del dato crudo.
EMOJI_ESTADO = {
    "desierta": ("🔴", "Desierta"),
    "ejecución de contrato": ("🟢", "Ejecución de Contrato"),
    "cancelado": ("⭕", "Cancelado"),
    "suspendido": ("🟠", "Suspendido"),
    "adjudicado - registro de contratos": ("🟩", "Adjudicado - Registro de Contratos"),
    # Doble emoji (🟩🟩/✅✅ vs. el 🟩 simple de "Adjudicado - Registro de
    # Contratos" y el ✅ simple de "En Recepción" mas abajo) a proposito --
    # para que "Adjudicada" y "Finalizada" se distingan de esos dos estados
    # a simple vista en la tabla, no por error de copiar/pegar.
    "adjudicada": ("🟩🟩", "Adjudicada"),
    "finalizada": ("✅✅", "Finalizada"),
    "por adjudicar": ("🍏", "Por Adjudicar"),
    "preguntas, respuestas y aclaraciones": ("🟡", "Preguntas, Respuestas y Aclaraciones"),
    "en recepción": ("✅", "En Recepción"),
    "entrega de propuesta": ("🟨", "Entrega de Propuesta"),
}


def estado_con_emoji(estado: str) -> str:
    """Antepone un emoji indicador al estado. La clave de busqueda se
    normaliza (espacios extra colapsados, sin extremos, case-insensitive)
    para tolerar variaciones del dato crudo del portal; un estado que no
    esta en `EMOJI_ESTADO` se muestra tal cual, sin emoji."""
    texto = str(estado or "").strip()
    if not texto:
        return texto
    clave = re.sub(r"\s+", " ", texto).casefold()
    coincidencia = EMOJI_ESTADO.get(clave)
    if coincidencia is None:
        return texto
    emoji, texto_canonico = coincidencia
    return f"{emoji} {texto_canonico}"


def _formatear_porcentaje_ahorro(valor) -> str:
    """"% de Ahorro" (ver render_tabla_con_color) como texto: "🟢 51.58 %"
    si el ahorro es positivo o cero, "🔴 -12.30 %" si es negativo (el
    Monto Adjudicado superó al Presupuesto Referencial, caso atípico que
    se muestra tal cual, sin forzarlo a positivo). Cadena vacía si `valor`
    es NaN/None (Monto Adjudicado o Presupuesto Referencial vacíos, o
    Presupuesto Referencial en 0 -- ver render_tabla_con_color) -- nunca
    "0.00 %" ni un error."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    emoji = "🟢" if valor >= 0 else "🔴"
    return f"{emoji} {valor:.2f} %"


def extraer_tipo_compra(objeto_proceso: str) -> str:
    """Infiere un 'tipo de compra' a partir de la primera palabra del Objeto
    del Proceso (en el portal suele ser un verbo/sustantivo de accion, p.ej.
    "Adquisición de...", "Contratación de...", "Construcción de..."). No hay
    un campo explicito de tipo de compra en el esquema, asi que es una
    aproximacion heuristica, no una categoria oficial del portal."""
    texto = str(objeto_proceso or "").strip()
    if not texto:
        return "Otros"
    primera_palabra = re.split(r"\s+", texto)[0]
    primera_palabra = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", primera_palabra)
    if not primera_palabra:
        return "Otros"
    # Normaliza tildes/mayusculas ANTES de capitalizar (misma logica que
    # _normalizar_texto_provincia): sin esto, "Repotenciacion" y
    # "Repotenciación" quedaban como dos categorias distintas en el
    # resumen "Por Tipo de Compra" del dashboard.
    return _normalizar_texto_provincia(primera_palabra).capitalize()


@st.cache_data(show_spinner=False)
def preparar_dataframe(registros: list[dict]) -> pd.DataFrame:
    """Construye el DataFrame base del dashboard analitico: parsea fecha de
    publicacion en año/mes y deriva el 'tipo de compra' del objeto.

    Cacheada (@st.cache_data): funcion pura sobre `registros` (misma
    lista -> mismo DataFrame), pero re-ejecuta el parseo de fechas y el
    .apply() de extraer_tipo_compra/extraer_provincia sobre TODOS los
    registros en cada rerun del dashboard (ej. al cambiar el filtro de
    Año/Mes/Provincia, que no cambia `registros` en si). show_spinner=False
    porque se llama a mitad de render_pagina_dashboard, despues de los
    contadores ya visibles."""
    df = pd.DataFrame(registros)
    if df.empty:
        return df

    df["fecha_publicacion"] = pd.to_datetime(df.get("fecha_publicacion"), errors="coerce")
    df["anio"] = df["fecha_publicacion"].dt.year
    df["mes_num"] = df["fecha_publicacion"].dt.month
    df["anio_mes"] = df["fecha_publicacion"].dt.strftime("%Y-%m")
    df["provincia_canton"] = df["provincia_canton"].fillna("Sin especificar")
    df["tipo_compra"] = df["objeto_proceso"].apply(extraer_tipo_compra)
    df["provincia_clave"] = df["provincia_canton"].apply(extraer_provincia)
    return df


CLAVES_FILTRO_DASHBOARD = ["dashboard_anio", "dashboard_mes", "dashboard_provincia", "dashboard_entidad"]


def render_filtros_dashboard(df: pd.DataFrame, key_prefix: str = "") -> pd.DataFrame:
    """Fila de filtros superiores (Año, Mes, Provincia/Cantón, Entidad
    Contratante) que acota todo lo que se muestra debajo: graficos, tablas
    y KPIs comparten el mismo dataframe filtrado, para que las cifras
    siempre coincidan. Los widgets tienen key propia para que "Limpiar
    filtros" pueda resetearlos de verdad (no solo re-consultar datos), ver
    CLAVES_FILTRO_DASHBOARD.

    El filtro de Entidad Contratante (P0-2 del plan de mejoras) reemplaza
    lo que antes era un item de menu aparte ("Dashboard Municipio de
    Guayaquil", el mismo render_dashboard con los registros pre-filtrados a
    esa entidad): ahora es un filtro mas de esta misma fila, sin duplicar
    pagina ni logica -- "Municipalidad de Guayaquil" en este selectbox logra
    la misma vista que antes tenia su propio item de navegacion.

    `key_prefix` distingue las keys de session_state cuando esta misma
    funcion se llama mas de una vez en la app con datos distintos -- hoy
    solo la usa render_pagina_dashboard, pero el prefijo se mantiene por si
    algun otro caller la reusa mas adelante (evita que dos instancias
    compartan keys y una seleccion pise a la otra)."""
    col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1.5, 1])

    if df.empty:
        col1.selectbox("Año", ["(Todos)"], disabled=True)
        col2.selectbox("Mes", ["(Todos)"], disabled=True)
        col3.multiselect("Provincia/Cantón", [], disabled=True, placeholder="Sin datos disponibles")
        col4.selectbox("Entidad Contratante", ["(Todas)"], disabled=True)
        return df

    anios_disponibles = sorted(df["anio"].dropna().unique().astype(int), reverse=True)
    anio_sel = col1.selectbox(
        "Año", ["(Todos)"] + [str(a) for a in anios_disponibles], key=f"{key_prefix}dashboard_anio"
    )

    meses_disponibles = sorted(df["mes_num"].dropna().unique().astype(int))
    opciones_mes = ["(Todos)"] + [MESES_ES[m] for m in meses_disponibles]
    mes_sel = col2.selectbox("Mes", opciones_mes, key=f"{key_prefix}dashboard_mes")

    provincias_disponibles = sorted(df["provincia_canton"].dropna().unique())
    provincias_sel = col3.multiselect(
        "Provincia/Cantón",
        provincias_disponibles,
        key=f"{key_prefix}dashboard_provincia",
        placeholder="Selecciona una o más provincias/cantones",
    )

    entidades_disponibles = sorted(df["entidad_contratante"].dropna().unique())
    entidad_sel = col4.selectbox(
        "Entidad Contratante", ["(Todas)"] + entidades_disponibles, key=f"{key_prefix}dashboard_entidad"
    )

    with col5:
        st.write("")  # alinea verticalmente el boton con los selectbox de arriba
        boton_limpiar_filtros(
            [f"{key_prefix}{clave}" for clave in CLAVES_FILTRO_DASHBOARD],
            key=f"{key_prefix}dashboard_limpiar_filtros",
        )

    df_filtrado = df
    if anio_sel != "(Todos)":
        df_filtrado = df_filtrado[df_filtrado["anio"] == int(anio_sel)]
    if mes_sel != "(Todos)":
        mes_num = next(k for k, v in MESES_ES.items() if v == mes_sel)
        df_filtrado = df_filtrado[df_filtrado["mes_num"] == mes_num]
    if provincias_sel:
        df_filtrado = df_filtrado[df_filtrado["provincia_canton"].isin(provincias_sel)]
    if entidad_sel != "(Todas)":
        df_filtrado = df_filtrado[
            df_filtrado["entidad_contratante"].map(_normalizar_texto_provincia)
            == _normalizar_texto_provincia(entidad_sel)
        ]

    return df_filtrado


def _aplicar_estilo_base(fig: go.Figure, altura: int = 380) -> None:
    """Fondo estructural tipo lienzo de papel: SIEMPRE blanco puro,
    independientemente de si Streamlit esta en modo claro u oscuro (un fondo
    transparente heredaria el fondo oscuro del tema y volveria illegible el
    texto negro de los ejes). Es el lienzo neutro sobre el que resalta la
    paleta viva de los datos."""
    fig.update_layout(
        plot_bgcolor=COLOR_LIENZO,
        paper_bgcolor=COLOR_LIENZO,
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=COLOR_TEXTO_EJE),
        margin=dict(l=10, r=10, t=20, b=10),
        height=altura,
        showlegend=False,
        hoverlabel=dict(bgcolor=COLOR_LIENZO, font_size=13, font_color=COLOR_TEXTO_EJE),
        bargap=0.35,
        # Formato numerico de Ecuador (coma decimal, punto de miles) para
        # TODOS los numeros que Plotly renderiza con specs tipo d3-format
        # (tickformat de ejes, ":,.2f" embebido en hovertemplate, etc.):
        # "separators" es el mecanismo nativo de Plotly para esto -- primer
        # caracter es el separador decimal, segundo el de miles -- asi no
        # hace falta reescribir cada hovertemplate/tickformat a mano.
        separators=",.",
    )


def _span_icono_material(nombre_icono: str, color: str, tamano_rem: float = 1.05) -> str:
    """Renderiza un icono de Material Symbols como ligature (el texto del
    nombre del icono se sustituye por el glifo cuando se le aplica la
    fuente correcta), el mismo mecanismo estandar de Google que usa
    Streamlit para sus propios shortcodes :material/xxx: del sidebar --
    pero esos shortcodes solo funcionan dentro de widgets de texto de
    Streamlit, no dentro de HTML crudo como el de _tarjeta_kpi_html
    (st.markdown(unsafe_allow_html=True) inserta el string tal cual, sin
    pasar por el parser de shortcodes de Streamlit). "Material Symbols
    Rounded" ya esta declarada como @font-face globalmente por el propio
    CSS de Streamlit (se usa en cada icono del sidebar), asi que no hace
    falta cargar ninguna fuente ni hoja de estilos externa aca -- solo
    aplicar el mismo font-family + font-feature-settings:'liga' que activa
    la sustitucion ligature en el navegador.

    `translate="no"` + `class="notranslate"` son necesarios: verificado en
    vivo con el traductor de Chrome activo en la pagina (agrega
    class="translated-ltr" al <html>, algo que le puede pasar a cualquier
    usuario con traduccion automatica activada) -- SIN estos dos atributos,
    Chrome traduce el texto crudo del nombre del icono ("cancel" ->
    "CANCELAR", "engineering" -> "INGENIERÍA", etc.) ANTES de que la fuente
    llegue a sustituirlo por el glifo, mostrando la palabra traducida en
    vez del icono. Se confirmo que hasta los propios iconos :material/xxx:
    del sidebar de Streamlit sufren el mismo problema (no tienen esta
    proteccion) -- no es algo que se pueda arreglar ahi (es codigo de
    Streamlit, no de este archivo), pero si se puede evitar aca."""
    return (
        f'<span translate="no" class="notranslate" '
        f'style="font-family:\'Material Symbols Rounded\'; font-weight:normal; '
        f'font-style:normal; font-size:{tamano_rem}rem; line-height:1; letter-spacing:normal; '
        f'text-transform:none; display:inline-block; white-space:nowrap; word-wrap:normal; '
        f'direction:ltr; -webkit-font-feature-settings:\'liga\'; -webkit-font-smoothing:antialiased; '
        f'color:{color}; vertical-align:middle;">{nombre_icono}</span>'
    )


def _tarjeta_kpi_html(
    etiqueta: str,
    valor: str,
    ayuda: str | None = None,
    icono: str | None = None,
    color_icono: str | None = None,
    insignia: str | None = None,
) -> str:
    """Tarjeta KPI en HTML puro (no st.metric): mismo fondo/tipografia/
    bordes en toda la app (Dashboard, Procesos y Municipio de Guayaquil,
    vía render_kpi_card mas abajo), en vez de la mezcla anterior de
    st.metric (texto plano) en unas paginas y esta tarjeta HTML en otras.
    El fondo se fuerza por inline-style con COLOR_LIENZO, igual que
    plot_bgcolor/paper_bgcolor de los graficos, para que ambos recuadros
    hagan juego sin depender del tema claro/oscuro de Streamlit.

    `icono`/`color_icono` son opcionales (la mayoria de las tarjetas KPI --
    Procesos, Presupuesto Total, Valor Adjudicado -- no representan un
    estado y no llevan icono): cuando se indican, se agregan ANTES de la
    etiqueta de texto (nunca en su reemplazo, para no depender solo del
    color/icono para distinguir estados -- ver render_contadores, el unico
    caller que los pasa hoy).

    `insignia` es un dato secundario opcional (hoy, el % de participacion
    de render_contadores) que se muestra como una pildora pequeña y
    discreta DEBAJO del valor principal -- nunca junto al numero grande,
    para no competir con el, y en gris neutro (no en el color semantico
    del icono/estado) para no sumar un significado nuevo de color.

    Todo el HTML se arma en UNA sola linea (sin saltos de linea/lineas en
    blanco internas): st.markdown(unsafe_allow_html=True) usa un parser
    de Markdown, y una linea en blanco A MITAD del bloque (ej. insertando
    aca un f-string multilinea con su propio salto de linea inicial,
    como tenia antes la insignia) corta el bloque HTML en dos -- todo lo
    que queda despues de esa linea en blanco deja de reconocerse como
    HTML y se muestra como texto plano crudo con las etiquetas visibles."""
    atributo_titulo = f' title="{html.escape(ayuda)}"' if ayuda else ""
    icono_html = _span_icono_material(icono, color_icono) + " " if icono else ""
    insignia_html = (
        f'<div style="margin-top:auto;padding-top:0.4rem;">'
        f'<span style="display:inline-block;padding:0.15rem 0.6rem;'
        f"border-radius:999px;background-color:{COLOR_NEUTRO_BORDE};"
        f"color:{COLOR_NEUTRO_TEXTO_SUAVE};font-size:0.75rem;font-weight:600;"
        f'line-height:1.4;">{html.escape(insignia)}</span></div>'
        if insignia
        else ""
    )
    return (
        f'<div{atributo_titulo} style="background-color:{COLOR_LIENZO};'
        f"border:1px solid {COLOR_NEUTRO_BORDE};border-radius:8px;box-sizing:border-box;"
        f"padding:1.25rem 1.5rem;margin-bottom:0.5rem;"
        f'display:flex;flex-direction:column;min-height:{ALTURA_KPI_REM}rem;">'
        f'<div style="font-size:0.875rem;color:{COLOR_NEUTRO_TEXTO_SUAVE};'
        f'min-height:2.5rem;">{icono_html}{etiqueta}</div>'
        f'<div style="font-size:2rem;font-weight:600;color:{COLOR_TEXTO_EJE};line-height:1.3;">{valor}</div>'
        f"{insignia_html}"
        f"</div>"
    )


def render_kpi_card(
    columna,
    etiqueta: str,
    valor: str,
    ayuda: str | None = None,
    icono: str | None = None,
    color_icono: str | None = None,
    insignia: str | None = None,
) -> None:
    """Tarjeta KPI reutilizable: mismo componente para Dashboard
    (render_kpis_dashboard), Procesos y Municipio de Guayaquil
    (render_contadores, render_metricas_resumen), en vez de que cada
    pagina eligiera su propio estilo (st.metric vs. tarjeta HTML).
    `icono`/`color_icono`/`insignia` son opcionales -- ver
    _tarjeta_kpi_html."""
    columna.markdown(
        _tarjeta_kpi_html(etiqueta, valor, ayuda, icono=icono, color_icono=color_icono, insignia=insignia),
        unsafe_allow_html=True,
    )


def _inyectar_estilos_kpi_tendencia() -> None:
    """CSS para que render_kpi_card_tendencia (etiqueta+valor+badge en HTML
    + sparkline via st.plotly_chart) tenga el mismo fondo/borde/padding que
    _tarjeta_kpi_html, aunque ya no es un unico <div> HTML -- el sparkline
    necesita su propio elemento Streamlit, asi que la tarjeta pasa a ser un
    st.container(key=...) real que envuelve markdown + plotly_chart. Mismo
    patron ".st-key-<key>" que el resto de la app (ver
    _inyectar_estilos_especificaciones_tecnicas_cards), pero por SUBCADENA
    ([class*=...]): cada tarjeta tiene su propia key (una por etiqueta, ver
    render_kpi_card_tendencia), asi que una key fija no alcanzaria a todas.
    Se llama en cada render (idempotente, mismo criterio que
    _inyectar_estilos_sidebar): reinyectar el mismo <style> no tiene efecto
    visible.

    `min-height: {ALTURA_KPI_REM}rem` (P1-6 del plan de mejoras, mismo
    valor que _tarjeta_kpi_html/_inyectar_estilos_gauge_ahorro): antes esta
    tarjeta no tenia altura minima propia, crecia con el contenido + el
    sparkline (~11rem) y quedaba desalineada frente a las tarjetas simples
    (8.5rem fijo) en la misma fila. `overflow: hidden` + `display:flex`
    con el sparkline en `margin-top:auto` evita ademas que el sparkline
    (fill="tozeroy", pegado al padding inferior) cruce el borde de la
    tarjeta -- confirmado en vivo antes de este cambio.

    Se probo tambien `height: 100%` para que la tarjeta se estirara exacto
    a lo que mida la columna de Streamlit -- NO funciona: entre esta
    tarjeta y `[data-testid="stColumn"]` (el unico nivel que Streamlit
    estira via align-items:stretch) hay varios wrappers internos
    (stVerticalBlockBorderWrapper, stVerticalBlock, etc.) sin altura
    propia, asi que el 100% se resuelve contra un padre en "auto" y no
    tiene efecto (confirmado midiendo con getBoundingClientRect en vivo).
    Forzarlo con !important en esos selectores genericos de Streamlit
    afectaria TODA la app (cualquier st.container/st.columns), no solo
    estas tarjetas -- demasiado riesgo para un ajuste cosmetico. Por eso
    la alineacion depende solo de ALTURA_KPI_REM: un piso lo bastante alto
    para que el contenido real de las 3 tarjetas (simple/sparkline/gauge)
    quede exactamente en ese piso, sin pelear la cascada de Streamlit."""
    st.markdown(
        f"""
        <style>
        div[class*="st-key-kpi_tendencia_"] {{
            background-color: {COLOR_LIENZO};
            border: 1px solid {COLOR_NEUTRO_BORDE};
            border-radius: 8px;
            padding: 1.25rem 1.5rem 0.75rem 1.5rem;
            margin-bottom: 0.5rem;
            min-height: {ALTURA_KPI_REM}rem;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}
        div[class*="st-key-kpi_tendencia_"] .js-plotly-plot {{
            margin-top: auto;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _figura_sparkline(serie: list[float]) -> go.Figure:
    """Mini-grafico de linea (sin ejes/grid/leyenda/hover) para el
    sparkline de render_kpi_card_tendencia -- misma paleta que el resto de
    graficos (COLOR_SIDEBAR_ACENTO = "#2a78d6"), pero SIN
    _aplicar_estilo_base: esa funcion fija una altura de 380px pensada
    para graficos normales, no para un sparkline de ~48px dentro de una
    tarjeta KPI."""
    fig = go.Figure(
        go.Scatter(
            y=serie,
            mode="lines",
            line=dict(color=COLOR_SIDEBAR_ACENTO, width=2, shape="spline", smoothing=0.6),
            fill="tozeroy",
            fillcolor="rgba(42, 120, 214, 0.12)",
            hoverinfo="skip",
        )
    )
    fig.update_xaxes(visible=False, showgrid=False, fixedrange=True)
    fig.update_yaxes(visible=False, showgrid=False, fixedrange=True)
    fig.update_layout(
        height=48,
        # b=6 (no 2): colchon extra para que el area rellena
        # (fill="tozeroy") no quede pegada al borde inferior real de la
        # tarjeta -- ver _inyectar_estilos_kpi_tendencia (P1-6).
        margin=dict(l=0, r=0, t=2, b=6),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def render_kpi_card_tendencia(
    columna,
    etiqueta: str,
    valor: str,
    serie: list[float] | None = None,
    variacion_pct: float | None = None,
    ayuda: str | None = None,
    sentido: str = "neutro",
) -> None:
    """Tarjeta KPI con mini-sparkline (tendencia mensual) y badge de
    variación porcentual vs. el periodo anterior, para los KPIs monetarios
    (Presupuesto Total, Valor Adjudicado/Presupuesto en Contratación) de
    Dashboard, Procesos y Municipio de Guayaquil -- ver
    render_kpis_dashboard/render_metricas_resumen.

    `sentido` (P1-4 del plan de mejoras) decide el color del badge:
    - "neutro" (default): gris (COLOR_NEUTRO_TEXTO_SUAVE) con la flecha
      ↑/↓ segun el signo, sin verde/rojo -- para metricas donde subir o
      bajar NO es intrinsecamente bueno/malo, solo describe cuanta
      actividad hubo el periodo (hoy, los 3 unicos callers: Presupuesto
      Total, Presupuesto en Contratación, Valor Adjudicado Total -- que
      un mes tenga menos presupuesto publicado no es "malo", es solo
      menos actividad ese periodo).
    - "positivo_sube": verde con "↑" si `variacion_pct` es >= 0, rojo con
      "↓" si es negativo -- reservado para metricas donde la direccion SI
      implica bueno/malo (ej. una futura tendencia de "% de Ahorro", hoy
      mostrado aparte como gauge sin badge, ver _figura_gauge_ahorro). En
      ambos modos, el icono (↑/↓) siempre acompaña al color -- nunca
      color solo.

    Si `serie` tiene menos de 2 puntos (sin historia suficiente para
    graficar una tendencia) se omite el sparkline; si `variacion_pct` es
    None (sin base para calcularlo, ej. periodo anterior en 0) se omite el
    badge -- en ambos casos la tarjeta degrada a mostrar solo etiqueta +
    valor, nunca un grafico vacio ni un badge sin sentido.

    `_inyectar_estilos_kpi_tendencia()` se llama ANTES de `with columna:`
    (mismo patron que `_inyectar_estilos_gauge_ahorro()`/col4 en
    render_pagina_municipalidad_guayaquil), no dentro -- un `st.markdown`
    dentro de `with columna:` reserva su propio elemento (con el gap
    vertical por defecto entre elementos de Streamlit) DENTRO de esa
    columna especifica, empujando el resto del contenido ~16px hacia
    abajo. Eso rompia la alineacion con las tarjetas simples de la misma
    fila (que no tienen ese elemento extra) aunque ambas midieran la
    misma altura -- confirmado midiendo `top`/`bottom` con
    getBoundingClientRect en vivo: mismo `height`, `top` distinto."""
    _inyectar_estilos_kpi_tendencia()
    with columna:
        clave = "kpi_tendencia_" + re.sub(r"[^a-z0-9]+", "_", etiqueta.lower()).strip("_")
        with st.container(key=clave):
            atributo_titulo = f' title="{html.escape(ayuda)}"' if ayuda else ""
            badge_html = ""
            if variacion_pct is not None:
                positivo = variacion_pct >= 0
                flecha = "↑" if positivo else "↓"
                if sentido == "neutro":
                    color = COLOR_NEUTRO_TEXTO_SUAVE
                else:
                    color = COLOR_ESTADO_OK if positivo else COLOR_ESTADO_CRITICO
                badge_html = (
                    f'<span style="display:inline-block;padding:0.15rem 0.6rem;'
                    f"border-radius:999px;background-color:{color}22;"
                    f'color:{color};font-size:0.75rem;font-weight:700;line-height:1.4;">'
                    f"{flecha} {abs(variacion_pct):.1f}%</span>"
                )
            st.markdown(
                f'<div{atributo_titulo}>'
                f'<div style="font-size:0.875rem;color:{COLOR_NEUTRO_TEXTO_SUAVE};'
                f'min-height:2.5rem;">{etiqueta}</div>'
                f'<div style="font-size:2rem;font-weight:600;color:{COLOR_TEXTO_EJE};'
                f'line-height:1.3;">{valor}</div>'
                f'<div style="min-height:1.6rem;margin-top:0.2rem;">{badge_html}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )
            if serie and len(serie) >= 2:
                st.plotly_chart(
                    _figura_sparkline(serie),
                    use_container_width=True,
                    config={"displayModeBar": False},
                    key=f"spark_{clave}",
                )


def _inyectar_estilos_gauge_ahorro() -> None:
    """CSS para que el contenedor del gauge de "% de Ahorro General" (ver
    render_metricas_resumen) tenga el mismo fondo/borde que el resto de
    tarjetas KPI (_tarjeta_kpi_html). A diferencia de
    _inyectar_estilos_kpi_tendencia (una key por etiqueta, selector por
    subcadena) aca alcanza una key fija: solo existe una instancia de este
    gauge por pagina.

    `min-height: {ALTURA_KPI_REM}rem` (P1-6 del plan de mejoras, mismo
    valor que _tarjeta_kpi_html/_inyectar_estilos_kpi_tendencia): en
    Municipalidad de Guayaquil esta tarjeta comparte fila con una simple
    (Número de Procesos) y dos con sparkline -- sin esta altura minima
    compartida, las 4 quedaban desalineadas entre si.

    `display:flex; flex-direction:column; justify-content:center`
    (agregado despues, mismo criterio que _tarjeta_kpi_html/
    _inyectar_estilos_kpi_tendencia): el gauge en si (_figura_gauge_ahorro)
    tiene una altura de chart FIJA en pixeles menor que `ALTURA_KPI_REM`,
    asi que centrar verticalmente el label+chart dentro del piso minimo
    evita que quede todo pegado arriba con un hueco abajo. (Se probo
    tambien `height: 100%` para estirar esta tarjeta exacto a la altura
    de la columna -- no funciona, ver el mismo comentario en
    _inyectar_estilos_kpi_tendencia: los wrappers internos de Streamlit
    entre esta tarjeta y `[data-testid="stColumn"]` no tienen altura
    propia, asi que el 100% no tiene de donde resolver.)"""
    st.markdown(
        f"""
        <style>
        div[class*="st-key-kpi_gauge_ahorro"] {{
            background-color: {COLOR_LIENZO};
            border: 1px solid {COLOR_NEUTRO_BORDE};
            border-radius: 8px;
            padding: 0.75rem 1rem 0 1rem;
            margin-bottom: 0.5rem;
            min-height: {ALTURA_KPI_REM}rem;
            box-sizing: border-box;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _figura_gauge_ahorro(porcentaje: float) -> go.Figure:
    """Gauge (velocímetro) para "% de Ahorro General" -- reemplaza la
    tarjeta plana solo cuando hay una base valida para calcularlo (ver
    render_metricas_resumen, rama mostrar_monto_adjudicado=True; si
    porcentaje_ahorro_general es None, esa función sigue mostrando "N/A"
    en una tarjeta normal, sin gauge). Rango fijo 0-30: el ahorro
    observado en este dataset no supera ese entorno; un valor fuera de
    rango simplemente satura el gauge en el extremo, sin romper. Mismo
    azul primario que el resto de la app (COLOR_SIDEBAR_ACENTO) para la
    barra de progreso, y `separators=",."` (mismo truco que
    _aplicar_estilo_base) para que el numero se lea con coma decimal,
    convencion Ecuador, en vez del punto decimal por defecto de Plotly."""
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=porcentaje,
            number={"suffix": "%", "valueformat": ".2f", "font": {"color": COLOR_TEXTO_EJE, "size": 28}},
            gauge={
                "axis": {"range": [0, 30], "tickcolor": COLOR_NEUTRO_TEXTO_SUAVE},
                "bar": {"color": COLOR_SIDEBAR_ACENTO, "thickness": 0.3},
                "bgcolor": COLOR_LIENZO,
                "borderwidth": 0,
            },
        )
    )
    fig.update_layout(
        # 148 (no 190): con el label + padding del contenedor, 190 hacia
        # que la tarjeta completa (232px) superara claramente el resto de
        # tarjetas KPI de la misma fila (~184-192px, ver ALTURA_KPI_REM en
        # ui/tema.py, P1-6 del plan de mejoras) -- 148 deja el total
        # alineado con sus vecinas.
        height=148,
        margin=dict(l=20, r=20, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=COLOR_TEXTO_EJE),
        separators=",.",
    )
    return fig


def _serie_mensual_desde_df(df: pd.DataFrame, campo: str) -> list[float]:
    """Suma de `campo` agregada por mes (columna "anio_mes", ya calculada
    por preparar_dataframe), ordenada cronologicamente -- para el
    sparkline de render_kpi_card_tendencia. Lista vacia si `df` esta vacio
    o no tiene la columna "anio_mes" (ej. sin ningun registro con fecha de
    publicacion valida)."""
    if df.empty or "anio_mes" not in df.columns:
        return []
    return df.dropna(subset=["anio_mes"]).groupby("anio_mes")[campo].sum().sort_index().tolist()


def _serie_mensual(registros: list[dict], campo: str) -> list[float]:
    """Igual que _serie_mensual_desde_df, pero a partir de una lista de
    registros crudos -- usado por render_metricas_resumen (Procesos y
    Municipio de Guayaquil), que no arma un DataFrame con "anio_mes" como
    si hace render_dashboard (ver preparar_dataframe)."""
    if not registros:
        return []
    df = pd.DataFrame(registros)
    if df.empty or "fecha_publicacion" not in df.columns or campo not in df.columns:
        return []
    df["anio_mes"] = pd.to_datetime(df["fecha_publicacion"], errors="coerce").dt.strftime("%Y-%m")
    return _serie_mensual_desde_df(df, campo)


def _variacion_pct_ultimo_periodo(serie: list[float]) -> float | None:
    """% de variación del último periodo de `serie` respecto al anterior.
    None si hay menos de 2 periodos o el periodo anterior es 0/vacío
    (división por cero) -- en ese caso render_kpi_card_tendencia no
    muestra badge."""
    if len(serie) < 2 or not serie[-2]:
        return None
    return (serie[-1] - serie[-2]) / serie[-2] * 100


ESTADOS_VALOR_ADJUDICADO = {
    _normalizar_texto_provincia(estado).lower()
    for estado in (
        "Adjudicada",
        "Adjudicado - Registro de Contratos",
        "Ejecución de Contrato",
        "Finalizada",
        "En Recepción",
    )
}


def render_kpis_dashboard(df: pd.DataFrame):
    """KPIs principales del Dashboard: Procesos, Presupuesto Total y
    Presupuesto en Contratación -- lo unico visible por defecto antes de
    expandir cualquier detalle (ver render_pagina_dashboard). Los dos KPIs
    monetarios llevan ademas un mini-sparkline (tendencia mensual del
    presupuesto) y un badge de variación vs. el mes anterior -- ver
    render_kpi_card_tendencia."""
    col1, col2, col3 = st.columns(3)
    presupuesto_total = df["presupuesto_referencial"].fillna(0).sum() if not df.empty else 0
    df_contratacion = (
        df.loc[df["estado"].map(_normalizar_texto_provincia).str.lower().isin(ESTADOS_VALOR_ADJUDICADO)]
        if not df.empty
        else df
    )
    valor_adjudicado_total = (
        df_contratacion["presupuesto_referencial"].fillna(0).sum() if not df_contratacion.empty else 0
    )

    serie_presupuesto = _serie_mensual_desde_df(df, "presupuesto_referencial")
    serie_contratacion = _serie_mensual_desde_df(df_contratacion, "presupuesto_referencial")

    render_kpi_card(col1, "Procesos (filtro actual)", formatear_numero_ec(len(df)))
    render_kpi_card_tendencia(
        col2,
        "Presupuesto Total (filtro actual)",
        formatear_moneda_ec(presupuesto_total),
        serie=serie_presupuesto,
        variacion_pct=_variacion_pct_ultimo_periodo(serie_presupuesto),
    )
    render_kpi_card_tendencia(
        col3,
        "Presupuesto en Contratación (filtro actual)",
        formatear_moneda_ec(valor_adjudicado_total),
        serie=serie_contratacion,
        variacion_pct=_variacion_pct_ultimo_periodo(serie_contratacion),
        ayuda=(
            "Presupuesto Referencial (no el monto adjudicado real) de los procesos que "
            "ya avanzaron a contratación: estados Adjudicada, Adjudicado - Registro de "
            "Contratos, Ejecución de Contrato, Finalizada o En Recepción, dentro del "
            "filtro actual."
        ),
    )


def render_grafico_estado_clic(registros: list[dict]) -> str | None:
    """Grafico de barras "Procesos por Estado" con clic-para-filtrar
    (drill-down): usa el soporte nativo de seleccion de st.plotly_chart
    (`on_select="rerun"`, Streamlit >= 1.35 -- sin necesitar streamlit-
    echarts ni ninguna libreria externa) en vez de streamlit-echarts (ver
    render_kpi_card_tendencia/_figura_gauge_ahorro sobre por que este
    proyecto usa Plotly para todo lo interactivo, no ECharts).

    Devuelve el nombre del estado clicado en ESTA ejecucion del script (o
    None si no hay seleccion) -- no toca session_state ella misma, deja
    que el caller (render_pagina_municipalidad_guayaquil) decida como
    persistir/combinar el filtro; una sola responsabilidad (dibujar +
    leer el evento).

    Barras en azul suave (COLOR_BARRA_DATO) -- la del estado
    ACTUALMENTE FILTRADO (session_state.filtro_estado_click, leido aca
    solo para colorear, no para decidir el retorno) se resalta en
    naranja de acento (COLOR_BARRA_DESTACADA), mismo patron "barra lider
    destacada" que el resto de graficos de ranking de esta app, pero aca
    lo que se resalta es la SELECCION activa, no el valor mas alto."""
    conteos: dict[str, int] = {}
    for r in registros:
        estado = (r.get("estado") or "").strip()
        if estado:
            conteos[estado] = conteos.get(estado, 0) + 1
    if not conteos:
        st.info("No hay datos para graficar con los filtros actuales.")
        return None

    # Descendente + autorange="reversed" mas abajo: mismo criterio que
    # render_grafico_comparativo/render_gantt_procesos, para que el estado
    # con mas procesos quede arriba.
    estados = sorted(conteos, key=lambda e: conteos[e], reverse=True)
    valores = [conteos[e] for e in estados]
    estado_activo = st.session_state.get("filtro_estado_click")
    colores = [COLOR_BARRA_DESTACADA if e == estado_activo else COLOR_BARRA_DATO for e in estados]

    # Horizontal (P1-3 del plan de mejoras): estados largos como "Adjudicado
    # - Registro de Contratos" salian rotados a 45° en el eje X y costaban
    # de leer -- en horizontal, la etiqueta completa se lee de corrido en
    # el eje Y, sin rotar.
    fig = go.Figure(
        go.Bar(
            x=valores,
            y=estados,
            orientation="h",
            marker=dict(color=colores, cornerradius=4, line=dict(width=0)),
            hovertemplate="<b>%{y}</b><br>%{x} proceso(s)<extra></extra>",
        )
    )
    fig.update_xaxes(
        showgrid=True, gridcolor=COLOR_GRID, zeroline=False, showline=True,
        linewidth=2, linecolor=COLOR_AXIS, tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    fig.update_yaxes(
        autorange="reversed", showgrid=False, showline=True, linewidth=2,
        linecolor=COLOR_AXIS, tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    _aplicar_estilo_base(fig, altura=max(320, 34 * len(estados)))

    st.markdown("**Procesos por Estado** _(clic en una barra para filtrar)_")
    # SIN config={"displayModeBar": False}: verificado en vivo que ese flag
    # rompe la deteccion de clic/seleccion de Plotly en esta version de
    # Streamlit (1.41.1) -- con el modebar oculto, plotly_click nunca se
    # dispara, asi que el drill-down quedaria muerto. El modebar (zoom/pan/
    # camara) queda visible como costo aceptado de esa limitacion.
    evento = st.plotly_chart(
        fig,
        use_container_width=True,
        key="grafico_estado_clic",
        on_select="rerun",
        selection_mode="points",
    )
    puntos = evento.selection.points if evento and evento.selection else []
    # "y" (no "x"): el grafico es horizontal, la categoria (estado) vive en
    # el eje Y -- ver orientation="h" mas arriba.
    return puntos[0]["y"] if puntos else None


# Etapas secuenciales del pipeline de contratacion, en orden de avance --
# ver render_grafico_funnel_pipeline. "Desierta" NO es una etapa del
# pipeline (un proceso Desierto no "avanza" a ningun estado posterior):
# se muestra aparte, como fuga.
ETAPAS_PIPELINE_CONTRATACION = [
    "En Recepción",
    "Adjudicada",
    "Adjudicado - Registro de Contratos",
    "Ejecución de Contrato",
    "Finalizada",
]
# Familia de azules del mas oscuro (etapa inicial) al mas claro (etapa
# final) -- mismo criterio "familia azul" que el resto de la paleta de
# datos (PALETA_DATOS), pero en un degrade fijo de 5 pasos pensado para
# que el embudo se lea de mas intenso a mas suave.
COLORES_FUNNEL_PIPELINE = ["#0f3d75", "#1a5aa8", "#2a78d6", "#6fa8dc", "#cfe0f5"]


def render_grafico_funnel_pipeline(registros: list[dict]) -> None:
    """Embudo (funnel) del pipeline de contratacion: como avanzan los
    procesos por las etapas de ETAPAS_PIPELINE_CONTRATACION. "Desierta"
    no es una etapa del pipeline (un proceso declarado desierto no
    avanza a ningun estado posterior) -- se muestra aparte, en una
    tarjeta en color critico, como "fuga" del pipeline en vez de
    mezclarse con las barras del embudo."""
    conteos: dict[str, int] = {}
    for r in registros:
        estado = (r.get("estado") or "").strip()
        if estado:
            conteos[estado] = conteos.get(estado, 0) + 1

    valores_pipeline = [conteos.get(etapa, 0) for etapa in ETAPAS_PIPELINE_CONTRATACION]
    conteo_desierta = conteos.get("Desierta", 0)
    if not any(valores_pipeline) and not conteo_desierta:
        st.info("No hay datos para graficar con los filtros actuales.")
        return

    col_funnel, col_fuga = st.columns([3, 1])
    with col_funnel:
        st.markdown("**Pipeline de Contratación**")
        fig = go.Figure(
            go.Funnel(
                y=ETAPAS_PIPELINE_CONTRATACION,
                x=valores_pipeline,
                marker=dict(color=COLORES_FUNNEL_PIPELINE),
                textinfo="value+label",
                textfont=dict(color=COLOR_TEXTO_EJE),
                connector=dict(line=dict(color=COLOR_GRID, width=1)),
                # %{y}/%{x} (no %{label}/%{value}): con go.Funnel, la version
                # de Plotly.js que empaqueta Streamlit no sustituye los alias
                # %{label}/%{value} en hovertemplate (quedan literales en el
                # tooltip, confirmado pasando el cursor sobre el grafico en
                # vivo) aunque textinfo="value+label" (mecanismo distinto,
                # sin plantilla) si funciona -- %{y}/%{x} son los nombres de
                # atributo reales de este trace (y=ETAPAS_PIPELINE_CONTRATACION,
                # x=valores_pipeline) y si se interpolan.
                hovertemplate="<b>%{y}</b><br>%{x} proceso(s)<extra></extra>",
            )
        )
        _aplicar_estilo_base(fig, altura=360)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with col_fuga:
        st.markdown("**Fuga del pipeline**")
        render_kpi_card(
            col_fuga,
            "Desierta",
            formatear_numero_ec(conteo_desierta),
            icono="block",
            color_icono=COLOR_ESTADO_CRITICO,
            ayuda="Procesos declarados desiertos: nunca avanzaron a ninguna etapa del pipeline.",
        )


def render_grafico_mensual(df: pd.DataFrame):
    st.markdown("**Presupuesto por mes**")
    if df.empty:
        st.info("No hay datos para graficar con los filtros actuales.")
        return

    resumen = (
        df.dropna(subset=["anio_mes"])
        .groupby("anio_mes", as_index=False)["presupuesto_referencial"]
        .sum()
        .sort_values("anio_mes")
    )
    if resumen.empty:
        st.info("Los procesos filtrados no tienen fecha de publicación.")
        return

    # Monocromo: el color deja de codificar la categoria (mes, una por
    # barra) y pasa a codificar unicamente "es el mes de mayor presupuesto
    # o no" -- ver COLOR_BARRA_DATO/COLOR_BARRA_DESTACADA.
    indice_max = resumen["presupuesto_referencial"].idxmax()
    colores_barras = [
        COLOR_BARRA_DESTACADA if idx == indice_max else COLOR_BARRA_DATO
        for idx in resumen.index
    ]

    fig = px.bar(
        resumen,
        x="anio_mes",
        y="presupuesto_referencial",
    )
    fig.update_traces(
        marker=dict(color=colores_barras, cornerradius=4, line=dict(width=0)),
        hovertemplate="<b>$ %{y:,.2f}</b><br>%{x}<extra></extra>",
    )
    fig.update_xaxes(
        showgrid=False, showline=True, linewidth=2, linecolor=COLOR_AXIS,
        tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
        # Rangeslider (zoom en el tiempo): util cuando el filtro de Año/Mes
        # deja muchos meses en pantalla a la vez -- arrastrando los extremos
        # se acota el rango visible sin perder el resto de la serie. Altura
        # del grafico ampliada mas abajo (altura=440 en vez del default 380)
        # para que el slider no le quite espacio a las barras.
        rangeslider=dict(visible=True, thickness=0.08, bgcolor=COLOR_LIENZO, bordercolor=COLOR_GRID),
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=COLOR_GRID, zeroline=False,
        showline=True, linewidth=2, linecolor=COLOR_AXIS,
        tickprefix="$ ", tickformat=",.0f", tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    _aplicar_estilo_base(fig, altura=440)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_grafico_provincia(df: pd.DataFrame, top_n: int = 15):
    st.markdown("**Presupuesto por Provincia/Cantón**")
    if df.empty:
        st.info("No hay datos para graficar con los filtros actuales.")
        return

    resumen = (
        df.groupby("provincia_canton", as_index=False)["presupuesto_referencial"]
        .sum()
        .sort_values("presupuesto_referencial", ascending=False)
    )
    if resumen.empty:
        st.info("No hay datos de provincia/cantón con los filtros actuales.")
        return

    if len(resumen) > top_n:
        principal = resumen.iloc[:top_n]
        resto = resumen.iloc[top_n:]["presupuesto_referencial"].sum()
        resumen = pd.concat(
            [principal, pd.DataFrame([{"provincia_canton": "Otros", "presupuesto_referencial": resto}])],
            ignore_index=True,
        )

    # Descendente: en este grafico horizontal, Plotly ubica el primer registro
    # del dataframe arriba, asi que ordenar de mayor a menor deja la provincia
    # con mas presupuesto en la primera fila (arriba) para lectura inmediata.
    resumen = resumen.sort_values("presupuesto_referencial", ascending=False)

    # Monocromo, mismo patron que render_grafico_mensual: el eje Y ya
    # identifica cada provincia por su etiqueta, asi que un color distinto
    # por barra no aportaba informacion -- solo se resalta la de mayor
    # presupuesto.
    indice_max = resumen["presupuesto_referencial"].idxmax()
    colores_barras = [
        COLOR_BARRA_DESTACADA if idx == indice_max else COLOR_BARRA_DATO
        for idx in resumen.index
    ]

    fig = px.bar(
        resumen,
        x="presupuesto_referencial",
        y="provincia_canton",
        orientation="h",
    )
    fig.update_traces(
        marker=dict(color=colores_barras, cornerradius=4, line=dict(width=0)),
        hovertemplate="<b>$ %{x:,.2f}</b><br>%{y}<extra></extra>",
    )
    fig.update_xaxes(
        showgrid=True, gridcolor=COLOR_GRID, zeroline=False,
        showline=True, linewidth=2, linecolor=COLOR_AXIS,
        tickprefix="$ ", tickformat=",.0f", tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    fig.update_yaxes(
        showgrid=False, showline=True, linewidth=2, linecolor=COLOR_AXIS,
        tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    _aplicar_estilo_base(fig, altura=max(320, 34 * len(resumen)))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_grafico_comparativo(df: pd.DataFrame, top_n: int = 12):
    """Ranking horizontal: el usuario elige la dimension (Provincia/Cantón,
    Tipo de Compra o Estado del Proceso) y la metrica (numero de procesos o
    presupuesto referencial total) via los selectores de
    DIMENSIONES_COMPARATIVAS/METRICAS_COMPARATIVAS, y se dibuja una barra
    por categoria, de mayor a menor, con la de mayor valor resaltada en
    COLOR_BARRA_DESTACADA (naranja de acento) y el resto en
    COLOR_BARRA_DATO -- el valor tambien se anota como texto al final de
    cada barra para no depender solo del color para distinguir al lider."""
    st.markdown("**Comparativa por ranking**")
    if df.empty:
        st.info("No hay datos para graficar con los filtros actuales.")
        return

    col_dim, col_met = st.columns(2)
    dimension_label = col_dim.selectbox(
        "Comparar por", list(DIMENSIONES_COMPARATIVAS.keys()), key="comparativo_dimension"
    )
    metrica_label = col_met.selectbox(
        "Métrica", list(METRICAS_COMPARATIVAS.keys()), key="comparativo_metrica"
    )
    columna_dim = DIMENSIONES_COMPARATIVAS[dimension_label]
    cfg = METRICAS_COMPARATIVAS[metrica_label]

    resumen = (
        df.groupby(columna_dim, as_index=False)
        .agg(valor=(cfg["columna"], cfg["agg"]))
        .sort_values("valor", ascending=False)
    )
    if resumen.empty or resumen["valor"].fillna(0).eq(0).all():
        st.info("No hay valores para graficar con los filtros actuales.")
        return
    resumen = resumen.iloc[:top_n]

    valor_maximo = resumen["valor"].max()
    colores = [
        COLOR_BARRA_DESTACADA if v == valor_maximo else COLOR_BARRA_DATO
        for v in resumen["valor"]
    ]
    textos = [cfg["formato"](v) for v in resumen["valor"]]

    fig = go.Figure(
        go.Bar(
            x=resumen["valor"],
            y=resumen[columna_dim],
            orientation="h",
            marker=dict(color=colores, cornerradius=4, line=dict(width=0)),
            text=textos,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>" + metrica_label + ": %{text}<extra></extra>",
        )
    )
    # autorange="reversed" + orden descendente = la categoria con mayor
    # valor queda arriba (mismo criterio que render_gantt_procesos).
    fig.update_yaxes(
        autorange="reversed", showgrid=False, showline=True, linewidth=2,
        linecolor=COLOR_AXIS, tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    eje_x = dict(
        showgrid=True, gridcolor=COLOR_GRID, zeroline=False, showline=True,
        linewidth=2, linecolor=COLOR_AXIS, tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    if cfg["es_moneda"]:
        eje_x.update(tickprefix="$ ", tickformat=",.0f")
    fig.update_xaxes(**eje_x)

    _aplicar_estilo_base(fig, altura=max(320, 38 * len(resumen)))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


_MAPA_HOVERTEMPLATE = (
    "<b>%{customdata[0]}</b> (%{customdata[1]})<br>"
    "Total procesos: %{customdata[2]}<br>"
    "Presupuesto total: $ %{customdata[3]:,.2f}<br>"
    "%{customdata[4]}<extra></extra>"
)
_MAPA_CUSTOM_DATA = ["provincia", "capital", "procesos", "presupuesto", "detalle_estados"]


def _aplicar_estilo_mapa_oscuro(fig: go.Figure) -> None:
    """Layout compartido entre el mapa de burbujas y el coropletico:
    mismo estilo oscuro, mismo tamaño, mismo formato de colorbar -- para
    que ambas vistas del selector se vean visualmente consistentes."""
    fig.update_layout(
        mapbox_style="carto-darkmatter",
        margin=dict(l=0, r=0, t=0, b=0),
        height=620,
        paper_bgcolor=COLOR_LIENZO,
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=COLOR_TEXTO_EJE),
        coloraxis_colorbar=dict(
            # El colorbar se dibuja fuera del area del mapa (sobre
            # paper_bgcolor, que es blanco -- ver COLOR_LIENZO), no sobre
            # las teselas oscuras: necesita su propio fondo oscuro
            # explicito, si no el texto claro queda casi ilegible sobre
            # blanco.
            bgcolor="rgba(17, 24, 39, 0.9)",
            bordercolor="rgba(255, 255, 255, 0.15)",
            borderwidth=1,
            title=dict(text="Presupuesto Total<br>(USD)", font=dict(color="#E0E0E0", size=14)),
            tickfont=dict(color="#E0E0E0", size=12),
            tickprefix="$ ",
            tickformat=",.0f",
            nticks=9,
        ),
        hoverlabel=dict(bgcolor=COLOR_LIENZO, font_size=13, font_color=COLOR_TEXTO_EJE),
        separators=",.",  # formato numerico de Ecuador -- ver _aplicar_estilo_base
    )


def _construir_mapa_burbujas(df_mapa: pd.DataFrame) -> go.Figure:
    fig = px.scatter_mapbox(
        df_mapa,
        lat="lat",
        lon="lon",
        size="procesos",
        color="presupuesto",
        color_continuous_scale="Blues",
        size_max=45,
        zoom=5.8,
        center={"lat": -1.5, "lon": -78.5},
        custom_data=_MAPA_CUSTOM_DATA,
    )
    fig.update_traces(marker=dict(opacity=0.9), hovertemplate=_MAPA_HOVERTEMPLATE)
    _aplicar_estilo_mapa_oscuro(fig)
    return fig


def _construir_mapa_coropletico(df_mapa: pd.DataFrame) -> go.Figure:
    geojson = cargar_geojson_provincias()
    fig = px.choropleth_mapbox(
        df_mapa,
        geojson=geojson,
        locations="provincia_clave",
        featureidkey="properties.provincia_clave",
        color="presupuesto",
        color_continuous_scale="Blues",
        zoom=5.8,
        center={"lat": -1.5, "lon": -78.5},
        custom_data=_MAPA_CUSTOM_DATA,
    )
    fig.update_traces(marker=dict(opacity=0.75, line=dict(width=1, color="#1E293B")), hovertemplate=_MAPA_HOVERTEMPLATE)
    _aplicar_estilo_mapa_oscuro(fig)
    return fig


def render_mapa_provincias(df: pd.DataFrame):
    """Mapa geografico real de Ecuador (teselas via Mapbox/Plotly, sin
    necesidad de token: estilo oscuro "carto-darkmatter", a tono con el
    resto del dashboard), con dos vistas intercambiables: burbujas (un
    punto en la capital de cada provincia) o coropletico (cada provincia
    pintada segun su metrica, usando el GeoJSON de limites del INEC/HDX).
    En ambas, el tamaño/color de burbuja o el color de relleno indican
    numero de procesos y presupuesto total; el desglose completo por
    Estado del Proceso se ve al pasar el cursor."""
    st.markdown("**Contrataciones por Provincia (mapa)**")
    st.caption(
        "El tamaño de cada burbuja (o la intensidad del color, en la vista "
        "coroplética) indica el número de procesos de contratación en esa "
        "provincia; el color indica el presupuesto referencial total (más "
        "claro = mayor presupuesto)."
    )
    if df.empty:
        st.info("No hay datos para el mapa con los filtros actuales.")
        return

    resumen = df.groupby("provincia_clave", as_index=False).agg(
        procesos=("id", "count"), presupuesto_total=("presupuesto_referencial", "sum")
    )

    filas_mapa = []
    provincias_sin_ubicar = []
    for _, fila in resumen.iterrows():
        info = CAPITALES_PROVINCIA.get(fila["provincia_clave"])
        if info is None:
            if fila["provincia_clave"]:
                provincias_sin_ubicar.append(fila["provincia_clave"])
            continue

        conteo_estados = (
            df.loc[df["provincia_clave"] == fila["provincia_clave"], "estado"]
            .fillna("Sin estado")
            .value_counts()
        )
        detalle_estados = "<br>".join(f"{estado}: {cantidad}" for estado, cantidad in conteo_estados.items())

        filas_mapa.append({
            "provincia_clave": fila["provincia_clave"],
            "provincia": info["nombre"],
            "capital": info["capital"],
            "lat": info["lat"],
            "lon": info["lon"],
            "procesos": fila["procesos"],
            "presupuesto": fila["presupuesto_total"] or 0,
            "detalle_estados": detalle_estados,
        })

    if not filas_mapa:
        st.info("No se pudo ubicar ninguna provincia de los datos filtrados en el mapa.")
        return

    df_mapa = pd.DataFrame(filas_mapa)

    vista = st.radio(
        "Vista del mapa",
        ["Burbujas", "Coroplético"],
        horizontal=True,
        label_visibility="collapsed",
        key="vista_mapa_provincias",
    )
    if vista == "Burbujas":
        fig = _construir_mapa_burbujas(df_mapa)
    else:
        fig = _construir_mapa_coropletico(df_mapa)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    if vista == "Coroplético":
        st.caption("Límites administrativos: INEC / HDX (data.humdata.org/dataset/cod-ab-ecu), CC BY-IGO.")

    if provincias_sin_ubicar:
        st.caption(
            "No se pudo ubicar en el mapa (provincia no reconocida): "
            + ", ".join(sorted(set(provincias_sin_ubicar)))
        )


def render_treemap_provincia_estado(df: pd.DataFrame):
    """Treemap jerarquico Provincia/Canton -> Estado del Proceso, con el
    conteo de procesos como area de cada rectangulo. El color se asigna
    por Provincia/Canton (PALETA_DATOS, familia de azules ciclica): cada
    provincia tiene un tono distintivo, y sus estados hijos heredan ese
    mismo tono -- a diferencia de ICONOS_ESTADO, aca el color identifica
    la categoria (provincia), no la severidad del estado."""
    st.markdown("**Provincia/Cantón → Estado del Proceso (treemap)**")
    if df.empty:
        st.info("No hay datos para graficar con los filtros actuales.")
        return

    resumen = (
        df.groupby(["provincia_canton", "estado"], as_index=False)
        .agg(procesos=("id", "count"))
    )
    if resumen.empty:
        st.info("No hay datos para graficar con los filtros actuales.")
        return

    fig = px.treemap(
        resumen,
        path=["provincia_canton", "estado"],
        values="procesos",
        color="provincia_canton",
        color_discrete_sequence=PALETA_DATOS,
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{value} procesos",
        textfont=dict(size=13, color="#FFFFFF"),
        marker=dict(line=dict(width=2, color=COLOR_LIENZO)),
        hovertemplate=(
            "<b>%{label}</b><br>Procesos: %{value}<br>"
            "%{percentParent:.0%} de %{parent}<extra></extra>"
        ),
        root_color=COLOR_LIENZO,
    )
    _aplicar_estilo_base(fig, altura=560)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_treemap_presupuesto_tipo(df: pd.DataFrame):
    """Treemap jerarquico Tipo de Compra -> Estado del Proceso, con el
    Presupuesto Referencial (suma) como area de cada rectangulo: a
    diferencia de `render_treemap_provincia_estado` (conteo de procesos
    por provincia), este pondera por dinero -- conecta directo con la
    misma columna `presupuesto_referencial` que ya suman los KPIs y las
    tablas resumen (`render_kpis_dashboard`, `render_tablas_resumen`)."""
    st.markdown("**Distribución del Presupuesto por Tipo de Compra → Estado (treemap)**")
    resumen = construir_datos_treemap_presupuesto(df)
    if resumen.empty:
        st.info("No hay datos de presupuesto para graficar con los filtros actuales.")
        return

    fig = px.treemap(
        resumen,
        path=["tipo_compra", "estado"],
        values="presupuesto_referencial",
        color="tipo_compra",
        color_discrete_sequence=PALETA_DATOS,
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>$ %{value:,.2f}",
        textfont=dict(size=13, color="#FFFFFF"),
        marker=dict(line=dict(width=2, color=COLOR_LIENZO)),
        hovertemplate=(
            "<b>%{label}</b><br>Presupuesto: $ %{value:,.2f}<br>"
            "%{percentParent:.0%} de %{parent}<extra></extra>"
        ),
        root_color=COLOR_LIENZO,
    )
    _aplicar_estilo_base(fig, altura=560)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_gantt_procesos(df: pd.DataFrame, limite: int = 25):
    """Gantt (linea de tiempo horizontal) de los procesos con fecha de
    publicacion mas reciente: cada barra va de su `fecha_publicacion` hasta
    hoy, coloreada por estado. El portal de Compras Publicas no expone una
    fecha de cierre/ejecucion real por proceso (el "Plazo de Ejecución" de
    Especificaciones Técnicas es un texto libre en dias, capturado por documento al momento
    de redactar el pliego, no un dato historico por proceso), asi que esto
    muestra dias transcurridos desde la publicacion -- no un cronograma de
    hitos con fecha de fin real. Ver `construir_datos_gantt_procesos`."""
    st.markdown(f"**Cronograma de Procesos: días transcurridos desde su publicación (últimos {limite})**")
    st.caption(
        "El portal no expone una fecha de cierre de ejecución por proceso, así que cada "
        "barra corre desde la Fecha de Publicación hasta hoy — no representa hitos de "
        "cronograma con fecha de fin real."
    )
    datos = construir_datos_gantt_procesos(df, limite=limite)
    if datos.empty:
        st.info("No hay procesos con fecha de publicación válida para graficar con los filtros actuales.")
        return

    fig = px.timeline(
        datos,
        x_start="inicio",
        x_end="fin",
        y="etiqueta",
        color="estado",
        color_discrete_sequence=PALETA_DATOS,
        custom_data=["dias_transcurridos", "entidad_contratante"],
    )
    fig.update_traces(
        marker=dict(line=dict(width=1, color=COLOR_LIENZO)),
        hovertemplate=(
            "<b>%{y}</b><br>Entidad: %{customdata[1]}<br>"
            "Días transcurridos: %{customdata[0]}<extra></extra>"
        ),
    )
    fig.update_yaxes(autorange="reversed", title=None, tickfont=dict(color=COLOR_TEXTO_EJE))
    fig.update_xaxes(title=None, tickfont=dict(color=COLOR_TEXTO_EJE))
    _aplicar_estilo_base(fig, altura=max(360, 32 * len(datos)))
    fig.update_layout(showlegend=True, legend_title_text="Estado")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _tabla_estatica(df_mostrar: pd.DataFrame) -> pd.DataFrame:
    """Prepara un DataFrame para `st.table`: sin indice visible (imita el
    `hide_index=True` que tenian estas tablas con `st.dataframe`)."""
    tabla = df_mostrar.reset_index(drop=True).copy()
    tabla.index = [""] * len(tabla)
    return tabla


def render_tablas_resumen(df: pd.DataFrame):
    st.markdown("**Resumen por Estado y Tipo de Compra**")
    if df.empty:
        st.info("No hay datos para resumir con los filtros actuales.")
        return

    col1, col2 = st.columns(2)

    resumen_estado = (
        df.groupby("estado", as_index=False)
        .agg(Procesos=("id", "count"), Presupuesto_Total=("presupuesto_referencial", "sum"))
        .rename(columns={"estado": "Estado", "Presupuesto_Total": "Presupuesto Total"})
        .sort_values("Presupuesto Total", ascending=False)
    )
    # "% Participación" = Procesos de ese estado / total de procesos de ESTA
    # tabla (no del df completo, aunque hoy coinciden -- resumen_estado ya
    # agrupa el 100% de `df`) -- se calcula antes de formatear "Presupuesto
    # Total" como texto, para sumar sobre el numero crudo.
    total_procesos_estado = resumen_estado["Procesos"].sum()
    resumen_estado.insert(
        resumen_estado.columns.get_loc("Procesos") + 1,
        "% Participación",
        (resumen_estado["Procesos"] / total_procesos_estado * 100).map(lambda v: f"{v:.1f}%"),
    )
    resumen_estado["Presupuesto Total"] = resumen_estado["Presupuesto Total"].map(formatear_moneda_ec)
    col1.caption("Por Estado del Proceso")
    # st.table (HTML estatico) en vez de st.dataframe: el componente
    # interactivo (glide-data-grid) a veces queda en negro/vacio hasta que
    # el usuario hace clic dentro (bug conocido de ese componente con
    # grids canvas fuera de la vista inicial). Estas tablas son chicas y
    # no necesitan ordenar/redimensionar columnas, asi que el renderizado
    # estatico es un intercambio razonable -- ver tambien _tabla_estatica.
    col1.table(_tabla_estatica(resumen_estado))

    resumen_tipo = (
        df.groupby("tipo_compra", as_index=False)
        .agg(Procesos=("id", "count"), Presupuesto_Total=("presupuesto_referencial", "sum"))
        .rename(columns={"tipo_compra": "Tipo de Compra", "Presupuesto_Total": "Presupuesto Total"})
        .sort_values("Presupuesto Total", ascending=False)
    )
    resumen_tipo["Presupuesto Total"] = resumen_tipo["Presupuesto Total"].map(formatear_moneda_ec)
    col2.caption("Por Tipo de Compra (inferido del Objeto del Proceso)")
    col2.table(_tabla_estatica(resumen_tipo))


def render_metricas_resumen(registros: list[dict], mostrar_monto_adjudicado: bool = False):
    """Tarjetas de resumen sobre los resultados actualmente filtrados.

    `mostrar_monto_adjudicado` (default False, mismo criterio que
    render_tabla_con_color -- solo Municipalidad de Guayaquil) separa DOS
    metricas distintas por nombre, no las unifica: con el campo True usa
    el Monto Adjudicado real (`monto_adjudicado`, leido de la pagina de
    detalle de cada proceso durante el scraping, ver
    scripts/scrape_portal.py) y la tarjeta se llama "Valor Adjudicado
    Total"; con False (pestaña general "Procesos", todas las entidades,
    donde `monto_adjudicado` hoy no se completa de forma confiable) usa
    el Presupuesto Referencial de los mismos 5 estados que
    ESTADOS_VALOR_ADJUDICADO (ver render_kpis_dashboard) y la tarjeta se
    llama "Presupuesto en Contratación" -- para no hacer pasar un
    presupuesto por un valor adjudicado real."""
    presupuesto_total = sum(r.get("presupuesto_referencial") or 0 for r in registros)

    if mostrar_monto_adjudicado:
        registros_valor_adjudicado = registros
        campo_valor_adjudicado = "monto_adjudicado"
        etiqueta_valor_adjudicado = "Valor Adjudicado Total"
        ayuda_valor_adjudicado = (
            "Suma del Monto Adjudicado real de cada proceso (leído de su página de "
            "detalle en el portal durante la importación)."
        )
    else:
        registros_valor_adjudicado = [
            r
            for r in registros
            if _normalizar_texto_provincia(r.get("estado", "")).lower() in ESTADOS_VALOR_ADJUDICADO
        ]
        campo_valor_adjudicado = "presupuesto_referencial"
        etiqueta_valor_adjudicado = "Presupuesto en Contratación"
        ayuda_valor_adjudicado = (
            "Presupuesto Referencial (no el monto adjudicado real) de los procesos en "
            "estado Adjudicada, Adjudicado - Registro de Contratos, Ejecución de "
            "Contrato, Finalizada o En Recepción."
        )
    valor_adjudicado_total = sum(r.get(campo_valor_adjudicado) or 0 for r in registros_valor_adjudicado)

    # Sparkline + badge de variación de los dos KPIs monetarios (ver
    # render_kpi_card_tendencia) -- misma logica que render_kpis_dashboard,
    # a partir de la lista de registros (esta funcion no arma un DataFrame
    # con "anio_mes" como si hace preparar_dataframe).
    serie_presupuesto = _serie_mensual(registros, "presupuesto_referencial")
    serie_valor_adjudicado = _serie_mensual(registros_valor_adjudicado, campo_valor_adjudicado)

    if mostrar_monto_adjudicado:
        col1, col2, col3, col4 = st.columns(4)
    else:
        col1, col2, col3 = st.columns(3)
    render_kpi_card(col1, "Número de Procesos", formatear_numero_ec(len(registros)))
    render_kpi_card_tendencia(
        col2,
        "Presupuesto Total",
        formatear_moneda_ec(presupuesto_total),
        serie=serie_presupuesto,
        variacion_pct=_variacion_pct_ultimo_periodo(serie_presupuesto),
    )
    render_kpi_card_tendencia(
        col3,
        etiqueta_valor_adjudicado,
        formatear_moneda_ec(valor_adjudicado_total),
        serie=serie_valor_adjudicado,
        variacion_pct=_variacion_pct_ultimo_periodo(serie_valor_adjudicado),
        ayuda=ayuda_valor_adjudicado,
    )

    if mostrar_monto_adjudicado:
        # "% de Ahorro General": mismos 5 estados que ESTADOS_VALOR_ADJUDICADO
        # (ver render_kpis_dashboard), normalizados sin tildes/mayusculas
        # con un set (no contains) para que "Ejecución de Contrato" calce
        # igual que "ejecucion de contrato".
        registros_ahorro = [
            r
            for r in registros
            if _normalizar_texto_provincia(r.get("estado", "")).lower() in ESTADOS_VALOR_ADJUDICADO
        ]
        suma_adjudicado_ahorro = sum(r.get("monto_adjudicado") or 0 for r in registros_ahorro)
        suma_presupuesto_ahorro = sum(r.get("presupuesto_referencial") or 0 for r in registros_ahorro)
        # Signo invertido respecto a la resta literal (adjudicado/presupuesto - 1):
        # un ahorro (adjudicado menor al presupuesto) debe verse positivo.
        porcentaje_ahorro_general = (
            (1 - suma_adjudicado_ahorro / suma_presupuesto_ahorro) * 100 if suma_presupuesto_ahorro else None
        )
        ayuda_ahorro = (
            "1 - (Suma del Monto Adjudicado / Suma del Presupuesto Referencial sin IVA), "
            "sobre los procesos en estado Adjudicada, Adjudicado - Registro de Contratos, "
            "Ejecución de Contrato, Finalizada o En Recepción."
        )
        if porcentaje_ahorro_general is not None:
            _inyectar_estilos_gauge_ahorro()
            with col4:
                with st.container(key="kpi_gauge_ahorro"):
                    st.markdown(
                        f'<div style="font-size:0.875rem;color:{COLOR_NEUTRO_TEXTO_SUAVE};'
                        f'padding-top:0.35rem;" title="{html.escape(ayuda_ahorro)}">% de Ahorro General</div>',
                        unsafe_allow_html=True,
                    )
                    st.plotly_chart(
                        _figura_gauge_ahorro(porcentaje_ahorro_general),
                        use_container_width=True,
                        config={"displayModeBar": False},
                        key="gauge_ahorro",
                    )
        else:
            render_kpi_card(col4, "% de Ahorro General", "N/A", ayuda=ayuda_ahorro)


def render_tabla_con_color(registros: list[dict], mostrar_monto_adjudicado: bool = False):
    """`mostrar_monto_adjudicado` (default False) agrega la columna "Monto
    Adjudicado" Y la columna derivada "% de Ahorro" (Presupuesto
    Referencial vs. Monto Adjudicado, calculada al vuelo, no vive en la
    base de datos) -- pensadas solo para la vista de Municipalidad de
    Guayaquil (ver render_pagina_municipalidad_guayaquil), no para la
    pestaña general "Procesos" (todas las entidades), que la usa con el
    default."""
    if not registros:
        st.info("No hay procesos de contratación para mostrar.")
        return

    columnas_tabla = (
        COLUMNAS_TABLA
        if mostrar_monto_adjudicado
        else {
            clave: etiqueta
            for clave, etiqueta in COLUMNAS_TABLA.items()
            if clave not in ("monto_adjudicado", "explicacion_estado")
        }
    )
    df = pd.DataFrame(registros)
    columnas_presentes = [c for c in columnas_tabla if c in df.columns]
    df_mostrar = df[columnas_presentes].rename(columns=columnas_tabla)

    # "% de Ahorro" es un campo derivado (no vive en la base de datos, se
    # calcula al vuelo aca) = (Presupuesto Referencial - Monto Adjudicado)
    # / Presupuesto Referencial * 100. Se arma ANTES de capturar el CSV
    # (mas abajo) para que quede incluido en la descarga con el valor
    # numerico crudo, igual que Presupuesto Referencial/Monto Adjudicado.
    # Mismo gate que "Monto Adjudicado" (mostrar_monto_adjudicado): depende
    # de esa columna, y esta restringido a la misma vista (Municipalidad
    # de Guayaquil).
    if mostrar_monto_adjudicado and "Monto Adjudicado" in df_mostrar.columns:
        presupuesto = pd.to_numeric(df_mostrar["Presupuesto Referencial (sin IVA)"], errors="coerce")
        adjudicado = pd.to_numeric(df_mostrar["Monto Adjudicado"], errors="coerce")
        # Division por cero (o Presupuesto Referencial vacio) y Monto
        # Adjudicado vacio (proceso todavia no adjudicado) quedan en NaN
        # -- nunca 0% ni un error -- que se muestra como celda vacia mas
        # abajo (ver _formatear_porcentaje_ahorro). Un resultado negativo
        # (el adjudicado supero al referencial, caso atipico) se deja tal
        # cual, sin forzarlo a positivo.
        ahorro = ((presupuesto - adjudicado) / presupuesto * 100).round(2)
        ahorro = ahorro.where(presupuesto.notna() & (presupuesto != 0) & adjudicado.notna())
        # Se inserta justo despues de "Monto Adjudicado" para que quede en
        # ese orden tanto en la tabla interactiva como en el CSV.
        posicion = df_mostrar.columns.get_loc("Monto Adjudicado") + 1
        df_mostrar.insert(posicion, "% de Ahorro", ahorro)

    # El CSV conserva la URL como columna de texto propia, para referencia,
    # aunque en la tabla interactiva el enlace queda embebido en "Código".
    csv_bytes = df_mostrar.to_csv(index=False).encode("utf-8-sig")

    # "Código" se convierte en un enlace clicable (column_config.LinkColumn)
    # hacia el detalle del proceso en el portal, mostrando el texto del
    # codigo en vez de la URL: LinkColumn solo puede derivar el texto de la
    # propia URL via una regex de captura, asi que se le agrega el codigo
    # como fragmento (#codigo) al final de la URL real (los fragmentos no
    # se envian al servidor, no afectan el enlace) y se extrae con esa
    # regex. Si un proceso no tiene URL conocida, el enlace queda como un
    # ancla local (#codigo) que no navega a ningun lado.
    if "URL" in df_mostrar.columns:
        base_url = df_mostrar["URL"].fillna("")
    else:
        base_url = pd.Series([""] * len(df_mostrar), index=df_mostrar.index)
    df_mostrar["Código"] = base_url.astype(str) + "#" + df_mostrar["Código"].astype(str)

    if "Fecha de Publicación" in df_mostrar.columns:
        df_mostrar["Fecha de Publicación"] = pd.to_datetime(
            df_mostrar["Fecha de Publicación"], errors="coerce"
        )

    columnas_visibles = [c for c in df_mostrar.columns if c != "URL"]
    df_visible = df_mostrar[columnas_visibles].copy()

    # Indicador de estado como emoji + texto, sin pintar el fondo de la celda:
    # se aplica aqui (despues de armar el CSV) para que la descarga conserve
    # el texto de estado tal cual viene de la API.
    df_visible["Estado del Proceso"] = df_visible["Estado del Proceso"].apply(estado_con_emoji)

    # Presupuesto Referencial se muestra ya formateado con la convencion de
    # Ecuador (punto de miles, coma decimal): st.column_config.NumberColumn
    # no soporta configurar esos separadores (su "format" es printf/d3, en
    # locale en-US), asi que se preformatea como texto en vez de dejarlo
    # como columna numerica -- el CSV descargable (csv_bytes, mas arriba)
    # ya se armo con el valor numerico crudo, asi que la descarga no pierde
    # precision ni queda atada a este formato de texto.
    df_visible["Presupuesto Referencial (sin IVA)"] = df_visible["Presupuesto Referencial (sin IVA)"].apply(
        formatear_moneda_ec
    )
    # Monto Adjudicado: mismo formato de moneda, mismo motivo (preformateado
    # como texto en vez de columna numerica). Puede venir vacio/None -- no
    # todos los procesos estan adjudicados, y el dato solo se completa
    # durante el scraping (ver scripts/scrape_portal.py::_obtener_montos_adjudicados);
    # formatear_moneda_ec ya devuelve "" en ese caso.
    if "Monto Adjudicado" in df_visible.columns:
        df_visible["Monto Adjudicado"] = df_visible["Monto Adjudicado"].apply(formatear_moneda_ec)
    # % de Ahorro: mismo criterio (preformateado como texto). Antepone
    # 🟢/🔴 segun el signo -- mismo patron que estado_con_emoji un poco
    # mas arriba -- como indicador visual simple sin necesitar un
    # pandas Styler (que no combina bien con el column_config ya usado
    # en esta tabla, ej. LinkColumn para "Código").
    if "% de Ahorro" in df_visible.columns:
        df_visible["% de Ahorro"] = df_visible["% de Ahorro"].apply(_formatear_porcentaje_ahorro)

    # Anchos priorizados para las columnas mas importantes (Código, Entidad,
    # Estado quedan fijas/legibles sin importar cuantas columnas tenga la
    # tabla), y "Objeto del Proceso" en un ancho medio en vez de "large":
    # st.dataframe (glide-data-grid) ya trunca con "…" y muestra el texto
    # completo al pasar el cursor/hacer clic en la celda, asi que no hace
    # falta "large" para que el dato no se pierda -- solo hacia que esta
    # columna dominara el ancho de toda la tabla.
    column_config = {
        "Código": st.column_config.LinkColumn(
            "Código", pinned=True, display_text=r"#(.*)$", width="medium"
        ),
        "Entidad Contratante": st.column_config.TextColumn("Entidad Contratante", width="medium"),
        "Estado del Proceso": st.column_config.TextColumn("Estado del Proceso", width="medium"),
        "Explicación (Desierta)": st.column_config.TextColumn(
            "Explicación (Desierta)",
            width="large",
            help="Explicación en lenguaje simple de por qué el proceso quedó desierto.",
        ),
        "Objeto del Proceso": st.column_config.TextColumn("Objeto del Proceso", width="medium"),
        "Presupuesto Referencial (sin IVA)": st.column_config.TextColumn(
            "Presupuesto Referencial (sin IVA)", width="medium"
        ),
        "Monto Adjudicado": st.column_config.TextColumn("Monto Adjudicado", width="medium"),
        "% de Ahorro": st.column_config.TextColumn("% de Ahorro", width="small"),
        "Fecha de Publicación": st.column_config.DateColumn(
            "Fecha de Publicación", format="YYYY-MM-DD"
        ),
    }

    st.caption(
        ":material/lightbulb: Las celdas con texto largo (ej. Objeto del Proceso) se truncan con "
        "\"…\": pasa el cursor sobre la celda o haz clic para ver el texto completo."
    )
    st.dataframe(
        df_visible,
        column_config=column_config,
        use_container_width=True,
        hide_index=True,
        height=520,
    )

    st.download_button(
        label=":material/download: Descargar tabla (CSV)",
        data=csv_bytes,
        file_name=f"contrataciones_{date.today().isoformat()}.csv",
        mime="text/csv",
    )

    # Visor de detalle para procesos "Desierta": st.dataframe no envuelve
    # texto multilinea dentro de la celda (solo trunca con "…", visible
    # completo recien al pasar el cursor/hacer clic), asi que para un
    # texto largo como "Explicación (Desierta)" esto es la forma robusta
    # de leerlo completo -- ademas de junto a su fuente real
    # (motivo_estado_raw, el texto oficial del portal). Mismo gate que la
    # columna misma (mostrar_monto_adjudicado -- ver docstring de esta
    # funcion): solo tiene sentido en la vista de Municipalidad de
    # Guayaquil, donde motivo_estado_raw/explicacion_estado se completan.
    if mostrar_monto_adjudicado:
        desiertas = df[df["estado"].str.startswith("Desierta", na=False)] if "estado" in df.columns else df.iloc[0:0]
        if not desiertas.empty:
            st.markdown("**Ver explicación completa de un proceso Desierto**")
            codigo_elegido = st.selectbox(
                "Proceso", desiertas["codigo"], key="detalle_desierta_codigo", label_visibility="collapsed"
            )
            fila = desiertas[desiertas["codigo"] == codigo_elegido].iloc[0]
            st.markdown(f"**Motivo oficial (portal):** {fila.get('motivo_estado_raw') or '—'}")
            st.info(f"**Explicación:** {fila.get('explicacion_estado') or '—'}")


def _opciones_lote_id(registros: list[dict]) -> dict[str, str]:
    """Etiqueta legible -> lote_id real, derivada de los registros ya
    cargados (no hay un endpoint dedicado de lotes en la API). El lote_id
    crudo es un timestamp ISO ("2026-07-28T11:07:02"): aca se convierte a
    una fecha/hora legible en español y se le suma la palabra clave y el
    numero de procesos de ese lote, para no forzar al usuario a copiar/
    pegar el timestamp a mano. Ordenado del lote mas reciente al mas
    antiguo."""
    info_por_lote: dict[str, dict] = {}
    for registro in registros:
        lote = registro.get("lote_id")
        if not lote:
            continue
        info = info_por_lote.setdefault(lote, {"palabra_clave": registro.get("palabra_clave") or "", "n": 0})
        info["n"] += 1

    opciones = {}
    for lote in sorted(info_por_lote, reverse=True):
        info = info_por_lote[lote]
        try:
            fecha_legible = datetime.fromisoformat(lote).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            fecha_legible = lote
        palabra_clave = info["palabra_clave"] or "sin palabra clave"
        etiqueta = f"{fecha_legible} — {palabra_clave} ({info['n']} procesos)"
        opciones[etiqueta] = lote
    return opciones


SIN_LOTE_ESPECIFICO = "(Ninguno — usar todo el rango de fechas)"


def render_generador_reportes():
    """Seccion 'Generación de Reportes Automáticos': arma el payload y
    llama a POST /api/generar-reporte (src/api_reportes.py), que devuelve
    el .docx generado por scripts/report_generator.py."""
    st.subheader(":material/description: Generación de Reportes Automáticos")
    st.caption(
        "Genera un informe Word (.docx) con las capturas de pantalla y la "
        "tabla de procesos de una o varias palabras clave."
    )

    if "reporte_docx_bytes" not in st.session_state:
        st.session_state.reporte_docx_bytes = None

    claves_filtro_reportes = [
        "reportes_palabras_clave",
        "reportes_fecha_inicio",
        "reportes_fecha_fin",
        "reportes_lote_id",
    ]
    boton_limpiar_filtros(claves_filtro_reportes, key="reportes_limpiar_filtros")

    with st.form("form_generar_reporte"):
        palabras_clave_texto = st.text_input(
            "Palabras clave (separadas por comas)",
            placeholder="Ej: luminarias, repotenciacion",
            key="reportes_palabras_clave",
        )
        col_inicio, col_fin = st.columns(2)
        fecha_inicio = col_inicio.date_input("Fecha inicio", value=None, key="reportes_fecha_inicio")
        fecha_fin = col_fin.date_input("Fecha fin", value=None, key="reportes_fecha_fin")

        # "Lote ID" (el timestamp crudo de una ejecucion de scraping/
        # importacion) es un dato de debugging, no algo que un usuario
        # normal deba escribir a mano: se esconde en un expander colapsado
        # y se elige por un selectbox con etiquetas legibles (fecha +
        # palabra clave + cantidad de procesos), no el timestamp crudo.
        with st.expander("Opciones avanzadas", expanded=False):
            opciones_lote = _opciones_lote_id(obtener_contrataciones())
            etiqueta_lote_sel = st.selectbox(
                "Lote de carga específico (opcional)",
                [SIN_LOTE_ESPECIFICO] + list(opciones_lote.keys()),
                key="reportes_lote_id",
                help=(
                    "Si se indica, acota el reporte a una única ejecución de "
                    "scraping/importación en vez de todo el rango de fechas."
                ),
            )
        enviado = st.form_submit_button(":material/edit_document: Generar Reporte Word", type="primary", use_container_width=True)

    if enviado:
        palabras_clave = [p.strip() for p in palabras_clave_texto.split(",") if p.strip()]
        if not palabras_clave:
            st.warning("Ingresa al menos una palabra clave.")
        elif not fecha_inicio or not fecha_fin:
            st.warning("Selecciona la fecha de inicio y la fecha de fin.")
        else:
            payload = {
                "palabras_clave": palabras_clave,
                "fecha_inicio": fecha_inicio.isoformat(),
                "fecha_fin": fecha_fin.isoformat(),
            }
            if etiqueta_lote_sel != SIN_LOTE_ESPECIFICO:
                payload["lote_id"] = opciones_lote[etiqueta_lote_sel]

            with st.spinner("Generando reporte..."):
                response = generar_reporte(payload)

            if response is not None:
                if response.status_code == 200:
                    st.session_state.reporte_docx_bytes = response.content
                    st.success("Reporte generado correctamente.")
                elif response.status_code == 404:
                    st.session_state.reporte_docx_bytes = None
                    st.warning(
                        response.json().get(
                            "detail",
                            "No se encontraron procesos para los filtros indicados.",
                        )
                    )
                elif response.status_code == 422:
                    st.session_state.reporte_docx_bytes = None
                    errores = response.json().get("detail", [])
                    mensaje = "; ".join(
                        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errores
                    )
                    st.error(f"Datos inválidos: {mensaje}")
                else:
                    st.session_state.reporte_docx_bytes = None
                    st.error(f"Error al generar el reporte: {response.status_code}")

    if st.session_state.reporte_docx_bytes:
        st.download_button(
            label=":material/download: Descargar Reporte_SERCOP.docx",
            data=st.session_state.reporte_docx_bytes,
            file_name="Reporte_SERCOP.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )


def _insignia_participacion(cantidad: int, total: int) -> str | None:
    """% de participacion de `cantidad` sobre `total` (1 decimal, ej.
    '32.4%'), para mostrar como insignia separada del valor principal en
    la tarjeta -- ver render_contadores y el parametro `insignia` de
    render_kpi_card/_tarjeta_kpi_html. None (sin insignia) si total es 0
    (filtro sin resultados): mostrarla implicaria una division por
    cero."""
    if total <= 0:
        return None
    return f"{cantidad / total * 100:.1f}%"


def _render_tarjeta_estado(columna, estado_categoria: str, conteos: dict, total: int) -> None:
    etiqueta_mostrar = NOMBRES_ESTADO_COMPLETOS.get(estado_categoria, estado_categoria)
    icono, color_icono = ICONOS_ESTADO.get(estado_categoria, (None, None))
    cantidad = conteos[estado_categoria]
    render_kpi_card(
        columna,
        etiqueta_mostrar,
        formatear_numero_ec(cantidad),
        icono=icono,
        color_icono=color_icono,
        insignia=_insignia_participacion(cantidad, total),
    )


def render_contadores(registros_totales: list[dict]):
    """Revelacion progresiva: por defecto solo Total + ESTADOS_DESTACADOS (4
    tarjetas), el resto de categorias queda dentro de un expander -- antes
    se mostraban las ~12 categorias de una sola vez. Cada tarjeta de
    estado (principales y las del expander) muestra ademas, como insignia
    separada debajo del numero, su % de participacion sobre `total` --
    ver _insignia_participacion. "Total" queda sin insignia (siempre
    seria 100%, no aporta informacion)."""
    total = len(registros_totales)
    st.subheader("Contador de contrataciones")

    conteos = {}
    for estado_categoria in ESTADOS:
        conteos[estado_categoria] = sum(
            1
            for r in registros_totales
            if r.get("estado", "").strip().lower().startswith(estado_categoria.lower())
        )
    # Estados que no calzan con ninguna categoria conocida (el portal tiene
    # varios poco frecuentes, ej. "Convalidacion de Errores", "Publicar
    # resultado"): se agrupan aqui para que el desglose siempre sume el Total.
    conteos["Otros"] = total - sum(conteos.values())

    cols = st.columns(4)
    # "Total" es el agregado, no un estado individual -- sin icono a
    # proposito (ver ICONOS_ESTADO).
    render_kpi_card(cols[0], "Total", formatear_numero_ec(total))
    for i, estado_categoria in enumerate(ESTADOS_DESTACADOS, start=1):
        _render_tarjeta_estado(cols[i], estado_categoria, conteos, total)

    etiquetas_resto = [e for e in ESTADOS if e not in ESTADOS_DESTACADOS] + ["Otros"]
    with st.expander("Ver todos los estados"):
        cols_resto = st.columns(4)
        for i, estado_categoria in enumerate(etiquetas_resto):
            _render_tarjeta_estado(cols_resto[i % 4], estado_categoria, conteos, total)


def render_vaciar_base_datos():
    st.divider()
    st.subheader(":material/warning: Zona de peligro")

    if "confirmar_vaciado" not in st.session_state:
        st.session_state.confirmar_vaciado = False

    # Contenedor con borde rojo (CSS scoped via st.container(key=...), que
    # Streamlit expone como la clase ".st-key-<key>") para que la zona de
    # peligro sea inconfundible a simple vista frente al resto de la UI
    # (neutra) y frente a botones de accion normal (naranja, type="primary"
    # sin este contenedor). El boton real de borrado solo aparece
    # habilitado tras el checkbox de confirmacion.
    with st.container(key="zona_peligro_vaciar_bd", border=True):
        if not st.session_state.confirmar_vaciado:
            st.caption("Elimina **todos** los procesos de contratación de forma permanente.")
            if st.button(":material/delete_forever: Borrar todos los procesos importados", use_container_width=True):
                st.session_state.confirmar_vaciado = True
                st.rerun()
        else:
            st.error(
                "Esto eliminará **todos** los procesos de contratación importados, de forma "
                "permanente. Esta acción no se puede deshacer.",
                icon="⚠️",
            )

            # Respaldo CSV descargable ANTES de la confirmacion final -- red
            # de seguridad de datos (P1-1 del plan de mejoras): borrar era
            # irreversible sin ninguna forma de recuperar lo eliminado.
            registros_respaldo = obtener_contrataciones()
            if registros_respaldo:
                st.download_button(
                    ":material/download: Descargar respaldo (CSV) antes de borrar",
                    pd.DataFrame(registros_respaldo).to_csv(index=False).encode("utf-8-sig"),
                    f"respaldo_procesos_{date.today().isoformat()}.csv",
                    "text/csv",
                    use_container_width=True,
                )

            confirmado = st.checkbox("Sí, entiendo y quiero borrar todos los procesos importados")

            col_confirmar, col_cancelar = st.columns(2)
            if col_confirmar.button(
                ":material/delete_forever: Confirmar borrado definitivo",
                type="primary",
                disabled=not confirmado,
                use_container_width=True,
            ):
                with st.spinner("Borrando los procesos importados..."):
                    response = vaciar_base_datos()
                if response is None:
                    return
                if response.status_code == 204:
                    st.session_state.confirmar_vaciado = False
                    st.session_state.resultados = None
                    st.session_state.mensaje_vaciado = (
                        ":material/check_circle: Todos los procesos importados fueron borrados."
                    )
                    # obtener_contrataciones() esta cacheada 10 min (ver
                    # services/sercop.py): sin este .clear(), el Dashboard
                    # seguiria mostrando los procesos ya borrados hasta que
                    # expire el TTL.
                    obtener_contrataciones.clear()
                    st.rerun()
                else:
                    st.error(f"Error al borrar los procesos: {response.status_code}")

            if col_cancelar.button("Cancelar", use_container_width=True):
                st.session_state.confirmar_vaciado = False
                st.rerun()

    st.markdown(
        f"""
        <style>
        .st-key-zona_peligro_vaciar_bd {{
            border-color: {COLOR_PELIGRO} !important;
        }}
        .st-key-zona_peligro_vaciar_bd button[kind="primary"] {{
            background-color: {COLOR_PELIGRO} !important;
            border-color: {COLOR_PELIGRO} !important;
            color: #FFFFFF !important;
        }}
        .st-key-zona_peligro_vaciar_bd button[kind="primary"]:hover {{
            background-color: #a62f2f !important;  /* COLOR_PELIGRO, mas oscuro para :hover */
            border-color: #a62f2f !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def _url_preload_fuente_material_symbols() -> str | None:
    """Ubica, dentro del propio paquete de Streamlit instalado, el archivo
    .woff2 de "Material Symbols Rounded" (el que usan los shortcodes
    :material/xxx: de toda la app) y devuelve la URL relativa con la que el
    navegador ya lo pide (confirmado con una captura de red real: algo como
    "./static/media/MaterialSymbols-Rounded.<hash>.woff2"). El nombre de
    archivo incluye un hash de build que cambia entre versiones de
    Streamlit, asi que se descubre por glob en vez de hardcodearlo -- se
    rompe (devuelve None, sin reventar la carga de la pagina) solo si un
    cambio futuro de Streamlit reorganiza esa carpeta, no con cada upgrade
    de version. Cacheada porque el filesystem no cambia durante la vida del
    proceso."""
    directorio_media = Path(st.__file__).resolve().parent / "static" / "static" / "media"
    try:
        candidatos = sorted(directorio_media.glob("MaterialSymbols-Rounded*.woff2"))
    except OSError:
        return None
    if not candidatos:
        return None
    return f"./static/media/{candidatos[0].name}"


def _inyectar_precarga_fuente_iconos() -> None:
    """Inyecta un <link rel="preload"> para la fuente de iconos (Material
    Symbols) apenas arranca la pagina, ANTES de que se rendericen los
    botones del sidebar. El flash reportado (nombre del icono en texto
    crudo, ej. "travel_explore", pegado a la etiqueta) es real: medido con
    Playwright, el archivo de la fuente a veces tarda mas de un segundo en
    quedar "loaded" en una carga en frio, y ese hueco es visible aunque
    font-display:block (ya activo por defecto en el @font-face que trae
    Streamlit) intente ocultarlo. Sin preload, el navegador recien pide
    este archivo cuando el CSS de Streamlit se parsea Y un elemento que
    usa esa fuente ya esta en pantalla -- con preload, el pedido arranca
    en paralelo con el bundle de JS, apenas se inserta este <link>, sin
    esperar a ese punto. Verificado en un test aislado: un <link
    rel="preload"> insertado por innerHTML (mismo mecanismo que usa
    st.markdown(unsafe_allow_html=True), no un <link> real en <head>)
    SI dispara el fetch del recurso -- los navegadores procesan <link> en
    cualquier posicion del arbol del documento, no solo en <head>."""
    url_fuente = _url_preload_fuente_material_symbols()
    if url_fuente is None:
        return
    st.markdown(
        f'<link rel="preload" as="font" type="font/woff2" crossorigin href="{url_fuente}">',
        unsafe_allow_html=True,
    )


def _inyectar_estilos_sidebar() -> None:
    """CSS del panel lateral de navegacion: fondo oscuro, texto claro y
    el item activo resaltado (boton `type="primary"`, con acento de color
    a la izquierda) -- el sidebar ahora es navegacion pura (Dashboard/
    Procesos/Reportes/Configuración), sin filtros ni widgets sueltos, por
    eso se puede forzar el color de texto para TODO su contenido."""
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
        [data-testid="stSidebar"] .stButton > button {{
            background-color: transparent;
            border: none;
            border-left: 3px solid transparent;
            border-radius: 4px;
            text-align: left;
            justify-content: flex-start;
            color: {COLOR_SIDEBAR_TEXTO} !important;
            font-weight: 600;
            letter-spacing: 0.02em;
            padding: 0.55rem 0.8rem;
            margin-bottom: 0.15rem;
            box-shadow: none;
            width: 100%;
        }}
        [data-testid="stSidebar"] .stButton > button:hover {{
            background-color: rgba(255, 255, 255, 0.08);
            color: {COLOR_SIDEBAR_TEXTO_ACTIVO} !important;
        }}
        [data-testid="stSidebar"] .stButton > button:focus:not(:active) {{
            box-shadow: none;
        }}
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {{
            background-color: rgba(255, 255, 255, 0.10);
            border-left: 3px solid {COLOR_SIDEBAR_ACENTO};
            color: {COLOR_SIDEBAR_TEXTO_ACTIVO} !important;
        }}
        [data-testid="stSidebar"] hr {{
            border-color: rgba(255, 255, 255, 0.12);
        }}
        /* Item "Municipalidad de Guayaquil": logo institucional (fuera del
        boton, en su propia columna) + boton, en vez de un icono Material
        inline. padding-left en el contenedor replica el inset de 0.8rem
        que los demas items tienen por el padding propio del boton, para
        que el logo arranque a la misma distancia del borde que sus
        iconos. padding-left reducido en ESTE boton evita que el gap de
        las columnas se sume al padding del boton y separe demasiado el
        logo del texto. */
        .st-key-nav_municipalidad_guayaquil {{
            padding-left: 0.8rem;
            margin-bottom: 0.15rem;
        }}
        .st-key-nav_municipalidad_guayaquil [data-testid="stHorizontalBlock"] {{
            align-items: center;
        }}
        .st-key-nav_municipalidad_guayaquil [data-testid="stColumn"]:last-child {{
            margin-left: -1rem;
        }}
        .st-key-nav_municipalidad_guayaquil .stButton > button {{
            padding-left: 0;
            margin-bottom: 0;
        }}
        /* Mitiga el flash de texto crudo del nombre del icono (ej.
        "travel_explore") pegado a la etiqueta del boton en la carga
        inicial: la fuente de iconos (Material Symbols) tarda en quedar
        "loaded" (medido con Playwright: mas de un segundo en frio), y
        mientras tanto el navegador puede pintar el nombre del icono como
        texto plano en vez del glifo. El contenido del sidebar arranca
        invisible (opacity:0) SIN limite de tiempo fijo -- a diferencia de
        un fade-in por animation-delay (intentado antes: un timer ciego
        que arranca a contar desde que ESTE contenedor se inserta en el
        DOM, no desde que su contenido real -- que Streamlit puede
        completar en mensajes/deltas posteriores -- ya esta pintado, asi
        que en la practica no cubria el hueco real), aca la revelacion la
        dispara JS (ver _revelar_sidebar_cuando_cargue_fuente_iconos) en
        cuanto `document.fonts.ready` confirma que la fuente ya esta lista.
        Esta regla es solo el estado inicial + la animacion de respaldo de
        abajo; el opacity:1 real lo pone ese script. */
        [data-testid="stSidebarUserContent"] {{
            opacity: 0;
            transition: opacity 0.15s ease-in;
        }}
        /* Red de seguridad puramente CSS: si por lo que sea el script de
        revelacion no llega a correr (bloqueador de contenido, iframe de
        componentes deshabilitado, etc.), esto fuerza opacity:1 igual a
        los pocos segundos -- sin esto, una falla silenciosa del script
        dejaria el sidebar invisible para siempre, un regreso mucho peor
        que el flash original. Sin `animation-fill-mode: backwards`, esta
        animacion NO toca el opacity durante su animation-delay (usa la
        cascada normal, es decir lo que haya puesto el script de JS o la
        regla de arriba); recien se activa al cabo de los 4s. */
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


def _revelar_sidebar_cuando_cargue_fuente_iconos() -> None:
    """Componente invisible (height=0) cuyo unico trabajo es correr un
    script que espera a `document.fonts.ready` -- confirmado con un test
    aislado que SI se puede acceder al `document` de la ventana padre
    (`window.parent.document`) desde el script de un
    `st.components.v1.html`, algo que NO es posible con
    `st.markdown(unsafe_allow_html=True)` (los <script> insertados asi no
    se ejecutan, verificado tambien por separado) -- y recien entonces le
    pone opacity:1 al contenido del sidebar (ver el opacity:0 inicial en
    _inyectar_estilos_sidebar). A diferencia de una espera con tiempo fijo,
    esto reacciona al evento real de "la fuente ya esta lista" sin importar
    cuanto tarde en la practica. Incluye su propio try/except + fallback
    inmediato por si `document.fonts` no estuviera disponible (navegadores
    muy viejos) -- la red de seguridad puramente CSS de
    _inyectar_estilos_sidebar cubre, ademas, el caso de que este script ni
    siquiera llegue a ejecutarse."""
    components.html(
        """
        <script>
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
        </script>
        """,
        height=0,
    )


def render_navegacion_sidebar() -> None:
    with st.sidebar:
        with st.container(key="sercop_brand"):
            st.markdown(":material/account_balance: **SERCOP ANALYTICS**")
        st.markdown('<div class="sercop-nav-label">MÓDULO DE GESTIÓN</div>', unsafe_allow_html=True)

        for nombre, icono in NAV_ITEMS:
            activo = st.session_state.pagina_activa == nombre
            tipo_boton = "primary" if activo else "secondary"

            if nombre == "Municipalidad de Guayaquil":
                # Logo institucional real (600x210, apaisado) en vez de un
                # emoji: se muestra a la izquierda del boton con una
                # altura fija (LOGO_MUNICIPALIDAD_ALTO_PX) y el ancho
                # calculado a partir de esa misma relacion de aspecto
                # (st.image solo acepta fijar el ancho -- ver
                # LOGO_MUNICIPALIDAD_ANCHO_PX), para que no se vea
                # distorsionado. El container con key permite que
                # _inyectar_estilos_sidebar (.st-key-nav_municipalidad_
                # guayaquil) alinee el inset izquierdo y el padding del
                # boton con los demas items del menu.
                with st.container(key="nav_municipalidad_guayaquil"):
                    col_icono, col_boton = st.columns([0.6, 4], gap="small", vertical_alignment="center")
                    with col_icono:
                        st.image(str(LOGO_MUNICIPALIDAD_PATH), width=LOGO_MUNICIPALIDAD_ANCHO_PX)
                    with col_boton:
                        if st.button(
                            nombre.upper(), key=f"nav_{nombre}", use_container_width=True, type=tipo_boton,
                        ):
                            st.session_state.pagina_activa = nombre
                            st.rerun()
                continue

            if st.button(
                f"{icono}  {nombre.upper()}",
                key=f"nav_{nombre}",
                use_container_width=True,
                type=tipo_boton,
            ):
                st.session_state.pagina_activa = nombre
                st.rerun()

        render_importacion_sercop_sidebar()


def _iniciar_importacion_sercop(sin_monto_adjudicado: bool = False) -> None:
    """Lanza scripts/scrape_portal.py (ventana visible de Chromium, CAPTCHA
    resuelto a mano por el usuario -- modelo hibrido local documentado en
    el propio script) en un proceso aparte con subprocess.Popen, para no
    bloquear el hilo principal de Streamlit mientras el usuario completa la
    busqueda en el portal. El stdout/stderr se redirige a un archivo en
    DIRECTORIO_LOGS_IMPORTACION_SERCOP: es la unica forma de que
    render_pagina_importacion_sercop sepa despues cuantos registros se
    importaron o si el script fallo, ya que el proceso corre desacoplado de
    este hilo. El Popen y la ruta del log quedan en session_state para que
    esa vista pueda consultarlos en cada rerun.

    El flag "-u" (Python sin buffer) es imprescindible: sin el, los
    print() de scrape_portal.py se acumulan en el buffer interno del
    proceso hijo y NO llegan al archivo hasta que el proceso termina (o el
    buffer se llena) -- si se cancela o se cae antes de eso, todo lo
    bufferizado se pierde y el log queda vacio aunque el script ya haya
    impreso avances por consola. Con "-u" cada print() se escribe al
    archivo de inmediato, asi que la cola del log (ver
    _leer_cola_log_importacion_sercop) refleja el progreso real.

    `sin_monto_adjudicado`, si viene marcado desde el checkbox del sidebar
    (ver render_importacion_sercop_sidebar), agrega `--sin-monto-adjudicado`
    al comando: scrape_portal.py se salta la visita al detalle de cada
    proceso (mas rapido, sin el campo Monto de Adjudicacion)."""
    st.session_state.sercop_import_cancelado = False
    DIRECTORIO_LOGS_IMPORTACION_SERCOP.mkdir(parents=True, exist_ok=True)
    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = DIRECTORIO_LOGS_IMPORTACION_SERCOP / f"importacion_{marca_tiempo}.log"
    comando = [sys.executable, "-u", "scripts/scrape_portal.py"]
    if sin_monto_adjudicado:
        comando.append("--sin-monto-adjudicado")
    try:
        # Cerrar nuestro extremo del archivo apenas se lanza el proceso es
        # seguro: subprocess.Popen duplica el descriptor/handle para el
        # proceso hijo (tanto en Windows como en POSIX), asi que
        # scrape_portal.py sigue escribiendo en el mismo archivo aunque
        # este bloque `with` ya haya cerrado nuestra copia del handle.
        with open(log_path, "w", encoding="utf-8") as log_file:
            proceso = subprocess.Popen(
                comando,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
    except OSError as exc:
        # Si el lanzamiento en si falla (interprete o script no encontrado,
        # permiso denegado, etc.), sercop_import_proceso nunca llega a
        # asignarse. Sin este try/except la excepcion se propagaria fuera
        # del manejador del boton, interrumpiendo el rerun ANTES de llegar
        # a `st.session_state.pagina_activa = PAGINA_IMPORTACION_SERCOP` --
        # eso es lo que hacia que, intermitentemente, un clic en "Importar
        # desde Portal SERCOP" no cambiara de pagina.
        st.session_state.sercop_import_proceso = None
        # Seguridad: el detalle (rutas, mensajes del SO) va al log, no a la UI.
        logger.exception("No se pudo lanzar la importacion SERCOP: %s", exc)
        st.session_state.sercop_import_error_lanzamiento = "revisa que el entorno de Python esté disponible e inténtalo de nuevo."
        return
    st.session_state.sercop_import_error_lanzamiento = None
    st.session_state.sercop_import_proceso = proceso
    st.session_state.sercop_import_log_path = str(log_path)
    st.session_state.sercop_import_inicio = time.time()


def _leer_resumen_log_importacion_sercop(log_path: str) -> tuple[int, int, int] | None:
    """Busca en el log de la corrida la linea final que imprime
    scripts/scrape_portal.py al terminar sin errores ("Busqueda completa: N
    registro(s)...", ver PATRON_RESUMEN_IMPORTACION_SERCOP) y devuelve
    (importados, paginas, con_error). Devuelve None si el proceso todavia
    no llego a esa linea -- aun corriendo, o termino (con o sin error) sin
    imprimirla, por ejemplo si la ventana de Chromium se cerro manualmente
    antes de tiempo."""
    try:
        contenido = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    coincidencia = PATRON_RESUMEN_IMPORTACION_SERCOP.search(contenido)
    if not coincidencia:
        return None
    importados, paginas, con_error = (int(grupo) for grupo in coincidencia.groups())
    return importados, paginas, con_error


def _leer_cola_log_importacion_sercop(log_path: str, lineas: int = 40) -> str:
    """Ultimas `lineas` del log de la corrida, para el expander de
    diagnostico que se muestra mientras corre, si tarda de mas, o si
    termina con error o sin el resumen esperado."""
    try:
        contenido = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return "(el archivo de log todavía no existe)"
    return "\n".join(contenido.splitlines()[-lineas:]) or "(el log está vacío por ahora)"


def _formatear_duracion_es(segundos: float) -> str:
    segundos = max(0, int(segundos))
    minutos, resto = divmod(segundos, 60)
    if minutos == 0:
        return f"{resto} s"
    return f"{minutos} min {resto} s"


def render_importacion_sercop_sidebar() -> None:
    """Seccion "Importación SERCOP" del menu lateral: dispara
    _iniciar_importacion_sercop() y navega a la vista dedicada
    (render_pagina_importacion_sercop), con el mismo patron
    session_state.pagina_activa + st.rerun() que usa render_navegacion_sidebar
    para el resto de items. Antes, este boton solo lanzaba el proceso "a
    ciegas" y mostraba un st.toast que desaparecia solo a los pocos
    segundos, sin cambiar de pagina ni dejar ningun rastro visible del
    resultado (exito, cuantos registros, o si fallo)."""
    with st.sidebar:
        st.divider()
        st.caption("IMPORTACIÓN SERCOP")
        with st.expander(":material/settings: Opciones avanzadas"):
            sin_monto_adjudicado = st.checkbox(
                "Carga rápida (sin monto de adjudicación)",
                key="sercop_sin_monto_adjudicado",
                help=(
                    "Salta la visita al detalle de cada proceso -- la fase mas lenta de la "
                    "importacion -- a cambio de no traer el Monto de Adjudicacion."
                ),
            )
        activo = st.session_state.pagina_activa == PAGINA_IMPORTACION_SERCOP
        if st.button(
            ":material/refresh: Actualizar contrataciones",
            key="sercop_importar_boton",
            use_container_width=True,
            type="primary" if activo else "secondary",
        ):
            _iniciar_importacion_sercop(sin_monto_adjudicado=sin_monto_adjudicado)
            st.session_state.pagina_activa = PAGINA_IMPORTACION_SERCOP
            st.rerun()


def render_pagina_importacion_sercop() -> None:
    """Vista dedicada de la Importación SERCOP: estado del proceso lanzado
    por _iniciar_importacion_sercop() (cargando / éxito / advertencia /
    error), con el resumen final que imprime scripts/scrape_portal.py y la
    cola del log para diagnostico. Antes de esto no existia ninguna vista
    para este proceso -- el boton del sidebar lanzaba el scraper pero el
    panel principal se quedaba en la pagina anterior (Dashboard/Procesos)
    sin ningun indicio de que algo estaba corriendo."""
    st.header(":material/travel_explore: Importación SERCOP")
    st.caption(
        "Abre una ventana de Chromium contra el buscador de procesos del portal SERCOP. "
        "Completa los filtros, resuelve el CAPTCHA y presiona 'Buscar' en la propia ventana -- "
        "esta página no interviene en eso, solo importa los resultados una vez que aparecen."
    )

    proceso = st.session_state.get("sercop_import_proceso")
    if proceso is None:
        error_lanzamiento = st.session_state.get("sercop_import_error_lanzamiento")
        if error_lanzamiento:
            st.error(f":material/error: No se pudo iniciar la importación: {error_lanzamiento}")
        else:
            st.info(
                "Todavía no se ha iniciado ninguna importación en esta sesión. Usa el botón "
                "'Actualizar contrataciones' del menú lateral, o el botón de abajo, para empezar."
            )
        if st.button(":material/play_arrow: Iniciar importación", key="sercop_import_iniciar_pagina"):
            _iniciar_importacion_sercop(
                sin_monto_adjudicado=st.session_state.get("sercop_sin_monto_adjudicado", False)
            )
            st.rerun()
        return

    log_path: str = st.session_state.sercop_import_log_path
    inicio: float = st.session_state.sercop_import_inicio
    transcurrido_s = time.time() - inicio
    codigo_salida = proceso.poll()  # None mientras el proceso sigue vivo

    if codigo_salida is None:
        st.info(
            f":material/hourglass_top: Importación en curso desde hace "
            f"{_formatear_duracion_es(transcurrido_s)}. Completa el CAPTCHA y la búsqueda en la "
            "ventana de Chromium que se abrió -- esta vista se actualiza sola."
        )
        if transcurrido_s > TIMEOUT_AVISO_IMPORTACION_SERCOP_S:
            st.warning(
                f":material/warning: Lleva más de {TIMEOUT_AVISO_IMPORTACION_SERCOP_S // 60} minutos "
                "corriendo -- revisa si la ventana de Chromium sigue esperando una acción tuya "
                "(CAPTCHA, botón 'Buscar') o si quedó bloqueada. Puedes detener el proceso abajo "
                "y volver a intentarlo; el proceso NO se cancela solo."
            )

        col_actualizar, col_detener = st.columns(2)
        with col_actualizar:
            if st.button(
                ":material/refresh: Actualizar estado", key="sercop_import_actualizar", use_container_width=True
            ):
                st.rerun()
        with col_detener:
            if st.button(
                ":material/stop_circle: Detener proceso", key="sercop_import_detener", use_container_width=True
            ):
                # Marcar la cancelacion ANTES de terminar el proceso: es lo
                # que le permite a esta misma vista, en el siguiente rerun,
                # distinguir "el usuario lo cancelo a proposito" de "el
                # proceso se cayo solo" -- ambos casos terminan con el mismo
                # codigo de salida (!= 0 en Windows), asi que sin este flag
                # no hay forma de diferenciarlos solo mirando proceso.poll().
                st.session_state.sercop_import_cancelado = True
                proceso.terminate()
                # Esperar un momento a que el proceso realmente termine
                # (terminate() solo envia la señal, no es sincrono) evita
                # que el rerun de abajo todavia lo vea como "en curso" y
                # el usuario tenga que esperar otro ciclo de auto-refresco
                # para ver el resultado de la cancelacion.
                try:
                    proceso.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                st.rerun()

        with st.expander("Ver log de la importación"):
            st.code(_leer_cola_log_importacion_sercop(log_path), language=None)

        # Auto-refresco: mientras el proceso siga corriendo, esta vista se
        # vuelve a ejecutar sola cada INTERVALO_AUTOREFRESCO_IMPORTACION_SERCOP_S
        # segundos, sin depender de que el usuario haga clic manualmente en
        # "Actualizar estado". st.rerun() interrumpe la ejecucion con una
        # excepcion, asi que nada despues de esta linea llega a correr; si
        # el usuario interactua con otro elemento (ej. navega a otra
        # pagina) mientras tanto, Streamlit cancela este rerun en curso y
        # atiende esa interaccion primero -- la espera de aca no bloquea la
        # navegacion mas que el intervalo configurado.
        time.sleep(INTERVALO_AUTOREFRESCO_IMPORTACION_SERCOP_S)
        st.rerun()

    resumen = _leer_resumen_log_importacion_sercop(log_path)
    cancelado = st.session_state.get("sercop_import_cancelado", False)

    if codigo_salida == 0 and resumen is not None:
        importados, paginas, con_error = resumen
        if importados > 0:
            st.success(
                f":material/check_circle: Importación completa en "
                f"{_formatear_duracion_es(transcurrido_s)}: {importados} registro(s) insertado(s) en "
                f"{paginas} página(s) de resultados."
            )
            # obtener_contrataciones() esta cacheada 10 min (ver
            # services/sercop.py): sin este .clear(), el Dashboard/Procesos
            # seguirian mostrando los datos previos a la importacion hasta
            # que expire el TTL.
            obtener_contrataciones.clear()
        else:
            st.warning(
                ":material/info: La importación terminó sin errores, pero no se insertó ningún "
                "registro -- revisa si la búsqueda en el portal llegó a mostrar resultados antes "
                "de que el proceso terminara."
            )
        if con_error:
            st.caption(f"{con_error} registro(s) se omitieron por error de validación (ver log).")
    elif codigo_salida == 0:
        st.warning(
            ":material/info: El proceso terminó sin errores, pero no se encontró el resumen "
            "esperado en el log -- puede que la ventana se haya cerrado manualmente antes de "
            "tiempo. Revisa el log de abajo para más detalle."
        )
    elif cancelado:
        # Un codigo de salida != 0 NO siempre es un fallo real: terminate()
        # tambien deja al proceso con codigo != 0 (en Windows, 1) cuando lo
        # cancela el propio usuario. Sin este chequeo (ver el flag que setea
        # el boton "Detener proceso" mas arriba), esta cancelacion
        # intencional se mostraba con el mismo st.error de un fallo real.
        st.info(
            f":material/stop_circle: Importación cancelada -- se detuvo manualmente tras "
            f"{_formatear_duracion_es(transcurrido_s)}."
        )
    else:
        st.error(
            f":material/error: La importación falló (el proceso terminó con código de salida "
            f"{codigo_salida}). Revisa el log de abajo para ver el error exacto."
        )

    with st.expander("Ver log de la importación", expanded=codigo_salida != 0 and not cancelado):
        st.code(_leer_cola_log_importacion_sercop(log_path), language=None)

    if st.button(":material/refresh: Iniciar nueva importación", key="sercop_import_reiniciar"):
        _iniciar_importacion_sercop(
            sin_monto_adjudicado=st.session_state.get("sercop_sin_monto_adjudicado", False)
        )
        st.rerun()


def _render_detalles_dashboard(df_filtrado: pd.DataFrame) -> None:
    """Bloque "detalles" de render_dashboard: los 8 graficos/tablas de
    detalle (incluido el grafico mensual, dentro del grupo "Tiempo") se
    agrupan en 3 pestañas tematicas (Resúmenes/Territorio/Tiempo) en vez de
    8 pestañas sueltas al mismo nivel -- cada grupo abre sus propias
    sub-pestañas anidadas (revelacion progresiva)."""
    grupo_resumenes, grupo_territorio, grupo_tiempo = st.tabs(
        [":material/receipt_long: Resúmenes", ":material/public: Territorio", ":material/schedule: Tiempo"]
    )

    with grupo_resumenes:
        tab_resumen, tab_presupuesto, tab_items, tab_comparativa = st.tabs(
            [
                ":material/receipt_long: Por estado y tipo de compra",
                ":material/payments: Presupuesto por Tipo (Treemap)",
                ":material/inventory_2: Presupuesto por Ítem (Especificaciones Técnicas)",
                ":material/leaderboard: Comparativa (ranking)",
            ]
        )
        with tab_resumen:
            render_tablas_resumen(df_filtrado)
        with tab_presupuesto:
            render_treemap_presupuesto_tipo(df_filtrado)
        with tab_items:
            render_treemap_items_especificaciones_tecnicas(
                st.session_state.get("especificaciones_tecnicas_items_df", _dataframe_items_especificaciones_tecnicas_vacio())
            )
        with tab_comparativa:
            render_grafico_comparativo(df_filtrado)

    with grupo_territorio:
        tab_provincia, tab_treemap = st.tabs(
            [
                ":material/location_on: Detalle por provincia",
                ":material/account_tree: Provincia → Estado",
            ]
        )
        with tab_provincia:
            render_grafico_provincia(df_filtrado)
            render_mapa_provincias(df_filtrado)
        with tab_treemap:
            render_treemap_provincia_estado(df_filtrado)

    with grupo_tiempo:
        tab_mensual, tab_gantt = st.tabs(
            [
                ":material/calendar_month: Detalle por mes",
                ":material/timeline: Cronograma de Procesos (Gantt)",
            ]
        )
        with tab_mensual:
            render_grafico_mensual(df_filtrado)
        with tab_gantt:
            render_gantt_procesos(df_filtrado)


def render_dashboard(registros_totales: list[dict], titulo: str, key_prefix: str = "") -> None:
    """Dashboard reutilizable: titulo -> contador de estados -> filtros
    (Año/Mes/Provincia/Entidad Contratante) -> fila de KPIs -> detalles en
    pestañas (ver _render_detalles_dashboard). Ninguna logica de
    agregacion vive aca, solo orquesta el render sobre lo que le pasen.

    Hasta P0-2 del plan de mejoras existia un segundo caller ("Dashboard
    Municipio de Guayaquil", un item de menu aparte que pre-filtraba los
    registros a esa entidad antes de llamar aca) -- se elimino porque el
    filtro de Entidad Contratante agregado a render_filtros_dashboard logra
    la misma vista sin duplicar pagina ni logica de menu. `key_prefix`
    queda igual por si en el futuro vuelve a haber mas de un caller (ver
    render_filtros_dashboard, que lo usa para no compartir keys de
    session_state entre instancias).

    El contador de estados se ve primero (antes de los selectores de
    filtro, que van debajo del divider), pero DEBE reflejar el filtro de
    Año/Mes/Provincia/Entidad igual que la fila de KPIs y el detalle -- por
    eso se reserva su lugar con `st.container()` (contenedor_contadores) y
    recien se llena mas abajo, ya con `df_filtrado` en mano: Streamlit
    inserta el contenido de un container en la posicion donde se creo el
    container, no donde se llena, asi que el orden visual no cambia."""
    st.header(titulo)
    contenedor_contadores = st.container()
    st.divider()

    df_totales = preparar_dataframe(registros_totales)
    df_filtrado = render_filtros_dashboard(df_totales, key_prefix=key_prefix)

    with contenedor_contadores:
        render_contadores(df_filtrado.to_dict("records"))

    render_kpis_dashboard(df_filtrado)

    _render_detalles_dashboard(df_filtrado)


def render_pagina_dashboard(registros_totales: list[dict]) -> None:
    render_dashboard(
        registros_totales,
        titulo=":material/analytics: Dashboard Analítico",
        key_prefix="global_",
    )


CLAVES_FILTRO_PROCESOS = [
    "procesos_estado",
    "procesos_fecha_inicio",
    "procesos_fecha_fin",
    "procesos_palabra_clave",
]


def render_pagina_procesos(registros_totales: list[dict]) -> None:
    st.header(":material/assignment: Procesos de Contratación")

    col_estado, col_inicio, col_fin, col_palabra = st.columns([1, 1, 1, 1.4])
    with col_estado:
        estado_filtro = st.selectbox("Estado del Proceso", ["(Todos)"] + ESTADOS, key="procesos_estado")
    with col_inicio:
        fecha_inicio = st.date_input("Fecha inicio", value=None, key="procesos_fecha_inicio")
    with col_fin:
        fecha_fin = st.date_input("Fecha fin", value=None, key="procesos_fecha_fin")
    with col_palabra:
        palabra_clave_filtro = st.text_input(
            "Palabra clave",
            placeholder="Ej: luminarias",
            key="procesos_palabra_clave",
            max_chars=MAX_LARGO_PALABRA_CLAVE,
            help="Se ignoran tildes y mayúsculas. Máximo 100 caracteres.",
        )
    # Seguridad: el texto se sanea antes de salir hacia la API (Unicode NFC,
    # sin caracteres de control/ancho cero, espacios colapsados). Se conservan
    # ñ y tildes. Ver scripts/formato_ec.py::limpiar_texto_libre.
    palabra_clave_filtro = limpiar_texto_libre(palabra_clave_filtro, max_len=MAX_LARGO_PALABRA_CLAVE)

    rango_fechas_invalido = bool(fecha_inicio and fecha_fin and fecha_inicio > fecha_fin)
    if rango_fechas_invalido:
        st.warning(":material/event_busy: La fecha de inicio no puede ser posterior a la fecha fin.")

    col_buscar, col_limpiar, _ = st.columns([1, 1, 4])
    buscar = col_buscar.button(
        ":material/search: Buscar",
        type="primary",
        width="stretch",
        disabled=rango_fechas_invalido,
    )
    with col_limpiar:
        boton_limpiar_filtros(
            CLAVES_FILTRO_PROCESOS,
            key="procesos_limpiar_filtros",
            on_clear=lambda: st.session_state.update(resultados=None),
        )

    if buscar:
        with st.spinner("Buscando procesos..."):
            st.session_state.resultados = obtener_contrataciones(
                status=None if estado_filtro == "(Todos)" else estado_filtro,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                palabra_clave=palabra_clave_filtro or None,
            )

    st.divider()
    registros_mostrar = (
        st.session_state.resultados
        if st.session_state.resultados is not None
        else registros_totales
    )
    render_metricas_resumen(registros_mostrar)
    render_tabla_con_color(registros_mostrar)


def render_pagina_reportes() -> None:
    st.header(":material/description: Reportes")
    render_generador_reportes()


def filtrar_por_entidad(registros: list[dict], entidad: str) -> list[dict]:
    """Filtra por Entidad Contratante exacta, insensible a mayusculas y
    tildes (misma normalizacion que _normalizar_texto_provincia, reusada
    aqui igual que ya se hace para tipo_compra): protege contra
    variaciones de escritura del dato crudo del portal, aunque hoy la
    base solo tenga una unica forma de escritura para cada entidad."""
    clave = _normalizar_texto_provincia(entidad)
    return [r for r in registros if _normalizar_texto_provincia(r.get("entidad_contratante")) == clave]


def _anios_disponibles(registros: list[dict]) -> list[str]:
    """Años presentes en fecha_publicacion (primeros 4 caracteres), sin
    duplicados y ordenados del mas reciente al mas antiguo."""
    anios = {(r.get("fecha_publicacion") or "")[:4] for r in registros if (r.get("fecha_publicacion") or "")[:4]}
    return sorted(anios, reverse=True)


def _filtrar_por_anio(registros: list[dict], anio: str | None) -> list[dict]:
    """Filtra por año de fecha_publicacion. anio=None devuelve todo."""
    if anio is None:
        return registros
    return [r for r in registros if (r.get("fecha_publicacion") or "")[:4] == anio]


def _slug_nombre_archivo(texto: str) -> str:
    clave = _normalizar_texto_provincia(texto)  # sin tildes, mayusculas
    slug = re.sub(r"[^A-Za-z0-9]+", "_", clave).strip("_")
    return slug[:80] or "SinTitulo"


def _iniciar_actualizacion_montos_adjudicados() -> None:
    """Lanza scripts/actualizar_montos_adjudicados.py --entidad
    "Municipalidad de Guayaquil" en un proceso aparte, con el mismo patron
    de log + session_state que _iniciar_importacion_sercop. A diferencia
    de ese script, este SI corre headless (no hay CAPTCHA involucrado --
    visita directamente los enlaces de detalle que cada proceso ya tiene
    guardados en `url`, ver el docstring del propio script), asi que no
    abre ninguna ventana visible ni bloquea al usuario."""
    st.session_state.actualizar_montos_proceso = None
    DIRECTORIO_LOGS_IMPORTACION_SERCOP.mkdir(parents=True, exist_ok=True)
    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = DIRECTORIO_LOGS_IMPORTACION_SERCOP / f"actualizar_montos_{marca_tiempo}.log"
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proceso = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    "scripts/actualizar_montos_adjudicados.py",
                    "--entidad",
                    ENTIDAD_MUNICIPALIDAD_GUAYAQUIL,
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
    except OSError as exc:
        logger.exception("No se pudo lanzar la actualizacion de montos adjudicados: %s", exc)
        st.session_state.actualizar_montos_error_lanzamiento = "revisa que el entorno de Python esté disponible e inténtalo de nuevo."
        return
    st.session_state.actualizar_montos_error_lanzamiento = None
    st.session_state.actualizar_montos_proceso = proceso
    st.session_state.actualizar_montos_log_path = str(log_path)
    st.session_state.actualizar_montos_inicio = time.time()


def render_actualizar_montos_adjudicados() -> None:
    """Botón "Actualizar Montos Adjudicados" para Municipalidad de
    Guayaquil: reintenta scripts/actualizar_montos_adjudicados.py sobre
    los procesos que todavía no tienen `monto_adjudicado` (importados
    antes de que este campo existiera, o cuya extracción falló la primera
    vez). Mismo patrón de estado que Importación SERCOP (log +
    auto-refresco cada INTERVALO_AUTOREFRESCO_IMPORTACION_SERCOP_S
    segundos), simplificado a un solo bloque en vez de una página aparte:
    esto es una acción de "completar datos" puntual y rápida (sin
    CAPTCHA), no un flujo largo que necesite su propia navegación."""
    st.caption(
        "Completa el Monto Adjudicado de los procesos que todavía no lo tienen (recién "
        "adjudicados desde la última importación, o que fallaron antes). No requiere "
        "CAPTCHA -- corre en segundo plano, sin abrir ninguna ventana."
    )
    if st.button(":material/sync: Actualizar Montos Adjudicados", key="actualizar_montos_boton"):
        _iniciar_actualizacion_montos_adjudicados()
        st.rerun()

    proceso = st.session_state.get("actualizar_montos_proceso")
    if proceso is None:
        error_lanzamiento = st.session_state.get("actualizar_montos_error_lanzamiento")
        if error_lanzamiento:
            st.error(f":material/error: No se pudo iniciar la actualización: {error_lanzamiento}")
        return

    log_path: str = st.session_state.actualizar_montos_log_path
    inicio: float = st.session_state.actualizar_montos_inicio
    transcurrido_s = time.time() - inicio
    codigo_salida = proceso.poll()

    if codigo_salida is None:
        st.info(f":material/hourglass_top: Actualizando desde hace {_formatear_duracion_es(transcurrido_s)}...")
        with st.expander("Ver log"):
            st.code(_leer_cola_log_importacion_sercop(log_path), language=None)
        time.sleep(INTERVALO_AUTOREFRESCO_IMPORTACION_SERCOP_S)
        st.rerun()

    try:
        contenido_log = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        contenido_log = ""
    resumen = PATRON_RESUMEN_ACTUALIZAR_MONTOS.search(contenido_log)

    if codigo_salida == 0 and resumen is not None:
        actualizados, sin_adjudicar, con_error = (int(grupo) for grupo in resumen.groups())
        if actualizados > 0:
            st.success(
                f":material/check_circle: {actualizados} proceso(s) actualizado(s) en "
                f"{_formatear_duracion_es(transcurrido_s)}. {sin_adjudicar} sin adjudicar todavía."
            )
            # obtener_contrataciones() esta cacheada 10 min (ver
            # services/sercop.py): sin este .clear(), Municipalidad de
            # Guayaquil (KPIs, tabla, gauge de ahorro) seguiria mostrando los
            # montos adjudicados previos hasta que expire el TTL.
            obtener_contrataciones.clear()
        else:
            st.info(
                f":material/info: Ningún proceso nuevo para actualizar "
                f"({sin_adjudicar} sin adjudicar todavía)."
            )
        if con_error:
            st.caption(f"{con_error} proceso(s) con error al actualizar (ver log).")
    elif codigo_salida == 0:
        st.warning(":material/info: El proceso terminó sin errores, pero no se encontró el resumen esperado.")
    else:
        st.error(f":material/error: La actualización falló (código de salida {codigo_salida}). Revisa el log.")

    with st.expander("Ver log", expanded=codigo_salida != 0):
        st.code(_leer_cola_log_importacion_sercop(log_path), language=None)


def render_pagina_municipalidad_guayaquil(registros_totales: list[dict]) -> None:
    st.header(":material/location_city: Municipalidad de Guayaquil")
    registros_municipio = filtrar_por_entidad(registros_totales, ENTIDAD_MUNICIPALIDAD_GUAYAQUIL)
    if registros_municipio:
        col_anio, _ = st.columns([1, 3])
        anios = _anios_disponibles(registros_municipio)
        anio_sel = col_anio.selectbox("Año", ["(Todos)"] + anios, key="muni_gye_anio")
        anio_filtro = None if anio_sel == "(Todos)" else anio_sel
        registros_filtrados = _filtrar_por_anio(registros_municipio, anio_filtro)

        st.caption(
            f"Mostrando {len(registros_filtrados)} de {len(registros_municipio)} contrataciones · Año: {anio_sel}"
        )

        if registros_filtrados:
            estado_clic = render_grafico_estado_clic(registros_filtrados)
            if estado_clic and estado_clic != st.session_state.get("filtro_estado_click"):
                st.session_state.filtro_estado_click = estado_clic
                st.rerun()

            st.divider()
            # Usa registros_filtrados (solo filtro de Año), NO registros_finales
            # (que ademas aplicaria el filtro de estado del clic): el funnel
            # existe para mostrar el pipeline COMPLETO de una sola vez, encadenarlo
            # al clic lo colapsaria a una sola etapa, perdiendo el sentido.
            render_grafico_funnel_pipeline(registros_filtrados)
            st.divider()

            estado_filtro = st.session_state.get("filtro_estado_click")
            registros_finales = registros_filtrados
            if estado_filtro:
                clave_estado_filtro = _normalizar_texto_provincia(estado_filtro)
                registros_finales = [
                    r
                    for r in registros_filtrados
                    if _normalizar_texto_provincia(r.get("estado", "")) == clave_estado_filtro
                ]
                col_chip, _ = st.columns([1, 3])
                with col_chip:
                    if st.button(f"Filtrado por estado: {estado_filtro} ✕", key="limpiar_filtro_estado_click"):
                        st.session_state.pop("filtro_estado_click", None)
                        # Tambien se limpia la seleccion propia del grafico (su
                        # session_state por key): sin esto, el clic anterior
                        # seguiria "activo" en el widget y este boton no
                        # tendria efecto -- volveria a filtrar por el mismo
                        # estado en el siguiente rerun (ver render_grafico_
                        # estado_clic, que lee su propia seleccion cada vez).
                        st.session_state.pop("grafico_estado_clic", None)
                        st.rerun()

            if registros_finales:
                render_contadores(registros_finales)
                st.divider()
                render_metricas_resumen(registros_finales, mostrar_monto_adjudicado=True)
                render_tabla_con_color(registros_finales, mostrar_monto_adjudicado=True)
                render_actualizar_montos_adjudicados()
            else:
                st.info(f'No se encontraron procesos para el estado "{estado_filtro}".')
        else:
            st.info(f"No se encontraron procesos para el año {anio_sel}.")
    else:
        st.info(f'No se encontraron procesos para "{ENTIDAD_MUNICIPALIDAD_GUAYAQUIL}".')

    st.divider()
    render_formularios_y_registro()


def render_pagina_configuracion() -> None:
    st.header(":material/settings: Configuración")
    render_vaciar_base_datos()


def _deshabilitar_traduccion_automatica() -> None:
    """Evita que Google Translate (activado por el usuario en Chrome)
    traduzca la pagina: los iconos de Material Symbols son ligaduras de
    texto (Streamlit renderiza el nombre del icono, ej. "settings", y la
    fuente lo dibuja como glifo) -- si el navegador los traduce ("ajustes"
    en vez de "settings"), la fuente no tiene esa ligadura y el icono se ve
    como texto crudo. El titulo/logo en español tambien queda mal
    traducido de paso. `<meta name="google" content="notranslate">`
    conviene ponerlo en <head>, pero Streamlit no lo expone -- se inserta
    via `components.html` (accede a `window.parent.document`, confirmado
    en un test aislado -- ver _revelar_sidebar_cuando_cargue_fuente_iconos;
    un <script> insertado por st.markdown(unsafe_allow_html=True) NO se
    ejecuta)."""
    components.html(
        """
        <script>
        const meta = window.parent.document.createElement('meta');
        meta.name = 'google';
        meta.content = 'notranslate';
        window.parent.document.head.appendChild(meta);
        window.parent.document.documentElement.setAttribute('translate', 'no');
        window.parent.document.documentElement.classList.add('notranslate');
        </script>
        """,
        height=0,
    )


def main():
    st.set_page_config(page_title="SERCOP Analytics", layout="wide")
    _deshabilitar_traduccion_automatica()
    _inyectar_precarga_fuente_iconos()
    _inyectar_estilos_sidebar()
    _revelar_sidebar_cuando_cargue_fuente_iconos()

    if "resultados" not in st.session_state:
        st.session_state.resultados = None
    if "pagina_activa" not in st.session_state:
        st.session_state.pagina_activa = "Dashboard"

    if st.session_state.get("mensaje_vaciado"):
        st.success(st.session_state.mensaje_vaciado)
        st.session_state.mensaje_vaciado = None

    render_navegacion_sidebar()

    # obtener_contrataciones() esta cacheada (ttl=600s), pero igual evitamos
    # llamarla del todo en paginas que no la necesitan (Reportes solo pega a
    # /api/generar-reporte, Configuración solo a /api/todos DELETE). El
    # spinner solo se nota quando hay cache miss (round-trip real a la
    # API); en cache hit es practicamente instantaneo.
    pagina = st.session_state.pagina_activa
    if pagina == "Dashboard":
        with st.spinner("Cargando datos del dashboard..."):
            registros = obtener_contrataciones()
        render_pagina_dashboard(registros)
    elif pagina == "Procesos":
        with st.spinner("Cargando procesos..."):
            registros = obtener_contrataciones()
        render_pagina_procesos(registros)
    elif pagina == "Reportes":
        render_pagina_reportes()
    elif pagina == "Municipalidad de Guayaquil":
        with st.spinner("Cargando datos de la Municipalidad de Guayaquil..."):
            registros = obtener_contrataciones()
        render_pagina_municipalidad_guayaquil(registros)
    elif pagina == "Configuración":
        render_pagina_configuracion()
    elif pagina == PAGINA_IMPORTACION_SERCOP:
        render_pagina_importacion_sercop()


if __name__ == "__main__":
    main()
