"""Interfaz Streamlit para visualizar procesos de contratacion publica.

Consume la API FastAPI (src/main.py) via requests. Arranque:

    uvicorn src.main:app --port 8000
    streamlit run app_ui.py --server.port 8501
"""
import base64
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from dotenv import load_dotenv

from scripts.especificaciones_tecnicas_generator import (
    COLOR_BORDE_TABLA_ITEMS,
    COORDINACION_FIJA,
    FIRMA_APROBADO_POR_DEFECTO_CARGO,
    FIRMA_APROBADO_POR_DEFECTO_NOMBRE,
    IMAGEN_ENCABEZADO,
    IMAGEN_PIE_PAGINA,
    TABLA_CHECKLIST_CRITERIOS_FIJOS,
    TABLA_CHECKLIST_ENCABEZADO,
    TABLA_PATRIMONIO_BIENES_SERVICIOS,
    TABLA_PATRIMONIO_ENCABEZADO,
    TABLA_PATRIMONIO_OBRAS,
    TABLA_PUNTAJE_ENCABEZADO,
    TABLA_PUNTAJE_FIJA,
    TEXTO_ADMINISTRADOR_CIERRE,
    TEXTO_ADMINISTRADOR_OBLIGACIONES_ADICIONALES,
    TEXTO_ADMINISTRADOR_OBLIGACIONES_INTRO,
    TEXTO_ADMINISTRADOR_INTRO_PLANTILLA,
    TEXTO_ANALISIS_ESTRATEGIA_FIJO,
    TEXTO_ATRIBUCIONES_ADMINISTRADOR,
    TEXTO_CERTIFICADO_PROVEEDOR_EXCLUSIVO_INTRO,
    TEXTO_CHECKLIST_INTRO,
    TEXTO_EXPERIENCIA_ESPECIFICA_PLANTILLA,
    TEXTO_EXPERIENCIA_GENERAL_PLANTILLA,
    TEXTO_EXPERIENCIA_PERSONAL_TECNICO,
    TEXTO_FORMACION_PERSONAL_TECNICO_PLANTILLA,
    TEXTO_GARANTIA_BUEN_USO_ANTICIPO,
    TEXTO_GARANTIA_FIEL_CUMPLIMIENTO,
    TEXTO_GARANTIA_RESPONSABILIDAD_CIVIL_PLANTILLA,
    TEXTO_MULTAS,
    TEXTO_PARAMETROS_EVALUACION_INTRO,
    TEXTO_PATRIMONIO_INTRO,
    TEXTO_PUNTAJE_INTRO,
    TEXTO_REAJUSTE_PRECIOS,
    TEXTO_TIEMPO_EXISTENCIA_LEGAL,
    TEXTO_VIGENCIA_OFERTA_PLANTILLA,
    TITULO_PROCESO_FIJO,
    generar_especificaciones_tecnicas,
)
from scripts.dashboard_analitico import (
    construir_datos_gantt_procesos,
    construir_datos_treemap_presupuesto,
)
from scripts.formato_ec import formatear_moneda_ec, formatear_numero_ec
from scripts.tinymce_editor import tinymce_editor

load_dotenv()

API_URL = os.environ.get("API_URL", "http://localhost:8000")

# Panel lateral de navegacion (estilo ERP: fondo oscuro, etiqueta de
# seccion con acento de color, items con icono + texto claro).
COLOR_SIDEBAR_FONDO = "#1E293B"
COLOR_SIDEBAR_TEXTO = "#CBD5E1"
COLOR_SIDEBAR_TEXTO_ACTIVO = "#FFFFFF"
COLOR_SIDEBAR_ACENTO = "#FF9800"  # mismo naranja de PALETA_VIVA, como acento de marca

# Paleta general de la interfaz (fuera de graficos): el naranja/rojo vibrante
# se reserva para botones de accion primaria (type="primary", ya configurado
# como primaryColor en .streamlit/config.toml) y para alertas -- el resto de
# la UI usa estos tonos neutros. COLOR_PELIGRO es un rojo aparte, mas oscuro
# y saturado que el naranja de marca, exclusivo para acciones destructivas
# (Vaciar Base de Datos), para que nunca se confunda con una accion primaria
# normal (Generar Reporte, Guardar Items, etc.).
COLOR_PELIGRO = "#DC2626"
COLOR_PELIGRO_FONDO_SUAVE = "#FEF2F2"
COLOR_NEUTRO_BORDE = "#E2E8F0"
COLOR_NEUTRO_TEXTO_SUAVE = "#64748B"

NAV_ITEMS = [
    ("Dashboard", ":material/monitoring:"),
    ("Procesos", ":material/assignment:"),
    ("Reportes", ":material/description:"),
    ("Municipalidad de Guayaquil", ":material/location_city:"),
    ("Configuración", ":material/settings:"),
]

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

COLUMNAS_TABLA = {
    "codigo": "Código",
    "entidad_contratante": "Entidad Contratante",
    "objeto_proceso": "Objeto del Proceso",
    "estado": "Estado del Proceso",
    "provincia_canton": "Provincia/Cantón",
    "presupuesto_referencial": "Presupuesto Referencial (sin IVA)",
    "fecha_publicacion": "Fecha de Publicación",
    "palabra_clave": "Palabra Clave",
    "url": "URL",
}

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# Paleta viva del dashboard: se reparte automaticamente entre barras/segmentos
# (color_discrete_sequence) para dar contraste y dinamismo visual, sin atarse
# al significado de ninguna variable especifica.
PALETA_VIVA = [
    "#E91E63", "#FF9800", "#FFEB3B", "#8BC34A",
    "#00BCD4", "#9C27B0", "#F44336", "#2196F3",
]
COLOR_LIENZO = "#FFFFFF"  # plot_bgcolor / paper_bgcolor: fondo claro fijo,
                          # independiente del tema (claro u oscuro) de Streamlit
COLOR_GRID = "#E0E0E0"  # gridlines grises muy tenues
COLOR_AXIS = "black"  # linea solida de eje ("trazo de tinta")
COLOR_TEXTO_EJE = "black"  # texto de ejes/fuente general, alto contraste sobre el lienzo claro

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


def api_request(method: str, path: str, timeout: int = 10, **kwargs):
    # Si la API exige X-API-Key (variable API_KEY configurada del lado del
    # servidor -- ver src/auth.py), Streamlit debe mandar la misma clave via
    # esta misma variable de entorno en su propio proceso.
    api_key = os.environ.get("API_KEY")
    if api_key:
        headers = {"X-API-Key": api_key, **kwargs.pop("headers", {})}
        kwargs["headers"] = headers
    try:
        response = requests.request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
    except requests.exceptions.ConnectionError:
        st.error(
            f"No se pudo conectar a la API en {API_URL}. "
            "¿Está corriendo `uvicorn src.main:app --port 8000`?"
        )
        return None
    return response


@st.cache_data(ttl=60)
def obtener_contrataciones(status=None, fecha_inicio=None, fecha_fin=None, palabra_clave=None):
    params = {}
    if status:
        # El query param se llama "estado" en la API (ver
        # src/main.py::listar_contrataciones) -- se renombro para no
        # colisionar con el modulo `status` de FastAPI importado ahi mismo.
        params["estado"] = status
    if fecha_inicio:
        params["fecha_inicio"] = fecha_inicio.isoformat()
    if fecha_fin:
        params["fecha_fin"] = fecha_fin.isoformat()
    if palabra_clave:
        params["palabra_clave"] = palabra_clave

    response = api_request("GET", "/api/todos", params=params)
    if response is None:
        return []
    if response.status_code != 200:
        st.error(f"Error al consultar la API: {response.status_code}")
        return []
    return response.json()


# Sin @st.cache_data: a diferencia de obtener_contrataciones (datos del
# portal, cambian poco), la lista de borradores debe reflejar de
# inmediato cualquier guardado/eliminado hecho en el propio rerun
# anterior -- un TTL, por corto que sea, mostraria el selectbox
# desactualizado justo despues de guardar o borrar.
def listar_borradores_especificaciones_tecnicas() -> list[dict]:
    response = api_request("GET", "/api/borradores")
    if response is None:
        return []
    if response.status_code != 200:
        st.error(f"Error al consultar los borradores guardados: {response.status_code}")
        return []
    return response.json()


def obtener_borrador_especificaciones_tecnicas(borrador_id: int) -> dict | None:
    response = api_request("GET", f"/api/borradores/{borrador_id}")
    if response is None:
        return None
    if response.status_code != 200:
        st.error(f"Error al cargar el borrador: {response.status_code}")
        return None
    return response.json()


def guardar_borrador_especificaciones_tecnicas(borrador_id: int | None, nombre_contratacion: str, datos_json: str) -> dict | None:
    """Crea (borrador_id is None) o reemplaza (borrador_id dado) un
    borrador. Siempre manda el registro completo -- no hay actualizacion
    parcial de un borrador, ver BorradorContratacionUpsert."""
    payload = {"nombre_contratacion": nombre_contratacion, "datos_json": datos_json}
    if borrador_id is None:
        response = api_request("POST", "/api/borradores", json=payload)
    else:
        response = api_request("PUT", f"/api/borradores/{borrador_id}", json=payload)
    if response is None:
        return None
    if response.status_code not in (200, 201):
        st.error(f"Error al guardar el progreso: {response.status_code} {response.text}")
        return None
    return response.json()


def eliminar_borrador_especificaciones_tecnicas(borrador_id: int) -> bool:
    response = api_request("DELETE", f"/api/borradores/{borrador_id}")
    if response is None:
        return False
    if response.status_code != 204:
        st.error(f"Error al eliminar la contratación: {response.status_code}")
        return False
    return True


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


CLAVES_FILTRO_DASHBOARD = ["dashboard_anio", "dashboard_mes", "dashboard_provincia"]


def render_filtros_dashboard(df: pd.DataFrame) -> pd.DataFrame:
    """Fila de filtros superiores (Año, Mes, Provincia/Cantón) que acota
    todo lo que se muestra debajo: graficos, tablas y KPIs comparten el
    mismo dataframe filtrado, para que las cifras siempre coincidan. Los
    widgets tienen key propia para que "Limpiar filtros" pueda resetearlos
    de verdad (no solo re-consultar datos), ver CLAVES_FILTRO_DASHBOARD."""
    col1, col2, col3, col4 = st.columns([1, 1, 2, 1])

    if df.empty:
        col1.selectbox("Año", ["(Todos)"], disabled=True)
        col2.selectbox("Mes", ["(Todos)"], disabled=True)
        col3.multiselect("Provincia/Cantón", [], disabled=True, placeholder="Sin datos disponibles")
        return df

    anios_disponibles = sorted(df["anio"].dropna().unique().astype(int), reverse=True)
    anio_sel = col1.selectbox("Año", ["(Todos)"] + [str(a) for a in anios_disponibles], key="dashboard_anio")

    meses_disponibles = sorted(df["mes_num"].dropna().unique().astype(int))
    opciones_mes = ["(Todos)"] + [MESES_ES[m] for m in meses_disponibles]
    mes_sel = col2.selectbox("Mes", opciones_mes, key="dashboard_mes")

    provincias_disponibles = sorted(df["provincia_canton"].dropna().unique())
    provincias_sel = col3.multiselect(
        "Provincia/Cantón",
        provincias_disponibles,
        key="dashboard_provincia",
        placeholder="Selecciona una o más provincias/cantones",
    )

    with col4:
        st.write("")  # alinea verticalmente el boton con los selectbox de arriba
        if st.button(":material/filter_alt_off: Limpiar filtros", key="dashboard_limpiar_filtros", use_container_width=True):
            for clave in CLAVES_FILTRO_DASHBOARD:
                st.session_state.pop(clave, None)
            st.rerun()

    df_filtrado = df
    if anio_sel != "(Todos)":
        df_filtrado = df_filtrado[df_filtrado["anio"] == int(anio_sel)]
    if mes_sel != "(Todos)":
        mes_num = next(k for k, v in MESES_ES.items() if v == mes_sel)
        df_filtrado = df_filtrado[df_filtrado["mes_num"] == mes_num]
    if provincias_sel:
        df_filtrado = df_filtrado[df_filtrado["provincia_canton"].isin(provincias_sel)]

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


def _tarjeta_kpi_html(etiqueta: str, valor: str, ayuda: str | None = None) -> str:
    """Tarjeta KPI en HTML puro (no st.metric): mismo fondo/tipografia/
    bordes en toda la app (Dashboard, Procesos y Municipio de Guayaquil,
    vía render_kpi_card mas abajo), en vez de la mezcla anterior de
    st.metric (texto plano) en unas paginas y esta tarjeta HTML en otras.
    El fondo se fuerza por inline-style con COLOR_LIENZO, igual que
    plot_bgcolor/paper_bgcolor de los graficos, para que ambos recuadros
    hagan juego sin depender del tema claro/oscuro de Streamlit."""
    atributo_titulo = f' title="{html.escape(ayuda)}"' if ayuda else ""
    return f"""
    <div{atributo_titulo} style="background-color:{COLOR_LIENZO};
                border:1px solid {COLOR_NEUTRO_BORDE}; border-radius:8px;
                padding:1.25rem 1.5rem; margin-bottom:0.5rem;">
        <div style="font-size:0.875rem; color:{COLOR_NEUTRO_TEXTO_SUAVE};">
            {etiqueta}
        </div>
        <div style="font-size:2rem; font-weight:600; color:{COLOR_TEXTO_EJE}; line-height:1.3;">
            {valor}
        </div>
    </div>
    """


def render_kpi_card(columna, etiqueta: str, valor: str, ayuda: str | None = None) -> None:
    """Tarjeta KPI reutilizable: mismo componente para Dashboard
    (render_kpis_dashboard), Procesos y Municipio de Guayaquil
    (render_contadores, render_metricas_resumen), en vez de que cada
    pagina eligiera su propio estilo (st.metric vs. tarjeta HTML)."""
    columna.markdown(_tarjeta_kpi_html(etiqueta, valor, ayuda), unsafe_allow_html=True)


def render_kpis_dashboard(df: pd.DataFrame):
    """KPIs principales del Dashboard: Procesos, Presupuesto Total y Valor
    Adjudicado -- lo unico visible por defecto antes de expandir cualquier
    detalle (ver render_pagina_dashboard)."""
    col1, col2, col3 = st.columns(3)
    presupuesto_total = df["presupuesto_referencial"].fillna(0).sum() if not df.empty else 0
    valor_adjudicado_total = (
        df.loc[df["estado"].str.strip().str.lower().str.startswith("adjudicad", na=False), "presupuesto_referencial"]
        .fillna(0)
        .sum()
        if not df.empty
        else 0
    )
    render_kpi_card(col1, "Procesos (filtro actual)", formatear_numero_ec(len(df)))
    render_kpi_card(col2, "Presupuesto Total (filtro actual)", formatear_moneda_ec(presupuesto_total))
    render_kpi_card(
        col3,
        "Valor Adjudicado (filtro actual)",
        formatear_moneda_ec(valor_adjudicado_total),
        ayuda=(
            "Suma del Presupuesto Referencial de los procesos con estado "
            "Adjudicada/Adjudicado dentro del filtro actual."
        ),
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

    fig = px.bar(
        resumen,
        x="anio_mes",
        y="presupuesto_referencial",
        color="anio_mes",
        color_discrete_sequence=PALETA_VIVA,
    )
    fig.update_traces(
        marker=dict(cornerradius=4, line=dict(width=0)),
        hovertemplate="<b>$ %{y:,.2f}</b><br>%{x}<extra></extra>",
    )
    fig.update_xaxes(
        showgrid=False, showline=True, linewidth=2, linecolor=COLOR_AXIS,
        tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=COLOR_GRID, zeroline=False,
        showline=True, linewidth=2, linecolor=COLOR_AXIS,
        tickprefix="$ ", tickformat=",.0f", tickfont=dict(color=COLOR_TEXTO_EJE), title=None,
    )
    _aplicar_estilo_base(fig)
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

    fig = px.bar(
        resumen,
        x="presupuesto_referencial",
        y="provincia_canton",
        orientation="h",
        color="provincia_canton",
        color_discrete_sequence=PALETA_VIVA,
    )
    fig.update_traces(
        marker=dict(cornerradius=4, line=dict(width=0)),
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
        color_continuous_scale="Viridis",
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
        color_continuous_scale="Viridis",
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
    por Provincia/Canton (PALETA_VIVA, la misma paleta viva y ciclica que
    ya usa `render_grafico_provincia`): cada provincia tiene un color
    solido y distintivo, y sus estados hijos heredan ese mismo tono."""
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
        color_discrete_sequence=PALETA_VIVA,
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
        color_discrete_sequence=PALETA_VIVA,
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
        color_discrete_sequence=PALETA_VIVA,
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


def render_metricas_resumen(registros: list[dict]):
    """Tarjetas de resumen sobre los resultados actualmente filtrados. No
    existe en el esquema un campo separado de "valor final adjudicado"
    (solo `presupuesto_referencial`), asi que ese total se calcula como la
    suma del presupuesto referencial de los procesos cuyo estado empieza
    por "Adjudicad..." (ver `ESTADOS`)."""
    presupuesto_total = sum(r.get("presupuesto_referencial") or 0 for r in registros)
    valor_adjudicado_total = sum(
        r.get("presupuesto_referencial") or 0
        for r in registros
        if r.get("estado", "").strip().lower().startswith("adjudicad")
    )

    col1, col2, col3 = st.columns(3)
    render_kpi_card(col1, "Número de Procesos", formatear_numero_ec(len(registros)))
    render_kpi_card(col2, "Presupuesto Total", formatear_moneda_ec(presupuesto_total))
    render_kpi_card(
        col3,
        "Valor Adjudicado Total",
        formatear_moneda_ec(valor_adjudicado_total),
        ayuda=(
            "Suma del Presupuesto Referencial de los procesos con estado "
            "Adjudicada/Adjudicado. No hay un campo separado de valor final "
            "adjudicado en los datos disponibles."
        ),
    )


def render_tabla_con_color(registros: list[dict]):
    if not registros:
        st.info("No hay procesos de contratación para mostrar.")
        return

    df = pd.DataFrame(registros)
    columnas_presentes = [c for c in COLUMNAS_TABLA if c in df.columns]
    df_mostrar = df[columnas_presentes].rename(columns=COLUMNAS_TABLA)

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
        "Objeto del Proceso": st.column_config.TextColumn("Objeto del Proceso", width="medium"),
        "Presupuesto Referencial (sin IVA)": st.column_config.TextColumn(
            "Presupuesto Referencial (sin IVA)", width="medium"
        ),
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
    if st.button(":material/filter_alt_off: Limpiar filtros", key="reportes_limpiar_filtros"):
        for clave in claves_filtro_reportes:
            st.session_state.pop(clave, None)
        st.rerun()

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
                response = api_request(
                    "POST", "/api/generar-reporte", json=payload, timeout=60
                )

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


def render_contadores(registros_totales: list[dict]):
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

    etiquetas = ESTADOS + ["Otros"]
    cols = st.columns(4)
    render_kpi_card(cols[0], "Total", formatear_numero_ec(total))
    for i, estado_categoria in enumerate(etiquetas, start=1):
        etiqueta_mostrar = NOMBRES_ESTADO_COMPLETOS.get(estado_categoria, estado_categoria)
        render_kpi_card(cols[i % 4], etiqueta_mostrar, formatear_numero_ec(conteos[estado_categoria]))


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
            if st.button(":material/delete_forever: Vaciar Base de Datos", use_container_width=True):
                st.session_state.confirmar_vaciado = True
                st.rerun()
        else:
            st.error(
                "Esto eliminará **todos** los procesos de contratación de la base "
                "de datos de forma permanente. Esta acción no se puede deshacer."
            )
            confirmado = st.checkbox("Sí, entiendo y quiero vaciar la base de datos por completo")

            col_confirmar, col_cancelar = st.columns(2)
            if col_confirmar.button(
                ":material/delete_forever: Confirmar vaciado definitivo",
                type="primary",
                disabled=not confirmado,
                use_container_width=True,
            ):
                with st.spinner("Vaciando la base de datos..."):
                    response = api_request("DELETE", "/api/todos")
                if response is None:
                    return
                if response.status_code == 204:
                    st.session_state.confirmar_vaciado = False
                    st.session_state.resultados = None
                    st.session_state.mensaje_vaciado = ":material/check_circle: Base de datos vaciada por completo."
                    st.rerun()
                else:
                    st.error(f"Error al vaciar la base de datos: {response.status_code}")

            if col_cancelar.button("Cancelar", use_container_width=True):
                st.session_state.confirmar_vaciado = False
                st.rerun()

    st.markdown(
        f"""
        <style>
        .st-key-zona_peligro_vaciar_bd {{
            border-color: {COLOR_PELIGRO} !important;
            background-color: {COLOR_PELIGRO_FONDO_SUAVE};
        }}
        .st-key-zona_peligro_vaciar_bd button[kind="primary"] {{
            background-color: {COLOR_PELIGRO} !important;
            border-color: {COLOR_PELIGRO} !important;
            color: #FFFFFF !important;
        }}
        .st-key-zona_peligro_vaciar_bd button[kind="primary"]:hover {{
            background-color: #B91C1C !important;
            border-color: #B91C1C !important;
        }}
        </style>
        """,
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
        </style>
        """,
        unsafe_allow_html=True,
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
                # distorsionado.
                col_icono, col_boton = st.columns([0.7, 4], gap="small", vertical_alignment="center")
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


def render_importacion_sercop_sidebar() -> None:
    """Seccion "Importación SERCOP" del menu lateral: lanza
    scripts/scrape_portal.py (ventana visible de Chromium, CAPTCHA resuelto
    a mano por el usuario -- ver el modelo hibrido local documentado en el
    propio script) en un proceso aparte con subprocess.Popen, para no
    bloquear el hilo principal de Streamlit mientras el usuario completa la
    busqueda en el portal."""
    with st.sidebar:
        st.divider()
        st.caption("IMPORTACIÓN SERCOP")
        if st.button(
            ":material/travel_explore: Importar desde Portal SERCOP",
            key="sercop_importar_boton",
            use_container_width=True,
        ):
            subprocess.Popen([sys.executable, "scripts/scrape_portal.py"])
            st.toast("Se abrió una ventana de Chromium para completar la búsqueda.")


def render_pagina_dashboard(registros_totales: list[dict]) -> None:
    """Revelacion progresiva: por defecto solo se ven los contadores y los
    3 KPIs principales (Procesos, Presupuesto, Adjudicado); el resto del
    detalle (evolucion mensual, provincia, mapa, treemap, tablas resumen)
    queda agrupado en pestañas, para no abrumar con todo el dashboard de
    una sola vez."""
    render_contadores(registros_totales)
    st.divider()
    st.header(":material/analytics: Dashboard Analítico")
    df_totales = preparar_dataframe(registros_totales)
    df_filtrado = render_filtros_dashboard(df_totales)
    render_kpis_dashboard(df_filtrado)

    tab_mensual, tab_provincia, tab_treemap, tab_resumen, tab_presupuesto, tab_gantt = st.tabs(
        [
            ":material/calendar_month: Ver detalle por mes",
            ":material/location_on: Ver detalle por provincia",
            ":material/account_tree: Ver Provincia → Estado",
            ":material/receipt_long: Ver resumen por estado y tipo de compra",
            ":material/payments: Presupuesto por Tipo (Treemap)",
            ":material/timeline: Cronograma de Procesos (Gantt)",
        ]
    )
    with tab_mensual:
        render_grafico_mensual(df_filtrado)
    with tab_provincia:
        render_grafico_provincia(df_filtrado)
        render_mapa_provincias(df_filtrado)
    with tab_treemap:
        render_treemap_provincia_estado(df_filtrado)
    with tab_resumen:
        render_tablas_resumen(df_filtrado)
    with tab_presupuesto:
        render_treemap_presupuesto_tipo(df_filtrado)
    with tab_gantt:
        render_gantt_procesos(df_filtrado)


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
            "Palabra clave", placeholder="Ej: luminarias", key="procesos_palabra_clave"
        )

    col_buscar, col_limpiar, _ = st.columns([1, 1, 4])
    buscar = col_buscar.button(":material/search: Buscar", type="primary", use_container_width=True)
    limpiar = col_limpiar.button(":material/filter_alt_off: Limpiar filtros", use_container_width=True)

    if buscar:
        with st.spinner("Buscando procesos..."):
            st.session_state.resultados = obtener_contrataciones(
                status=None if estado_filtro == "(Todos)" else estado_filtro,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                palabra_clave=palabra_clave_filtro or None,
            )
    if limpiar:
        st.session_state.resultados = None
        for clave in CLAVES_FILTRO_PROCESOS:
            st.session_state.pop(clave, None)
        st.rerun()

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


def _slug_nombre_archivo(texto: str) -> str:
    clave = _normalizar_texto_provincia(texto)  # sin tildes, mayusculas
    slug = re.sub(r"[^A-Za-z0-9]+", "_", clave).strip("_")
    return slug[:80] or "SinTitulo"


COLUMNAS_ITEMS_ESPECIFICACIONES_TECNICAS = [
    "Ítem",
    "Tipo",
    "Descripción",
    "Unidad de Medida",
    "Cantidad Solicitada",
    "Valor Unitario",
    "Valor Total",
    "Descripción CPC",
    "Número CPC",
]


CATALOGO_CPC_PATH = Path(__file__).resolve().parent / "data" / "cpc_n9.csv"


@st.cache_data(ttl=86400, show_spinner=False)
def _cargar_catalogo_cpc() -> dict[str, str]:
    """Catalogo oficial 'Listado de CPC N9' (SERCOP, ~30.000 codigos):
    codigo -> descripcion. Se carga UNA sola vez cada 24h (cache_data con
    ttl=86400 -- el CSV es un catalogo fijo, no cambia entre reruns) y
    se expone como dict, no como DataFrame, para que la busqueda del
    autocompletado sea O(1) por codigo en vez de recorrer/filtrar
    30.000 filas en cada guardado. show_spinner=False porque se llama
    dentro del boton "Guardar Ítems", a mitad de la seccion "Ítems y
    Presupuesto" ya renderizada -- un spinner ahi se veria como un salto
    visual, no como una carga inicial de pagina."""
    df = pd.read_csv(CATALOGO_CPC_PATH, dtype=str)
    return dict(zip(df["codigo_cpc"].str.strip(), df["descripcion_cpc"].str.strip()))


COLUMNAS_VISIBLES_ITEMS_ESPECIFICACIONES_TECNICAS = [
    "Ítem",
    "Tipo",
    "Descripción",
    "Unidad de Medida",
    "Cantidad Solicitada",
    "Valor Unitario",
    "Valor Total",
    "Descripción CPC",
    "Número CPC",
]


def _asignar_fila_ids_especificaciones_tecnicas(df: pd.DataFrame) -> pd.DataFrame:
    """Asigna un '_fila_id' unico y estable (via un contador en
    session_state) a toda fila que todavia no lo tenga -- en la practica,
    las filas nuevas que el usuario acaba de agregar en el data_editor.
    Este id persiste entre guardados y es la clave real para reconocer
    "la misma fila" de un guardado al siguiente: la POSICION (indice) no
    sirve para eso, porque num_rows="dynamic" permite borrar una fila de
    la mitad de la tabla, lo que corre de posicion a todas las filas
    siguientes sin que hayan cambiado en nada."""
    df = df.reset_index(drop=True).copy()
    if "_fila_id" not in df.columns:
        df["_fila_id"] = pd.array([pd.NA] * len(df), dtype="Int64")
    for indice in df.index[df["_fila_id"].isna()]:
        st.session_state.especificaciones_tecnicas_siguiente_fila_id += 1
        df.at[indice, "_fila_id"] = st.session_state.especificaciones_tecnicas_siguiente_fila_id
    return df


def _autocompletar_descripcion_cpc(
    df_nuevo: pd.DataFrame, df_anterior: pd.DataFrame, catalogo: dict[str, str]
) -> tuple[pd.DataFrame, list[str]]:
    """Autocompleta 'Descripción CPC' fila por fila cuando el 'Número CPC'
    de ESA fila (identificada por su '_fila_id' estable, no por su
    posicion -- ver _asignar_fila_ids_especificaciones_tecnicas) cambio respecto al guardado
    anterior, y el codigo se encuentra en el catalogo oficial. Si el
    codigo no cambio, se respeta lo que el usuario haya dejado en
    'Descripción CPC' (no se sobreescribe). Si el codigo cambio pero NO
    esta en el catalogo, tampoco se sobreescribe -- se reporta como no
    encontrado para mostrar una advertencia. df_nuevo debe venir ya
    procesado por _asignar_fila_ids_especificaciones_tecnicas (toda fila, incluidas las
    nuevas, ya tiene un '_fila_id')."""
    df_nuevo = df_nuevo.reset_index(drop=True).copy()
    codigo_previo_por_fila_id: dict[int, str] = {}
    if "_fila_id" in df_anterior.columns and "Número CPC" in df_anterior.columns:
        for _, fila in df_anterior.iterrows():
            fila_id = fila.get("_fila_id")
            if pd.notna(fila_id):
                codigo_previo_por_fila_id[int(fila_id)] = str(fila.get("Número CPC") or "").strip()

    no_encontrados = []
    for indice, fila in df_nuevo.iterrows():
        codigo_nuevo = str(fila.get("Número CPC") or "").strip()
        if not codigo_nuevo:
            continue
        fila_id = fila.get("_fila_id")
        codigo_previo = codigo_previo_por_fila_id.get(int(fila_id), "") if pd.notna(fila_id) else ""
        if codigo_nuevo == codigo_previo:
            continue
        if codigo_nuevo in catalogo:
            df_nuevo.at[indice, "Descripción CPC"] = catalogo[codigo_nuevo]
        else:
            no_encontrados.append(codigo_nuevo)
    return df_nuevo, no_encontrados


def _dataframe_items_especificaciones_tecnicas_vacio() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Ítem": pd.Series(dtype="Int64"),
            "Tipo": pd.Series(dtype="str"),
            "Descripción": pd.Series(dtype="str"),
            "Unidad de Medida": pd.Series(dtype="str"),
            "Cantidad Solicitada": pd.Series(dtype="float"),
            "Valor Unitario": pd.Series(dtype="float"),
            "Valor Total": pd.Series(dtype="float"),
            "Descripción CPC": pd.Series(dtype="str"),
            "Número CPC": pd.Series(dtype="str"),
            "_fila_id": pd.Series(dtype="Int64"),
        }
    )


def _dataframe_cpc_especificaciones_tecnicas_vacio() -> pd.DataFrame:
    return pd.DataFrame({"Código CPC": pd.Series(dtype="str"), "Descripción del CPC": pd.Series(dtype="str")})


@st.cache_data(show_spinner=False)
def _recalcular_items_especificaciones_tecnicas(df: pd.DataFrame) -> pd.DataFrame:
    """Recalcula Item # (posicion) y Valor Total = Cantidad Solicitada *
    Valor Unitario tras cada edicion -- ninguna de las dos columnas es
    editable directamente por el usuario (ver column_config en
    render_formularios_y_registro). "Tipo" tambien se rellena con "Bien"
    por defecto para filas nuevas (el selector Bien/Servicio es POR
    ITEM, via SelectboxColumn, no un unico selector global).

    Cacheada (@st.cache_data): funcion pura (mismo df de entrada ->
    mismo resultado) llamada varias veces por rerun (vista previa,
    seccion "Ítems y Presupuesto", Word) sobre el mismo
    session_state.especificaciones_tecnicas_items_df -- sin cache se
    recalcularia identico varias veces por script run."""
    df = df.reset_index(drop=True).copy()
    df["Ítem"] = df.index + 1
    if "Tipo" not in df.columns:
        df["Tipo"] = "Bien"
    df["Tipo"] = df["Tipo"].fillna("Bien")
    cantidad = pd.to_numeric(df["Cantidad Solicitada"], errors="coerce").fillna(0)
    valor_unitario = pd.to_numeric(df["Valor Unitario"], errors="coerce").fillna(0)
    df["Valor Total"] = (cantidad * valor_unitario).round(2)
    return df


@st.cache_data(show_spinner=False)
def _sumar_valor_total_items_especificaciones_tecnicas(df_items: pd.DataFrame) -> float:
    """Suma la columna "Valor Total" (ya recalculada por
    _recalcular_items_especificaciones_tecnicas) de todos los items de Especificaciones Técnicas. Es la unica
    fuente de la Sumatoria Total Y del Presupuesto Referencial (bloqueado),
    ambos mostrados en la seccion "Ítems y Presupuesto" -- ambos leen de
    aqui para no poder desincronizarse.

    Cacheada (@st.cache_data): funcion pura, misma razon que
    _recalcular_items_especificaciones_tecnicas -- se llama varias veces por rerun
    (Sumatoria Total, Presupuesto Referencial autocompletado, Word/Vista
    Previa) sobre el mismo dataframe."""
    if df_items.empty or "Valor Total" not in df_items.columns:
        return 0.0
    return float(df_items["Valor Total"].sum())


def _formatear_numero_especificaciones_tecnicas(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return formatear_numero_ec(valor)


def _formatear_moneda_especificaciones_tecnicas(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return formatear_numero_ec(valor, decimales=2)


def _specs_vacias_especificaciones_tecnicas(tipo: str) -> dict:
    if tipo == "Servicio":
        return {
            "procedimiento": "",
            "herramientas_equipo": "",
            "normas_aplicables": "",
            "medicion": "",
            "forma_pago": "",
            "obligaciones": "",
        }
    return {"subtitulo_specs": "MODELO DE EJEMPLO", "descripcion_material": "", "parametros": []}


def _celda_parametro_a_texto(valor) -> str:
    """Normaliza una celda de pandas (NaN, float, str con saltos de linea
    embebidos, etc.) al texto que se guarda en un parametro. Los saltos de
    linea dentro de la celda (ej. una lista de viñetas pegada en Excel) se
    preservan tal cual -- se muestran despues en un st.text_area, no en un
    text_input de una sola linea."""
    if pd.isna(valor):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).lstrip("﻿").strip()


def _parsear_texto_parametros_manual(texto: str, separador: str) -> pd.DataFrame:
    """Reconstruye a mano (sin pd.read_csv) una tabla de 2 columnas
    (Parametro, Valor) a partir del texto crudo de un .csv/.txt.

    Los archivos reales de este flujo traen descripciones multilinea (ej.
    una lista numerada del 1 al 9) SIN encerrarlas entre comillas -- para
    un parser de CSV eso son lineas con menos campos de los que espera,
    y pd.read_csv (con el engine C o el python) revienta con "Error
    tokenizing data. C error: Expected N fields, saw M". Aqui, en cambio,
    cada linea se procesa por su cuenta: si trae el separador es una fila
    nueva (Parametro/Valor); si no lo trae y no esta vacia, se asume que
    es la continuacion del Valor de la ULTIMA fila ya registrada y se le
    concatena con un "\n" (una linea vacia no continua ni corta nada, se
    ignora)."""
    filas: list[list[str]] = []
    for linea in texto.splitlines():
        if separador in linea:
            nombre, valor = linea.split(separador, 1)
            filas.append([nombre.strip(), valor.strip()])
        elif linea.strip() and filas:
            filas[-1][1] = f"{filas[-1][1]}\n{linea.strip()}"
        # una linea sin separador y sin ninguna fila previa (o vacia) no
        # tiene donde continuar: se descarta sin romper el resto.
    return pd.DataFrame(filas, columns=["Parámetro", "Valor"])


def _leer_parametros_desde_archivo(archivo_subido) -> list[dict]:
    """Lee un archivo .xlsx/.csv/.txt subido por el usuario y lo convierte
    en una lista de {"nombre": ..., "valor": ...} listos para anexarse a
    los parametros de un item. Solo usa las primeras 2 columnas del
    archivo (columna 0 = Parametro, columna 1 = Valor/Descripcion) y
    descarta filas sin nombre de parametro.

    Lanza ValueError con un mensaje apto para mostrar en st.error si el
    archivo no se puede leer o no tiene al menos 2 columnas."""
    nombre_archivo = (archivo_subido.name or "").lower()
    try:
        if nombre_archivo.endswith(".xlsx"):
            df = pd.read_excel(archivo_subido)
        else:
            # .csv/.txt: separador segun el tipo de archivo (tab en .txt,
            # ";" en .csv -- el que usa Excel en configuracion regional
            # Ecuador/es-ES al exportar, ya que "," esta reservado como
            # separador decimal). Se procesa a mano (ver
            # _parsear_texto_parametros_manual) en vez de pd.read_csv,
            # porque las descripciones multilinea sin comillas de estos
            # archivos rompen el parser de pandas.
            separador = "\t" if nombre_archivo.endswith(".txt") else ";"
            archivo_subido.seek(0)
            crudo = archivo_subido.read()
            try:
                texto = crudo.decode("utf-8-sig")
            except UnicodeDecodeError:
                texto = crudo.decode("utf-8", errors="ignore")
            df = _parsear_texto_parametros_manual(texto, separador)
    except Exception as exc:
        raise ValueError(f"No se pudo leer el archivo: {exc}") from exc

    if df.shape[1] < 2:
        raise ValueError("El archivo debe tener al menos 2 columnas (Parámetro y Valor/Descripción).")

    # Purifica el dataframe ANTES del bucle de inyeccion: las celdas
    # vacias de la 2da columna llegan como NaN, y sin este fillna("") se
    # terminaria inyectando el string "nan" en vez de un campo vacio.
    df = df.fillna("")

    df_columnas = df.iloc[:, :2]
    parametros = []
    for _, fila in df_columnas.iterrows():
        nombre = _celda_parametro_a_texto(fila.iloc[0])
        if not nombre:
            continue
        parametros.append({"nombre": nombre, "valor": _celda_parametro_a_texto(fila.iloc[1])})

    if not parametros:
        raise ValueError("El archivo no tiene filas válidas (la columna Parámetro está vacía).")
    return parametros


def _recolectar_datos_especificaciones_tecnicas() -> dict:
    """Arma el mismo diccionario `datos` que consume generar_especificaciones_tecnicas(), a
    partir de TODO lo que el usuario ya cargo en session_state. Se usa
    tanto para el boton de descarga en Word como para la Vista Previa,
    para garantizar que ambos muestren exactamente lo mismo."""
    df_items = _recalcular_items_especificaciones_tecnicas(st.session_state.especificaciones_tecnicas_items_df)
    specs = st.session_state.especificaciones_tecnicas_specs
    items_datos = []
    for indice, fila in df_items.reset_index(drop=True).iterrows():
        tipo_fila = fila.get("Tipo") or "Bien"
        item = {
            "tipo": tipo_fila,
            "descripcion": str(fila.get("Descripción") or ""),
            "unidad_medida": str(fila.get("Unidad de Medida") or ""),
            "cantidad_solicitada": _formatear_numero_especificaciones_tecnicas(fila.get("Cantidad Solicitada")),
            "valor_unitario": _formatear_moneda_especificaciones_tecnicas(fila.get("Valor Unitario")),
            "valor_total": _formatear_moneda_especificaciones_tecnicas(fila.get("Valor Total")),
            "descripcion_cpc": str(fila.get("Descripción CPC") or ""),
            "numero_cpc": str(fila.get("Número CPC") or ""),
        }
        spec = specs[indice] if indice < len(specs) else _specs_vacias_especificaciones_tecnicas(tipo_fila)
        item.update(spec)
        items_datos.append(item)

    df_cpc = st.session_state.especificaciones_tecnicas_cpc_df
    requerimientos_cpc = [
        {"cpc": str(fila.get("Código CPC") or ""), "descripcion": str(fila.get("Descripción del CPC") or "")}
        for _, fila in df_cpc.iterrows()
    ]

    return {
        "objeto_contratacion": st.session_state.get("especificaciones_tecnicas_objeto_contratacion", ""),
        "items": items_datos,
        # No se lee de session_state["especificaciones_tecnicas_presupuesto"]: ese campo ahora
        # es de solo lectura y se autocompleta con esta misma suma (ver
        # seccion "Ítems y Presupuesto"), pero calcularlo aqui de nuevo
        # evita depender de que esa seccion ya se haya renderizado en esta
        # sesion -- el Word/Vista Previa siempre reflejan la suma actual
        # de los items, se haya visitado esa seccion o no.
        "presupuesto_referencial": formatear_moneda_ec(_sumar_valor_total_items_especificaciones_tecnicas(df_items)),
        "requerimientos_cpc": requerimientos_cpc,
        "codigo_cpc_mayor_peso": st.session_state.get("especificaciones_tecnicas_codigo_cpc_mayor_peso", ""),
        "alcance": st.session_state.get("especificaciones_tecnicas_alcance", ""),
        "plazo_ejecucion": st.session_state.get("especificaciones_tecnicas_plazo", ""),
        "personal_tecnico_principal": st.session_state.get("especificaciones_tecnicas_personal_tecnico_principal", ""),
        "personal_tecnico_auxiliar": st.session_state.get("especificaciones_tecnicas_personal_tecnico_auxiliar", ""),
        "equipo_trabajo": st.session_state.get("especificaciones_tecnicas_equipo_trabajo", ""),
        "recursos": st.session_state.get("especificaciones_tecnicas_recursos", ""),
        "forma_condiciones_pago": st.session_state.get("especificaciones_tecnicas_forma_pago", ""),
        "lugar_direccion": st.session_state.get("especificaciones_tecnicas_lugar", ""),
        "obligaciones_entidad": st.session_state.get("especificaciones_tecnicas_obligaciones_entidad", ""),
        "obligaciones_contratista": st.session_state.get("especificaciones_tecnicas_obligaciones_contratista", ""),
        "garantias_tecnicas": st.session_state.get("especificaciones_tecnicas_garantias_tecnicas", ""),
        "monto_garantia_responsabilidad_civil": _formatear_moneda_especificaciones_tecnicas(
            st.session_state.get("especificaciones_tecnicas_monto_garantia_rc")
        ),
        "vigencia_oferta_dias": _formatear_numero_especificaciones_tecnicas(st.session_state.get("especificaciones_tecnicas_vigencia_oferta")),
        "tipo_adjudicacion": st.session_state.get("especificaciones_tecnicas_tipo_adjudicacion", ""),
        "analisis_estrategia_html": st.session_state.get("especificaciones_tecnicas_analisis_estrategia_html", ""),
        "administrador_nombre": st.session_state.get("especificaciones_tecnicas_admin_nombre", ""),
        "administrador_cargo": st.session_state.get("especificaciones_tecnicas_admin_cargo", ""),
        "administrador_cedula": st.session_state.get("especificaciones_tecnicas_admin_cedula", ""),
        "tecnico_no_interviene_nombre": st.session_state.get("especificaciones_tecnicas_tecnico_nombre", ""),
        "tecnico_no_interviene_cargo": st.session_state.get("especificaciones_tecnicas_tecnico_cargo", ""),
        "tecnico_no_interviene_correo": st.session_state.get("especificaciones_tecnicas_tecnico_correo", ""),
        "direccion_contacto": st.session_state.get("especificaciones_tecnicas_direccion_contacto", ""),
        "telefono_contacto": st.session_state.get("especificaciones_tecnicas_telefono_contacto", ""),
        "proceso_contratacion_aplicar": st.session_state.get("especificaciones_tecnicas_proceso_aplicar", ""),
        "pct_experiencia_general": _formatear_numero_especificaciones_tecnicas(st.session_state.get("especificaciones_tecnicas_pct_general")),
        "pct_experiencia_especifica": _formatear_numero_especificaciones_tecnicas(st.session_state.get("especificaciones_tecnicas_pct_especifica")),
        "titulo_profesional_personal_tecnico": st.session_state.get("especificaciones_tecnicas_titulo_profesional", ""),
        "equipo_trabajo_recursos_evaluar": st.session_state.get("especificaciones_tecnicas_equipo_evaluar", ""),
        "certificado_proveedor_exclusivo": st.session_state.get("especificaciones_tecnicas_certificado_proveedor", "No"),
        "patrimonio_aplica": st.session_state.get("especificaciones_tecnicas_patrimonio_aplica", "No"),
        "evaluacion_estrategia_adquisicion": st.session_state.get("especificaciones_tecnicas_evaluacion_estrategia", ""),
        "otros_parametros_evaluacion": st.session_state.get("especificaciones_tecnicas_otros_parametros", ""),
        "fecha_documento": st.session_state.get("especificaciones_tecnicas_fecha", ""),
        "firmas": {
            "elaborado": {
                "nombre": st.session_state.get("especificaciones_tecnicas_firma_elaborado_nombre", ""),
                "cargo": st.session_state.get("especificaciones_tecnicas_firma_elaborado_cargo", ""),
                "firmado_por": st.session_state.get("especificaciones_tecnicas_firma_elaborado_firmado", ""),
            },
            "revisado": {
                "nombre": st.session_state.get("especificaciones_tecnicas_firma_revisado_nombre", ""),
                "cargo": st.session_state.get("especificaciones_tecnicas_firma_revisado_cargo", ""),
                "firmado_por": st.session_state.get("especificaciones_tecnicas_firma_revisado_firmado", ""),
            },
            "aprobado": {
                "nombre": st.session_state.get("especificaciones_tecnicas_firma_aprobado_nombre") or FIRMA_APROBADO_POR_DEFECTO_NOMBRE,
                "cargo": st.session_state.get("especificaciones_tecnicas_firma_aprobado_cargo") or FIRMA_APROBADO_POR_DEFECTO_CARGO,
                "firmado_por": st.session_state.get("especificaciones_tecnicas_firma_aprobado_firmado", ""),
            },
        },
    }


# --- Vista previa HTML (pestaña 5): UNA sola tabla continua con los
# mismos bordes azul marino institucionales (COLOR_BORDE_TABLA_ITEMS) y
# la misma estructura fila por fila que la tabla continua real de
# scripts/especificaciones_tecnicas_generator.py -- confirmado contra el .docx del modelo
# oficial de referencia (solo "REQUERIMIENTOS ADICIONALES OBLIGATORIOS" y
# "PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN" son titulos de ancho completo
# reales; todo lo demas es una fila de campo etiqueta+valor). Reutiliza
# los mismos textos fijos que el generador para que la previsualizacion y
# el .docx final coincidan siempre. FECHA y FIRMAS DE RESPONSABILIDAD no
# existen en el modelo de referencia y por eso se muestran aparte, fuera
# de la tabla continua, igual que en el generador. ---
_VACIO = '<span style="background:#fff59d; padding:0 2px;">&nbsp;</span>'
_BORDE = f"1px solid #{COLOR_BORDE_TABLA_ITEMS}"


def _html_valor_o_vacio(valor: str) -> str:
    return html.escape(valor) if valor else _VACIO


_PATRON_ETIQUETAS_PELIGROSAS = re.compile(
    r"<\s*(script|style|iframe|object|embed)\b.*?>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL
)


def _sanitizar_html_enriquecido(html_enriquecido: str) -> str:
    """El HTML del editor TinyMCE (pestaña 'Análisis para definir la
    estrategia de adquisición') se inserta con unsafe_allow_html=True en
    la Vista Previa -- se quitan aquí, por precaución, las etiquetas que
    podrían ejecutar código o cargar contenido externo, aunque TinyMCE ya
    no las genera desde su propia interfaz."""
    return _PATRON_ETIQUETAS_PELIGROSAS.sub("", html_enriquecido)


def _html_fila_campo(etiqueta: str, valor: str) -> str:
    """Fila de campo editable por el usuario: etiqueta centrada (~33%
    del ancho, misma proporcion que en el .docx) + valor resaltado en
    amarillo si esta vacio."""
    return (
        "<tr>"
        f'<td style="border:{_BORDE}; padding:5px 8px; width:33%; text-align:center; vertical-align:middle;">'
        f"{html.escape(etiqueta)}</td>"
        f'<td style="border:{_BORDE}; padding:5px 8px; text-align:justify; vertical-align:middle;">'
        f"{_html_valor_o_vacio(valor)}</td>"
        "</tr>"
    )


def _html_fila_campo_fijo(etiqueta: str, contenido_html: str) -> str:
    """Como _html_fila_campo, pero el valor es contenido fijo ya armado
    en HTML (texto institucional, listas, subtablas), sin resaltado."""
    return (
        "<tr>"
        f'<td style="border:{_BORDE}; padding:5px 8px; width:33%; text-align:center; vertical-align:middle;">'
        f"{html.escape(etiqueta)}</td>"
        f'<td style="border:{_BORDE}; padding:5px 8px; text-align:justify; vertical-align:top;">'
        f"{contenido_html}</td>"
        "</tr>"
    )


def _html_titulo_ancho(texto: str) -> str:
    """Uno de los 2 unicos titulos de seccion de ancho completo reales
    del modelo: centrado, negrita, sin relleno de color."""
    return (
        '<tr><td colspan="2" style='
        f'"border:{_BORDE}; padding:6px 8px; text-align:center; font-weight:bold; font-size:16px;">'
        f"{html.escape(texto)}</td></tr>"
    )


def _html_fila_ancho_parrafo(contenido_html: str) -> str:
    """Fila de ancho completo sin etiqueta (parrafo introductorio suelto,
    o una subtabla como la lista de CPC)."""
    return f'<tr><td colspan="2" style="border:{_BORDE}; padding:5px 8px;">{contenido_html}</td></tr>'


def _html_parrafos(texto: str) -> str:
    return "".join(
        f'<p style="margin:3px 0; text-align:justify;">{html.escape(linea)}</p>' for linea in texto.split("\n")
    )


def _html_lista_numerada(items: list[str]) -> str:
    """Cursiva, igual que el modelo real (atribuciones del administrador)."""
    return "".join(
        f'<p style="margin:2px 0; text-align:justify; font-size:12px; font-style:italic;">'
        f"{numero}. {html.escape(texto)}</p>"
        for numero, texto in enumerate(items, start=1)
    )


def _html_lista_vinetas(items: list[str]) -> str:
    """Cursiva, igual que el modelo real (obligaciones adicionales)."""
    return "".join(
        f'<p style="margin:2px 0; text-align:justify; font-size:12px; font-style:italic;">'
        f"● {html.escape(texto)}</p>"
        for texto in items
    )


def _html_tabla(encabezados: list[str], filas: list[list[str]]) -> str:
    ths = "".join(
        f'<th style="border:{_BORDE}; padding:3px; background:#f2f2f2; font-size:11px;">{html.escape(h)}</th>'
        for h in encabezados
    )
    trs = "".join(
        "<tr>"
        + "".join(f'<td style="border:{_BORDE}; padding:3px; font-size:11px;">{html.escape(str(v))}</td>' for v in fila)
        + "</tr>"
        for fila in filas
    )
    return f'<table style="width:100%; border-collapse:collapse; margin:4px 0;"><tr>{ths}</tr>{trs}</table>'


def _html_filas_item(numero: int, item: dict) -> str:
    """Filas (no tabla aparte) de un item: encabezado de 8 columnas, fila
    de datos, fila divisora PARAMETROS/ESPECIFICACIONES TECNICAS, fila de
    especificaciones y una fila vacia de separacion -- se insertan
    directamente en la tabla continua, igual que en el modelo real."""
    encabezados = [
        "ITEM", "DESCRIPCIÓN", "Unidad de Medida", "Cantidad Solicitada",
        "Valor Unitario", "Valor Total", "Descripción del CPC", "NÚMERO DE CPC",
    ]
    valores = [
        str(numero), item.get("descripcion", ""), item.get("unidad_medida", ""),
        item.get("cantidad_solicitada", ""), item.get("valor_unitario", ""),
        item.get("valor_total", ""), item.get("descripcion_cpc", ""), item.get("numero_cpc", ""),
    ]
    fila_encabezado = "".join(
        f'<th style="border:{_BORDE}; padding:2px; background:#f2f2f2; font-size:10px;">{html.escape(h)}</th>'
        for h in encabezados
    )
    fila_datos = "".join(
        f'<td style="border:{_BORDE}; padding:2px; font-size:10px; text-align:center;">'
        f'{_html_valor_o_vacio(str(v)) if not v else html.escape(str(v))}</td>'
        for v in valores
    )

    if item.get("tipo") == "Servicio":
        etiqueta_label = "DESCRIPCIÓN<br>SERVICIO"
        bloques = []
        for etiqueta, clave in (
            ("PROCEDIMIENTO (Desmontaje/Montaje)", "procedimiento"),
            ("HERRAMIENTAS/EQUIPO", "herramientas_equipo"),
            ("NORMAS", "normas_aplicables"),
            ("MEDICIÓN", "medicion"),
            ("FORMA DE PAGO", "forma_pago"),
            ("OBLIGACIONES", "obligaciones"),
        ):
            bloques.append(
                f'<p style="margin:2px 0; font-size:11px;"><b>{etiqueta}:</b> '
                f'{_html_valor_o_vacio(item.get(clave, ""))}</p>'
            )
        contenido_specs = "".join(bloques)
    else:
        etiqueta_label = "DESCRIPCIÓN<br>MATERIAL"
        subtitulo = item.get("subtitulo_specs") or "MODELO DE EJEMPLO"
        contenido_specs = (
            f'<p style="margin:2px 0;"><span style="background:#8BC34A; padding:0 2px;">'
            f'{html.escape(subtitulo)}</span></p>'
        )
        if item.get("descripcion_material"):
            contenido_specs += f'<p style="margin:2px 0; font-size:11px;">{html.escape(item["descripcion_material"])}</p>'
        parametros = item.get("parametros") or []
        if parametros:
            filas_parametros = "".join(
                f'<tr><td style="border:{_BORDE}; padding:2px; font-weight:bold; font-size:10px;">'
                f'{html.escape(p.get("nombre",""))}</td>'
                f'<td style="border:{_BORDE}; padding:2px; font-size:10px;">{html.escape(p.get("valor",""))}</td></tr>'
                for p in parametros
            )
            contenido_specs += f'<table style="width:100%; border-collapse:collapse;">{filas_parametros}</table>'

    return (
        f"<tr>{fila_encabezado}</tr>"
        f"<tr>{fila_datos}</tr>"
        "<tr>"
        f'<td style="border:{_BORDE}; padding:3px; font-weight:bold; text-align:center; font-size:11px;">PARÁMETROS</td>'
        f'<td colspan="7" style="border:{_BORDE}; padding:3px; font-weight:bold; text-align:center; font-size:11px;">'
        "ESPECIFICACIONES TÉCNICAS</td>"
        "</tr>"
        "<tr>"
        f'<td style="border:{_BORDE}; padding:3px; font-weight:bold; text-align:center; font-size:11px;">{etiqueta_label}</td>'
        f'<td colspan="7" style="border:{_BORDE}; padding:5px; vertical-align:top;">{contenido_specs}</td>'
        "</tr>"
        f'<tr><td colspan="8" style="border:{_BORDE}; padding:8px;"></td></tr>'
    )


@st.cache_data(ttl=86400, show_spinner=False)
def _imagenes_especificaciones_tecnicas_base64() -> tuple[str, str]:
    """Encabezado/pie institucionales: archivos de imagen fijos en disco
    (IMAGEN_ENCABEZADO/IMAGEN_PIE_PAGINA), mismo criterio de ttl=86400 que
    _cargar_catalogo_cpc y cargar_geojson_provincias. show_spinner=False
    porque se llama dentro de la pestaña "Generación y Vista Previa"."""
    return (
        base64.b64encode(IMAGEN_ENCABEZADO.read_bytes()).decode(),
        base64.b64encode(IMAGEN_PIE_PAGINA.read_bytes()).decode(),
    )


def _render_vista_previa_especificaciones_tecnicas(datos: dict) -> None:
    encabezado_b64, pie_b64 = _imagenes_especificaciones_tecnicas_base64()

    partes = [
        '<div style="background:white; color:#111; padding:20px; border:1px solid #ccc; '
        'font-family: Arial, sans-serif; max-height:75vh; overflow-y:auto;">',
        f'<img src="data:image/jpeg;base64,{encabezado_b64}" style="width:100%; margin-bottom:10px;">',
        '<table style="width:100%; border-collapse:collapse; text-align:center; font-weight:bold; margin-bottom:14px;">',
        f'<tr><td style="border:{_BORDE}; padding:6px;">{html.escape(TITULO_PROCESO_FIJO)}</td></tr>',
        f'<tr><td style="border:{_BORDE}; padding:6px;">{html.escape(COORDINACION_FIJA)}</td></tr>',
        f'<tr><td style="border:{_BORDE}; padding:8px; background:#fff59d;">'
        f'{_html_valor_o_vacio(datos.get("objeto_contratacion", ""))}</td></tr>',
        "</table>",
        '<table style="width:100%; border-collapse:collapse; font-size:12px;">',
    ]

    items = datos.get("items", [])
    if not items:
        partes.append(
            '<tr><td colspan="2" style="padding:6px; color:#999;">'
            '(sin ítems agregados todavía en la sección "Ítems y Presupuesto")</td></tr>'
        )
    for numero, item in enumerate(items, start=1):
        partes.append(_html_filas_item(numero, item))

    partes.append(_html_fila_campo("PRESUPUESTO REFERENCIAL", datos.get("presupuesto_referencial", "")))

    partes.append(_html_titulo_ancho("REQUERIMIENTOS ADICIONALES OBLIGATORIOS"))
    requerimientos = datos.get("requerimientos_cpc") or [{"cpc": "", "descripcion": ""}]
    partes.append(
        _html_fila_ancho_parrafo(
            _html_tabla(
                ["CPC", "DESCRIPCIÓN DEL CPC"],
                [[r.get("cpc") or "", r.get("descripcion") or ""] for r in requerimientos],
            )
        )
    )

    partes.append(
        _html_fila_campo(
            "CÓDIGO CPC (DETALLAR EL CÓDIGO Y LA DESCRIPCIÓN DEL DE MAYOR PESO ECONÓMICO DE LA CONTRATACIÓN)",
            datos.get("codigo_cpc_mayor_peso", ""),
        )
    )
    partes.append(_html_fila_campo("ALCANCE", datos.get("alcance", "")))
    partes.append(
        _html_fila_campo("PLAZO DE EJECUCIÓN: PARCIALES Y/O TOTAL (EN DÍAS)", datos.get("plazo_ejecucion", ""))
    )

    partes.append(_html_fila_campo("1.- PERSONAL TÉCNICO PRINCIPAL", datos.get("personal_tecnico_principal", "")))
    partes.append(
        _html_fila_campo(
            "2.- PERSONAL TÉCNICO AUXILIAR O SECUNDARIO", datos.get("personal_tecnico_auxiliar", "")
        )
    )
    partes.append(_html_fila_campo("3.- EQUIPO DE TRABAJO", datos.get("equipo_trabajo", "")))
    partes.append(_html_fila_campo("4.- RECURSOS", datos.get("recursos", "")))

    partes.append(_html_fila_campo("FORMA Y CONDICIONES DE PAGO", datos.get("forma_condiciones_pago", "")))
    partes.append(
        _html_fila_campo("LUGAR Y DIRECCIÓN DE ENTREGA/EJECUCIÓN", datos.get("lugar_direccion", ""))
    )

    partes.append(_html_fila_campo_fijo("MULTAS", _html_parrafos(TEXTO_MULTAS)))

    partes.append(
        _html_fila_campo("i) OBLIGACIONES DE LA ENTIDAD CONTRATANTE", datos.get("obligaciones_entidad", ""))
    )
    partes.append(
        _html_fila_campo("ii) OBLIGACIONES DE LA CONTRATISTA", datos.get("obligaciones_contratista", ""))
    )

    partes.append(
        _html_fila_campo("GARANTÍAS TÉCNICAS, EN EL CASO DE QUE APLIQUE", datos.get("garantias_tecnicas", ""))
    )

    texto_responsabilidad_civil = TEXTO_GARANTIA_RESPONSABILIDAD_CIVIL_PLANTILLA.format(
        objeto=datos.get("objeto_contratacion", "") or "",
        monto=datos.get("monto_garantia_responsabilidad_civil", "") or "",
    )
    partes.append(
        _html_fila_campo_fijo(
            "GARANTÍAS ADICIONALES, EN EL CASO DE QUE APLIQUE",
            _html_parrafos(TEXTO_GARANTIA_FIEL_CUMPLIMIENTO)
            + _html_parrafos(TEXTO_GARANTIA_BUEN_USO_ANTICIPO)
            + _html_parrafos(texto_responsabilidad_civil),
        )
    )

    partes.append(
        _html_fila_campo_fijo(
            "VIGENCIA DE LA OFERTA",
            _html_parrafos(
                TEXTO_VIGENCIA_OFERTA_PLANTILLA.format(dias=datos.get("vigencia_oferta_dias", "") or "")
            ),
        )
    )
    partes.append(_html_fila_campo_fijo("REAJUSTE DE PRECIOS", _html_parrafos(TEXTO_REAJUSTE_PRECIOS)))
    partes.append(_html_fila_campo("TIPO DE ADJUDICACIÓN", datos.get("tipo_adjudicacion", "")))

    contenido_administrador = _html_parrafos(
        TEXTO_ADMINISTRADOR_INTRO_PLANTILLA.format(
            nombre=datos.get("administrador_nombre", "") or "",
            cedula=datos.get("administrador_cedula", "") or "",
            cargo=datos.get("administrador_cargo", "") or "",
        )
    )
    contenido_administrador += _html_lista_numerada(TEXTO_ATRIBUCIONES_ADMINISTRADOR)
    contenido_administrador += _html_parrafos(TEXTO_ADMINISTRADOR_OBLIGACIONES_INTRO)
    contenido_administrador += _html_lista_vinetas(TEXTO_ADMINISTRADOR_OBLIGACIONES_ADICIONALES)
    contenido_administrador += _html_parrafos(TEXTO_ADMINISTRADOR_CIERRE)
    partes.append(_html_fila_campo_fijo("ADMINISTRADOR DEL CONTRATO", contenido_administrador))

    contenido_tecnico = "".join(
        f'<p style="margin:2px 0; font-size:11px;"><b>{etiqueta}:</b> {_html_valor_o_vacio(valor)}</p>'
        for etiqueta, valor in (
            ("Funcionario", datos.get("tecnico_no_interviene_nombre", "")),
            ("Cargo", datos.get("tecnico_no_interviene_cargo", "")),
            ("Mail", datos.get("tecnico_no_interviene_correo", "")),
            ("Dirección", datos.get("direccion_contacto", "")),
            ("Teléfono", datos.get("telefono_contacto", "")),
        )
    )
    partes.append(_html_fila_campo_fijo("TÉCNICO QUE NO INTERVIENE EN LA CONTRATACIÓN", contenido_tecnico))

    contenido_estrategia = _html_parrafos(TEXTO_ANALISIS_ESTRATEGIA_FIJO)
    html_analisis = (datos.get("analisis_estrategia_html", "") or "").strip()
    contenido_estrategia += '<p style="margin:4px 0 2px; font-size:11px;"><b>Análisis específico de la contratación:</b></p>'
    contenido_estrategia += (
        f'<div style="font-size:11px;">{_sanitizar_html_enriquecido(html_analisis)}</div>'
        if html_analisis
        else f'<p style="font-size:11px;">{_VACIO}</p>'
    )
    partes.append(_html_fila_campo_fijo("ANÁLISIS PARA DEFINIR LA ESTRATÉGIA DE ADQUISICIÓN", contenido_estrategia))
    partes.append(
        _html_fila_campo("PROCESO DE CONTRATACIÓN A APLICAR", datos.get("proceso_contratacion_aplicar", ""))
    )

    partes.append(_html_titulo_ancho("PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN"))
    partes.append(_html_fila_ancho_parrafo(_html_parrafos(TEXTO_PARAMETROS_EVALUACION_INTRO)))

    partes.append(
        _html_fila_campo_fijo(
            "EXPERIENCIA GENERAL DEL OFERENTE",
            _html_parrafos(
                TEXTO_EXPERIENCIA_GENERAL_PLANTILLA.format(
                    pct_general=datos.get("pct_experiencia_general", "") or ""
                )
            ),
        )
    )
    partes.append(
        _html_fila_campo_fijo(
            "EXPERIENCIA ESPECÍFICA DEL OFERENTE",
            _html_parrafos(
                TEXTO_EXPERIENCIA_ESPECIFICA_PLANTILLA.format(
                    pct_especifica=datos.get("pct_experiencia_especifica", "") or ""
                )
            ),
        )
    )
    partes.append(
        _html_fila_campo_fijo(
            "FORMACIÓN DEL PERSONAL TÉCNICO",
            _html_parrafos(
                TEXTO_FORMACION_PERSONAL_TECNICO_PLANTILLA.format(
                    titulo_profesional=datos.get("titulo_profesional_personal_tecnico", "") or ""
                )
            ),
        )
    )
    partes.append(
        _html_fila_campo_fijo(
            "EXPERIENCIA DEL PERSONAL TÉCNICO", _html_parrafos(TEXTO_EXPERIENCIA_PERSONAL_TECNICO)
        )
    )
    partes.append(
        _html_fila_campo(
            "EQUIPO DE TRABAJO/RECURSOS A EVALUAR", datos.get("equipo_trabajo_recursos_evaluar", "")
        )
    )

    contenido_certificado = _html_parrafos(TEXTO_CERTIFICADO_PROVEEDOR_EXCLUSIVO_INTRO)
    contenido_certificado += (
        f'<p style="margin:4px 0 2px; font-size:11px;"><b>¿Aplica?:</b> '
        f'{_html_valor_o_vacio(datos.get("certificado_proveedor_exclusivo", "No"))}</p>'
    )
    partes.append(_html_fila_campo_fijo("CERTIFICADO DE PROVEEDOR EXCLUSIVO O AUTORIZADO", contenido_certificado))

    patrimonio_aplica = datos.get("patrimonio_aplica", "No")
    contenido_patrimonio = (
        f'<p style="margin:2px 0; font-size:11px;"><b>¿Aplica?:</b> {_html_valor_o_vacio(patrimonio_aplica)}</p>'
    )
    if patrimonio_aplica == "Sí":
        contenido_patrimonio += _html_parrafos(TEXTO_PATRIMONIO_INTRO)
        contenido_patrimonio += '<p style="margin:4px 0 2px; font-weight:bold;">Bienes y/o Servicios</p>'
        contenido_patrimonio += _html_tabla(TABLA_PATRIMONIO_ENCABEZADO, TABLA_PATRIMONIO_BIENES_SERVICIOS)
        contenido_patrimonio += '<p style="margin:4px 0 2px; font-weight:bold;">Obras</p>'
        contenido_patrimonio += _html_tabla(TABLA_PATRIMONIO_ENCABEZADO, TABLA_PATRIMONIO_OBRAS)
    partes.append(_html_fila_campo_fijo("PATRIMONIO", contenido_patrimonio))

    partes.append(
        _html_fila_campo_fijo(
            "TIEMPO DE EXISTENCIA LEGAL DE PERSONAS JURÍDICAS", _html_parrafos(TEXTO_TIEMPO_EXISTENCIA_LEGAL)
        )
    )

    contenido_checklist = _html_parrafos(TEXTO_CHECKLIST_INTRO)
    contenido_checklist += _html_tabla(
        TABLA_CHECKLIST_ENCABEZADO, [[c, "", "", ""] for c in TABLA_CHECKLIST_CRITERIOS_FIJOS]
    )
    partes.append(
        _html_fila_campo_fijo("METODOLOGÍA DE EVALUACIÓN DE OFERTA (CUMPLE/NO CUMPLE)", contenido_checklist)
    )

    partes.append(
        _html_fila_campo(
            "EVALUACIÓN DEL ANÁLISIS DE ESTRATEGIA DE ADQUISICIÓN (MEJOR VALOR POR DINERO)",
            datos.get("evaluacion_estrategia_adquisicion", ""),
        )
    )
    partes.append(
        _html_fila_campo(
            "OTROS PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN", datos.get("otros_parametros_evaluacion", "")
        )
    )

    contenido_puntaje = _html_parrafos(TEXTO_PUNTAJE_INTRO)
    contenido_puntaje += _html_tabla(TABLA_PUNTAJE_ENCABEZADO, TABLA_PUNTAJE_FIJA)
    partes.append(_html_fila_campo_fijo("METODOLOGÍA DE EVALUACIÓN DE OFERTA POR PUNTAJE", contenido_puntaje))

    partes.append("</table>")

    # FECHA y FIRMAS DE RESPONSABILIDAD no existen en el modelo de
    # referencia -- se muestran aparte, fuera de la tabla continua, igual
    # que en el .docx (ver scripts/especificaciones_tecnicas_generator.py).
    partes.append(
        f'<p style="margin:14px 0 4px;"><b>FECHA:</b> {_html_valor_o_vacio(datos.get("fecha_documento", ""))}</p>'
    )
    firmas = datos.get("firmas", {})
    partes.append('<p style="margin:10px 0 4px; font-weight:bold;">FIRMAS DE RESPONSABILIDAD:</p>')
    filas_firmas = []
    for clave, etiqueta in (("elaborado", "Elaborado por"), ("revisado", "Revisado por"), ("aprobado", "Aprobado por")):
        d = firmas.get(clave, {})
        filas_firmas.append(
            [etiqueta, d.get("nombre") or "", d.get("cargo") or "", d.get("firmado_por") or ""]
        )
    partes.append(_html_tabla(["", "Nombre", "Cargo", "Firmado por"], filas_firmas))

    partes.append(f'<img src="data:image/jpeg;base64,{pie_b64}" style="width:100%; margin-top:14px;">')
    partes.append("</div>")

    st.markdown("".join(partes), unsafe_allow_html=True)


# Claves de los ~44 widgets "simples" (text_input/text_area/number_input/
# selectbox) de las secciones "Formulario y Parámetros" y "Generación y
# Vista Previa" que solo usan `key=` sin `value=` propio.
# Streamlit borra la entrada de session_state de un widget con key en
# cualquier rerun en el que ese widget NO se instancie (ver docs: "widget
# state will be lost if the widget is removed from the app"), y aqui eso
# pasa cada vez que el usuario cambia de seccion de Especificaciones Técnicas (las
# secciones son ramas `elif` condicionales, no todas se ejecutan en cada
# rerun) o de pagina del sidebar: el campo se ve vacio al volver aunque
# el usuario ya lo habia llenado. Los widgets de items (data_editor) y
# especificaciones tecnicas (value=spec.get(...) desde la lista
# persistente especificaciones_tecnicas_specs) ya son inmunes a esto porque no dependen
# unicamente del key -- este mismo patron (un valor guardado aparte,
# reinyectado en el widget) es el que se replica aqui para el resto.
_ESPECIFICACIONES_TECNICAS_CAMPOS_SIMPLES_PERSISTENTES = [
    "especificaciones_tecnicas_tab_activa",
    "especificaciones_tecnicas_objeto_contratacion",
    # "especificaciones_tecnicas_presupuesto" NO esta aqui a proposito: ya no es un valor que
    # el usuario escriba (esta `disabled=True`) sino que se recalcula y se
    # reasigna en cada rerun de la seccion "Ítems y Presupuesto" desde
    # _sumar_valor_total_items_especificaciones_tecnicas -- no necesita este respaldo porque
    # nunca depende de lo que Streamlit haya borrado o no.
    "especificaciones_tecnicas_codigo_cpc_mayor_peso",
    "especificaciones_tecnicas_alcance",
    "especificaciones_tecnicas_plazo",
    "especificaciones_tecnicas_personal_tecnico_principal",
    "especificaciones_tecnicas_personal_tecnico_auxiliar",
    "especificaciones_tecnicas_equipo_trabajo",
    "especificaciones_tecnicas_recursos",
    "especificaciones_tecnicas_forma_pago",
    "especificaciones_tecnicas_lugar",
    "especificaciones_tecnicas_obligaciones_entidad",
    "especificaciones_tecnicas_obligaciones_contratista",
    "especificaciones_tecnicas_garantias_tecnicas",
    "especificaciones_tecnicas_monto_garantia_rc",
    "especificaciones_tecnicas_vigencia_oferta",
    "especificaciones_tecnicas_tipo_adjudicacion",
    "especificaciones_tecnicas_admin_nombre",
    "especificaciones_tecnicas_admin_cargo",
    "especificaciones_tecnicas_admin_cedula",
    "especificaciones_tecnicas_tecnico_nombre",
    "especificaciones_tecnicas_tecnico_cargo",
    "especificaciones_tecnicas_tecnico_correo",
    "especificaciones_tecnicas_direccion_contacto",
    "especificaciones_tecnicas_telefono_contacto",
    "especificaciones_tecnicas_proceso_aplicar",
    "especificaciones_tecnicas_pct_general",
    "especificaciones_tecnicas_pct_especifica",
    "especificaciones_tecnicas_titulo_profesional",
    "especificaciones_tecnicas_equipo_evaluar",
    "especificaciones_tecnicas_certificado_proveedor",
    "especificaciones_tecnicas_patrimonio_aplica",
    "especificaciones_tecnicas_evaluacion_estrategia",
    "especificaciones_tecnicas_analisis_estrategia_html",
    "especificaciones_tecnicas_otros_parametros",
    "especificaciones_tecnicas_fecha",
    "especificaciones_tecnicas_firma_elaborado_nombre",
    "especificaciones_tecnicas_firma_elaborado_cargo",
    "especificaciones_tecnicas_firma_elaborado_firmado",
    "especificaciones_tecnicas_firma_revisado_nombre",
    "especificaciones_tecnicas_firma_revisado_cargo",
    "especificaciones_tecnicas_firma_revisado_firmado",
    "especificaciones_tecnicas_firma_aprobado_nombre",
    "especificaciones_tecnicas_firma_aprobado_cargo",
    "especificaciones_tecnicas_firma_aprobado_firmado",
]


def _restaurar_campos_simples_especificaciones_tecnicas() -> None:
    """Repone en session_state, ANTES de crear ningun widget, los campos
    que Streamlit haya borrado por no haberse instanciado en el rerun
    anterior (otra sub-pestaña o otra pagina del sidebar), usando la
    ultima copia guardada en el diccionario sombra."""
    sombra = st.session_state.setdefault("_especificaciones_tecnicas_sombra", {})
    for clave in _ESPECIFICACIONES_TECNICAS_CAMPOS_SIMPLES_PERSISTENTES:
        if clave not in st.session_state and clave in sombra:
            st.session_state[clave] = sombra[clave]


def _guardar_campos_simples_especificaciones_tecnicas() -> None:
    """Copia al diccionario sombra el valor actual de cada campo que SI
    se instancio en este rerun, para poder reponerlo la proxima vez que
    Streamlit borre su entrada de session_state (ver
    _restaurar_campos_simples_especificaciones_tecnicas)."""
    sombra = st.session_state.setdefault("_especificaciones_tecnicas_sombra", {})
    for clave in _ESPECIFICACIONES_TECNICAS_CAMPOS_SIMPLES_PERSISTENTES:
        if clave in st.session_state:
            sombra[clave] = st.session_state[clave]


def _df_a_registros_json(df: pd.DataFrame) -> list[dict]:
    """Convierte un DataFrame a una lista de dicts de tipos nativos de
    Python (str/int/float/None), lista para json.dumps(allow_nan=False).
    astype(object) ANTES de reemplazar NaN por None es necesario: sobre
    una columna float64/Int64, asignar None con .where() se revierte solo
    a NaN/pd.NA porque esos dtypes no pueden contener None -- solo una
    columna "object" lo conserva tal cual."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def _serializar_estado_especificaciones_tecnicas() -> dict:
    """Junta TODO el estado persistente de Especificaciones Técnicas (los ~44 campos
    simples de _ESPECIFICACIONES_TECNICAS_CAMPOS_SIMPLES_PERSISTENTES, la Estrategia de
    Adquisicion en HTML, y los items/CPC/especificaciones tecnicas) en un
    dict de tipos puros -- ni un DataFrame ni ningun objeto de Streamlit
    -- listo para guardarse como datos_json de un borrador. Deliberadamente
    NO incluye: "_especificaciones_tecnicas_sombra" (cache interno, se reconstruye solo),
    "especificaciones_tecnicas_docx_bytes"/"especificaciones_tecnicas_docx_nombre" (el .docx se regenera al
    vuelo, no hace falta guardar el binario) ni las claves de los
    file_uploader por item (un widget nativo no admite pre-rellenarse)."""
    estado: dict = {}
    for clave in _ESPECIFICACIONES_TECNICAS_CAMPOS_SIMPLES_PERSISTENTES:
        if clave in st.session_state:
            estado[clave] = st.session_state[clave]
    estado["especificaciones_tecnicas_analisis_estrategia_html"] = st.session_state.get("especificaciones_tecnicas_analisis_estrategia_html", "")
    estado["especificaciones_tecnicas_items_df"] = _df_a_registros_json(st.session_state.especificaciones_tecnicas_items_df)
    estado["especificaciones_tecnicas_cpc_df"] = _df_a_registros_json(st.session_state.especificaciones_tecnicas_cpc_df)
    estado["especificaciones_tecnicas_specs"] = st.session_state.especificaciones_tecnicas_specs
    estado["especificaciones_tecnicas_items_editor_version"] = st.session_state.especificaciones_tecnicas_items_editor_version
    estado["especificaciones_tecnicas_siguiente_fila_id"] = st.session_state.especificaciones_tecnicas_siguiente_fila_id
    estado["especificaciones_tecnicas_siguiente_param_id"] = st.session_state.especificaciones_tecnicas_siguiente_param_id
    return estado


def _restaurar_estado_especificaciones_tecnicas(estado: dict) -> None:
    """Inversa de _serializar_estado_especificaciones_tecnicas: repone en session_state TODO
    el estado guardado de un borrador. Los DataFrames se reconstruyen
    desde sus registros (una lista vacia usa los constructores _vacio
    para no perder las columnas esperadas -- pd.DataFrame([]) no tiene
    columnas). especificaciones_tecnicas_items_editor_version se incrementa (no se copia tal
    cual) para forzar un key nuevo en el data_editor de items y que el
    grid se remonte limpio con el dataframe cargado, en vez de intentar
    reconciliar un diff incremental sobre el grid que ya tenia montado
    (mismo motivo que al guardar items, ver "Guardar Ítems")."""
    for clave in _ESPECIFICACIONES_TECNICAS_CAMPOS_SIMPLES_PERSISTENTES:
        if clave in estado:
            st.session_state[clave] = estado[clave]
    st.session_state["especificaciones_tecnicas_analisis_estrategia_html"] = estado.get("especificaciones_tecnicas_analisis_estrategia_html", "")

    registros_items = estado.get("especificaciones_tecnicas_items_df") or []
    st.session_state.especificaciones_tecnicas_items_df = (
        pd.DataFrame(registros_items) if registros_items else _dataframe_items_especificaciones_tecnicas_vacio()
    )
    registros_cpc = estado.get("especificaciones_tecnicas_cpc_df") or []
    st.session_state.especificaciones_tecnicas_cpc_df = (
        pd.DataFrame(registros_cpc) if registros_cpc else _dataframe_cpc_especificaciones_tecnicas_vacio()
    )
    st.session_state.especificaciones_tecnicas_specs = estado.get("especificaciones_tecnicas_specs") or []
    st.session_state.especificaciones_tecnicas_items_editor_version = st.session_state.get("especificaciones_tecnicas_items_editor_version", 0) + 1
    st.session_state.especificaciones_tecnicas_siguiente_fila_id = estado.get("especificaciones_tecnicas_siguiente_fila_id", 0)
    st.session_state.especificaciones_tecnicas_siguiente_param_id = estado.get("especificaciones_tecnicas_siguiente_param_id", 0)
    # La sombra vieja puede tener valores de OTRA contratacion que ya no
    # aplican; se descarta y _guardar_campos_simples_especificaciones_tecnicas la reconstruye
    # con los valores recien cargados al final de este mismo rerun.
    st.session_state.pop("_especificaciones_tecnicas_sombra", None)


def _reiniciar_estado_especificaciones_tecnicas() -> None:
    """Vacia todo el estado de Especificaciones Técnicas (usado por "Nueva contratación" y
    tras "Eliminar contratación"), dejando el formulario como una sesion
    recien abierta -- misma lista de claves que _restaurar_estado_especificaciones_tecnicas,
    pero con los valores vacios de cada widget en vez de los de un
    borrador."""
    for clave in _ESPECIFICACIONES_TECNICAS_CAMPOS_SIMPLES_PERSISTENTES:
        st.session_state.pop(clave, None)
    st.session_state.pop("especificaciones_tecnicas_analisis_estrategia_html", None)
    st.session_state.pop("_especificaciones_tecnicas_sombra", None)
    st.session_state.pop("especificaciones_tecnicas_docx_bytes", None)
    st.session_state.pop("especificaciones_tecnicas_docx_nombre", None)
    st.session_state.especificaciones_tecnicas_items_df = _dataframe_items_especificaciones_tecnicas_vacio()
    st.session_state.especificaciones_tecnicas_cpc_df = _dataframe_cpc_especificaciones_tecnicas_vacio()
    st.session_state.especificaciones_tecnicas_specs = []
    st.session_state.especificaciones_tecnicas_items_editor_version = st.session_state.get("especificaciones_tecnicas_items_editor_version", 0) + 1
    st.session_state.especificaciones_tecnicas_siguiente_fila_id = 0
    st.session_state.especificaciones_tecnicas_siguiente_param_id = 0
    st.session_state.especificaciones_tecnicas_borrador_id = None
    # NO se puede escribir directo a st.session_state["especificaciones_tecnicas_borrador_selector"]
    # aqui: esta funcion se llama desde botones que se instancian DESPUES
    # del selectbox en el mismo rerun, y Streamlit prohibe modificar la
    # key de un widget ya instanciado en ese mismo rerun. En cambio, se
    # deja esta "orden pendiente" en una key comun y corriente (no atada a
    # ningun widget) que _render_panel_borradores_especificaciones_tecnicas aplica al
    # selectbox, pero ANTES de crearlo, en el rerun siguiente -- si no se
    # tocara nada, el selectbox conservaria la etiqueta de la contratacion
    # anterior y la recargaria sola.
    st.session_state["especificaciones_tecnicas_borrador_selector_pendiente"] = None


def _render_panel_borradores_especificaciones_tecnicas() -> None:
    """Panel de control (arriba del todo de "Formularios y Registro") para
    guardar/cargar/eliminar contrataciones completas como filas de
    borradores_contratacion (ver src/database.py), asi el trabajo
    sobrevive a cerrar el navegador o reiniciar Streamlit -- hasta ahora
    todo el formulario vivia solo en session_state.

    El selectbox usa el id numerico del borrador como VALOR real del
    widget (no el texto visible, vía format_func): la etiqueta incluye la
    fecha de actualizacion, que cambia en cada guardado, y si esa fecha
    fuera el valor del widget, tras guardar Streamlit podria encontrarse
    con que el valor que tenia guardado en session_state ya no esta entre
    las opciones actuales -- eso es un error duro en Streamlit, no un
    detalle cosmetico. Con el id como valor eso no puede pasar: el mismo
    id sigue siendo valido aunque su etiqueta visible cambie."""
    if "especificaciones_tecnicas_borrador_id" not in st.session_state:
        st.session_state.especificaciones_tecnicas_borrador_id = None

    borradores = listar_borradores_especificaciones_tecnicas()
    etiqueta_por_id = {None: "— Nueva contratación (sin guardar) —"}
    for borrador in borradores:
        etiqueta_por_id[borrador["id"]] = (
            f"{borrador['nombre_contratacion']} (act. {borrador['fecha_actualizacion']})"
        )
    ids_disponibles = list(etiqueta_por_id.keys())

    # Aplica una orden pendiente de otro boton (Guardar/Nueva/Eliminar, ver
    # sus comentarios: ellos no pueden tocar la key del selectbox porque
    # se instancian despues de el en su propio rerun) ANTES de crear el
    # widget, que es el unico momento en que Streamlit permite fijar su
    # valor. Sin una orden pendiente, si el id que el selectbox tenia
    # guardado ya no existe entre las opciones actuales (primera carga, o
    # el borrador se elimino desde otra sesion), se resetea a "Nueva
    # contratación" para no reventar el selectbox con un valor invalido.
    #
    # OJO: nunca se asigna `None` explicitamente a session_state["especificaciones_tecnicas_borrador_selector"]
    # (se hace `pop` en su lugar) -- se comprobo empiricamente que un
    # st.selectbox recien creado (key todavia ausente de session_state)
    # muestra el placeholder "Choose an option" en vez de la etiqueta
    # mapeada de None ("Nueva contratación") si ese None se escribe a mano
    # ANTES de que el widget exista por primera vez, aunque None sea una
    # opcion valida de la lista. Dejando la key ausente en ese caso,
    # Streamlit cae solo, correctamente, en su propio default (indice 0,
    # que en `ids_disponibles` siempre es None) -- ese default SI se
    # renderiza bien.
    def _fijar_selector_borrador(id_objetivo: int | None) -> None:
        if id_objetivo is None:
            st.session_state.pop("especificaciones_tecnicas_borrador_selector", None)
        else:
            st.session_state["especificaciones_tecnicas_borrador_selector"] = id_objetivo

    if "especificaciones_tecnicas_borrador_selector_pendiente" in st.session_state:
        _fijar_selector_borrador(st.session_state.pop("especificaciones_tecnicas_borrador_selector_pendiente"))
    elif (
        "especificaciones_tecnicas_borrador_selector" not in st.session_state
        or st.session_state.get("especificaciones_tecnicas_borrador_selector") not in ids_disponibles
    ):
        # "not in st.session_state" (ademas del chequeo de valor invalido
        # de antes) porque este panel ahora es una seccion mas del menu
        # lateral (ver _render_navegacion_especificaciones_tecnicas_sidebar): al navegar a
        # otra seccion y volver, Streamlit borra este selectbox por no
        # haberse instanciado mientras tanto -- y como None (la opcion
        # "Nueva contratación") SIEMPRE es un valor valido de la lista,
        # el chequeo anterior (que solo miraba "esta en ids_disponibles")
        # no detectaba la key ausente y mostraba "Nueva contratación" aun
        # con un borrador ya cargado.
        _fijar_selector_borrador(
            st.session_state.especificaciones_tecnicas_borrador_id if st.session_state.especificaciones_tecnicas_borrador_id in ids_disponibles else None
        )

    st.markdown("**:material/folder_open: Gestor de Contrataciones** (guardado persistente en la base de datos)")
    col_selector, col_guardar, col_nuevo, col_eliminar = st.columns([3, 1, 1, 1])

    id_seleccionado = col_selector.selectbox(
        "Cargar contratación guardada",
        ids_disponibles,
        format_func=lambda id_: etiqueta_por_id.get(id_, "— Nueva contratación (sin guardar) —"),
        key="especificaciones_tecnicas_borrador_selector",
        label_visibility="collapsed",
    )
    # Cargar: solo cuando el usuario ACABA de elegir un id distinto al que
    # ya esta activo (si fueran iguales, se re-cargaria en cada rerun
    # posterior sin que el usuario haya vuelto a tocar el selector).
    if id_seleccionado is not None and id_seleccionado != st.session_state.especificaciones_tecnicas_borrador_id:
        borrador = obtener_borrador_especificaciones_tecnicas(id_seleccionado)
        if borrador is not None:
            try:
                estado = json.loads(borrador["datos_json"])
            except json.JSONDecodeError:
                st.error("El borrador guardado tiene un JSON inválido y no se pudo cargar.")
            else:
                # No se aplica _restaurar_estado_especificaciones_tecnicas(estado) aqui mismo:
                # este script termina en el rerun() de abajo sin llegar a
                # instanciar ningun widget de ninguna pestaña (el despacho
                # de pestañas viene mas abajo), y se comprobo
                # empiricamente que Streamlit puede reinicializar esas
                # keys "huerfanas" a su valor vacio de widget ANTES de que
                # el rerun automatico vuelva a correr el script -- como la
                # key sigue *presente* (vacia, no ausente), el respaldo de
                # sombra en _restaurar_campos_simples_especificaciones_tecnicas no la detecta
                # (esa funcion solo repone claves AUSENTES) y el campo se
                # ve vacio pese a haberse cargado bien. La solucion real
                # es no tocar session_state todavia: se deja el estado a
                # aplicar en una key comun (no atada a ningun widget) y
                # render_formularios_y_registro la aplica en su primerisima
                # linea del rerun siguiente, antes de que exista chance de
                # que cualquier widget la pise.
                st.session_state["especificaciones_tecnicas_estado_pendiente_restaurar"] = estado
                st.session_state.especificaciones_tecnicas_borrador_id = id_seleccionado
                st.success(f"Contratación «{borrador['nombre_contratacion']}» cargada.")
                st.rerun()

    if col_guardar.button(":material/save: Guardar progreso", key="especificaciones_tecnicas_guardar_borrador", use_container_width=True):
        nombre_contratacion = (st.session_state.get("especificaciones_tecnicas_objeto_contratacion") or "").strip()
        if not nombre_contratacion:
            st.error(
                'Completa "Objeto de contratación" en la sección "Formulario y Parámetros" antes de guardar.'
            )
        else:
            datos_json = json.dumps(_serializar_estado_especificaciones_tecnicas(), ensure_ascii=False, allow_nan=False)
            resultado = guardar_borrador_especificaciones_tecnicas(
                st.session_state.especificaciones_tecnicas_borrador_id, nombre_contratacion, datos_json
            )
            if resultado is not None:
                st.session_state.especificaciones_tecnicas_borrador_id = resultado["id"]
                # especificaciones_tecnicas_borrador_selector no se puede tocar aqui (el
                # selectbox ya se instancio arriba en este mismo rerun) --
                # se deja la orden pendiente para el proximo rerun, ver el
                # comentario en _render_panel_borradores_especificaciones_tecnicas.
                st.session_state["especificaciones_tecnicas_borrador_selector_pendiente"] = resultado["id"]
                st.success(f"Progreso guardado como «{nombre_contratacion}».")
                st.rerun()

    if col_nuevo.button(":material/note_add: Nueva contratación", key="especificaciones_tecnicas_nueva_contratacion", use_container_width=True):
        _reiniciar_estado_especificaciones_tecnicas()
        st.success("Formulario en blanco: lista para una nueva contratación.")
        st.rerun()

    if "especificaciones_tecnicas_confirmar_eliminar_borrador" not in st.session_state:
        st.session_state.especificaciones_tecnicas_confirmar_eliminar_borrador = False

    if col_eliminar.button(
        ":material/delete: Eliminar contratación",
        key="especificaciones_tecnicas_eliminar_borrador",
        use_container_width=True,
        disabled=st.session_state.especificaciones_tecnicas_borrador_id is None,
    ):
        st.session_state.especificaciones_tecnicas_confirmar_eliminar_borrador = True
        st.rerun()

    if st.session_state.especificaciones_tecnicas_confirmar_eliminar_borrador:
        # Misma logica de doble clic que "Vaciar la base de datos" en
        # Configuracion: una eliminacion no se puede deshacer, asi que un
        # solo clic accidental no debe bastar para perder una
        # contratacion guardada. Fuera de las 4 columnas de arriba (no
        # anida columnas dentro de columnas) para que la confirmacion se
        # vea a todo lo ancho, no apretada en col_eliminar.
        st.warning("¿Eliminar esta contratación guardada? No se puede deshacer.")
        col_confirmar, col_cancelar = st.columns(2)
        if col_confirmar.button("Sí, eliminar", key="especificaciones_tecnicas_confirmar_eliminar_borrador_btn", type="primary"):
            borrador_id = st.session_state.especificaciones_tecnicas_borrador_id
            st.session_state.especificaciones_tecnicas_confirmar_eliminar_borrador = False
            if borrador_id is not None and eliminar_borrador_especificaciones_tecnicas(borrador_id):
                _reiniciar_estado_especificaciones_tecnicas()
                st.success("Contratación eliminada.")
            st.rerun()
        if col_cancelar.button("Cancelar", key="especificaciones_tecnicas_cancelar_eliminar_borrador_btn"):
            st.session_state.especificaciones_tecnicas_confirmar_eliminar_borrador = False
            st.rerun()

    if st.session_state.especificaciones_tecnicas_borrador_id is not None:
        st.caption(f"Editando la contratación guardada #{st.session_state.especificaciones_tecnicas_borrador_id}.")
    else:
        st.caption("Contratación nueva: aún no se ha guardado.")


def _inyectar_estilos_especificaciones_tecnicas_cards() -> None:
    """CSS liviano de "Formularios y Registro": botones redondeados,
    sombra sutil sobre el wrapper nativo de st.container(border=True)
    (look de tarjeta), el sub-menu lateral de secciones de Especificaciones Técnicas
    distinguido de los 5 botones de pagina de arriba (ver
    _render_navegacion_especificaciones_tecnicas_sidebar), y las metricas financieras
    (Sumatoria Total, Presupuesto Referencial) resaltadas -- mismo patron
    de st.container(key=...) -> ".st-key-<key>" ya usado en la zona de
    peligro de render_vaciar_base_datos (linea ~1176)."""
    st.markdown(
        f"""
        <style>
        .stButton > button {{
            border-radius: 10px;
        }}
        [data-testid="stVerticalBlockBorderWrapper"] {{
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.10);
        }}
        .st-key-especificaciones_tecnicas_sidebar_subnav {{
            border-left: 2px solid rgba(255, 255, 255, 0.15);
            margin-left: 0.35rem;
            padding-left: 0.5rem;
        }}
        .st-key-especificaciones_tecnicas_sidebar_subnav .stButton > button {{
            font-size: 0.85rem;
            font-weight: 500;
            padding: 0.45rem 0.7rem;
        }}
        .st-key-especificaciones_tecnicas_metrica_sumatoria,
        .st-key-especificaciones_tecnicas_metrica_presupuesto {{
            border-color: {COLOR_SIDEBAR_ACENTO} !important;
            background-color: #FFF7ED;
        }}
        .st-key-especificaciones_tecnicas_metrica_sumatoria [data-testid="stMetricValue"] {{
            color: {COLOR_SIDEBAR_ACENTO};
            font-size: 1.6rem;
        }}
        .st-key-especificaciones_tecnicas_metrica_presupuesto input {{
            color: {COLOR_SIDEBAR_ACENTO} !important;
            font-weight: 700;
            font-size: 1.05rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_navegacion_especificaciones_tecnicas_sidebar(nombres_secciones: list[str]) -> None:
    """Menu lateral de las secciones de Especificaciones Técnicas, anidado DENTRO del
    sidebar principal (debajo de los 5 botones de pagina de
    render_navegacion_sidebar, ver el st.divider()+st.caption() que lo
    preceden) -- no reemplaza esa navegacion, la extiende solo mientras
    se esta en "Municipalidad de Guayaquil". Mismo patron ya probado ahi:
    un st.button por opcion (no st.tabs()/st.radio, ver el comentario en
    render_formularios_y_registro sobre por que) que fija
    especificaciones_tecnicas_tab_activa en session_state y dispara st.rerun(). Envuelto en
    st.container(key="especificaciones_tecnicas_sidebar_subnav") para poder distinguirlo con
    CSS propio (ver _inyectar_estilos_especificaciones_tecnicas_cards) sin tocar la regla
    compartida que estiliza los botones de pagina de arriba."""
    with st.sidebar:
        st.divider()
        st.caption("ESPECIFICACIONES TÉCNICAS")
        with st.container(key="especificaciones_tecnicas_sidebar_subnav"):
            for nombre in nombres_secciones:
                activo = st.session_state.especificaciones_tecnicas_tab_activa == nombre
                if st.button(
                    nombre,
                    key=f"especificaciones_tecnicas_nav_{nombre}",
                    use_container_width=True,
                    type="primary" if activo else "secondary",
                ):
                    st.session_state.especificaciones_tecnicas_tab_activa = nombre
                    st.rerun()


def render_formularios_y_registro() -> None:
    """Subseccion "Formularios y Registro": genera el .docx (y la tabla
    de items en Excel) de Especificaciones Tecnicas para los
    Procesos de Bienes, replicando el formato exacto de un modelo Word
    de referencia (ver scripts/especificaciones_tecnicas_generator.py). El encabezado fijo,
    la tabla de items con calculo automatico y su tipo Bien/Servicio POR
    ITEM, las especificaciones tecnicas condicionales, ~30 campos de
    condiciones legales (organizados en expanders) y una vista previa en
    vivo se organizan en 4 secciones navegables desde un menu lateral
    (ver _render_navegacion_especificaciones_tecnicas_sidebar) para no ser un formulario
    gigante."""
    # Aplica un borrador recien elegido en el selectbox del panel de
    # borradores ANTES que cualquier otra cosa en esta funcion, incluidos
    # los defaults de mas abajo: es el primerisimo punto del rerun donde
    # todavia no se instancio ningun widget de ninguna seccion, que es
    # justamente lo que garantiza que Streamlit no le pise el valor
    # despues (ver el comentario en _render_panel_borradores_especificaciones_tecnicas, rama
    # "Cargar contratación guardada", sobre por que la restauracion no se
    # puede hacer en el mismo rerun en que se detecta la seleccion).
    if "especificaciones_tecnicas_estado_pendiente_restaurar" in st.session_state:
        _restaurar_estado_especificaciones_tecnicas(st.session_state.pop("especificaciones_tecnicas_estado_pendiente_restaurar"))
        # _guardar_campos_simples_especificaciones_tecnicas() AHORA MISMO, no al final de la
        # funcion: los campos de una seccion que no sea la activa (la que
        # se restauro junto con todo lo demas) no van a pasar por ningun
        # widget en ESTE rerun, asi que van a quedar "huerfanos" otra vez
        # de cara al proximo rerun -- la sombra es lo unico que los trae
        # de vuelta (ver _restaurar_campos_simples_especificaciones_tecnicas), y si Streamlit
        # interrumpe este rerun a medio camino porque el usuario ya
        # disparo otra interaccion (ej. cambiar de seccion) antes de que
        # este termine solo, un `_guardar_campos_simples_especificaciones_tecnicas()` al
        # final de la funcion nunca llegaria a ejecutarse. Guardando la
        # sombra aqui, en la primera linea posible, esto ya quedo hecho
        # pase lo que pase con el resto del rerun.
        _guardar_campos_simples_especificaciones_tecnicas()

    _inyectar_estilos_especificaciones_tecnicas_cards()

    st.subheader(":material/edit_note: Formularios y Registro")
    st.caption(
        "Genera el documento de Especificaciones Técnicas para los Procesos de Bienes, "
        "con el mismo formato del modelo institucional."
    )

    if "especificaciones_tecnicas_items_df" not in st.session_state:
        st.session_state.especificaciones_tecnicas_items_df = _dataframe_items_especificaciones_tecnicas_vacio()
    if "especificaciones_tecnicas_items_editor_version" not in st.session_state:
        st.session_state.especificaciones_tecnicas_items_editor_version = 0
    if "especificaciones_tecnicas_siguiente_fila_id" not in st.session_state:
        st.session_state.especificaciones_tecnicas_siguiente_fila_id = 0
    if "especificaciones_tecnicas_cpc_df" not in st.session_state:
        st.session_state.especificaciones_tecnicas_cpc_df = _dataframe_cpc_especificaciones_tecnicas_vacio()
    if "especificaciones_tecnicas_specs" not in st.session_state:
        st.session_state.especificaciones_tecnicas_specs = []
    if "especificaciones_tecnicas_siguiente_param_id" not in st.session_state:
        st.session_state.especificaciones_tecnicas_siguiente_param_id = 0

    _restaurar_campos_simples_especificaciones_tecnicas()

    # st.tabs() nativo no acepta key/session_state: su seccion activa se
    # rastrea solo en el frontend, y se sabe que se resetea a la primera
    # cuando el script hace st.rerun() manual (como los botones
    # "Añadir/Quitar item"/"Añadir/Quitar parametro" mas abajo) en vez de
    # un rerun nativo disparado por el propio widget editado. Un selector
    # respaldado en session_state (mismo patron ya probado en
    # render_navegacion_sidebar, reutilizado tal cual en
    # _render_navegacion_especificaciones_tecnicas_sidebar) elimina ese reseteo de forma
    # deterministica, sin depender de como Streamlit maneje cada rerun.
    NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS = [
        "Gestor de Borradores / Contrataciones",
        "Formulario y Parámetros",
        "Ítems y Presupuesto",
        "Generación y Vista Previa",
    ]
    if "especificaciones_tecnicas_tab_activa" not in st.session_state:
        st.session_state.especificaciones_tecnicas_tab_activa = NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS[0]
    elif st.session_state.especificaciones_tecnicas_tab_activa not in NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS:
        # Puede pasar al cargar un borrador guardado ANTES de este cambio
        # (tenia nombres de pestaña viejos, ej. "4. Condiciones Legales y
        # Descarga") -- a diferencia del st.radio() de antes (que hubiera
        # tirado un StreamlitAPIException, un error duro y visible ante
        # un valor fuera de lista), el selector por botones no valida
        # nada: un valor no reconocido simplemente no hace matchear
        # ningun `elif` de mas abajo y deja la seccion en blanco sin
        # ningun aviso. Se aterriza en "Formulario y Parámetros" (no en
        # la primera de la lista) porque quien esta en este caso
        # probablemente acaba de cargar un borrador viejo y quiere ver
        # sus datos, no la pantalla de borradores.
        st.session_state.especificaciones_tecnicas_tab_activa = NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS[1]

    _render_navegacion_especificaciones_tecnicas_sidebar(NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS)
    tab_activa = st.session_state.especificaciones_tecnicas_tab_activa

    if tab_activa == NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS[0]:
        with st.container(border=True):
            _render_panel_borradores_especificaciones_tecnicas()

    elif tab_activa == NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS[1]:
        with st.container(border=True):
            st.markdown("**Encabezado fijo del documento**")
            st.info(f"{TITULO_PROCESO_FIJO}\n\n{COORDINACION_FIJA}")
            st.text_area(
                'Objeto de contratación (se resalta en amarillo en el documento generado)',
                placeholder="Ej: SUMINISTRO, INSTALACIÓN, MANTENIMIENTO PREVENTIVO Y REPOTENCIACIÓN DE...",
                key="especificaciones_tecnicas_objeto_contratacion",
            )

        st.markdown("**Especificaciones Técnicas por Ítem**")
        df_items = _recalcular_items_especificaciones_tecnicas(st.session_state.especificaciones_tecnicas_items_df)
        cantidad_items = len(df_items)
        specs = st.session_state.especificaciones_tecnicas_specs
        tipos_por_fila = df_items["Tipo"].fillna("Bien").tolist() if cantidad_items else []

        while len(specs) < cantidad_items:
            specs.append(_specs_vacias_especificaciones_tecnicas(tipos_por_fila[len(specs)]))
        del specs[cantidad_items:]
        for indice, tipo_fila in enumerate(tipos_por_fila):
            # si el usuario cambio el Tipo de ESE item en la seccion de
            # Items, la spec ya cargada tiene la forma equivocada y hay
            # que reiniciarla (no se puede mezclar, ej., parametros de
            # Bien con campos de Servicio).
            es_spec_de_servicio = "procedimiento" in specs[indice]
            if es_spec_de_servicio != (tipo_fila == "Servicio"):
                specs[indice] = _specs_vacias_especificaciones_tecnicas(tipo_fila)

        if cantidad_items == 0:
            st.info(
                'Agrega ítems en la sección "Ítems y Presupuesto" para poder '
                "describir sus especificaciones técnicas."
            )
        else:
            for indice in range(cantidad_items):
                tipo_item = tipos_por_fila[indice]
                descripcion_item = df_items.iloc[indice]["Descripción"] or f"Ítem {indice + 1}"
                with st.expander(
                    f"Ítem {indice + 1} ({tipo_item}) — {descripcion_item}", expanded=(indice == 0)
                ):
                    spec = specs[indice]
                    if tipo_item == "Bien":
                        spec["descripcion_material"] = st.text_area(
                            "Descripción de Material",
                            value=spec.get("descripcion_material", ""),
                            key=f"especificaciones_tecnicas_specs_material_{indice}",
                        )
                        spec["subtitulo_specs"] = st.text_input(
                            'Subtítulo (equivalente a "Modelo de Ejemplo", se resalta en verde)',
                            value=spec.get("subtitulo_specs", "MODELO DE EJEMPLO"),
                            key=f"especificaciones_tecnicas_specs_subtitulo_{indice}",
                        )
                        st.caption(
                            "Parámetros técnicos (ej. Parámetros de módulos, Gabinetes, Pantalla, etc.)"
                        )
                        parametros = spec.setdefault("parametros", [])
                        for indice_param, parametro in enumerate(parametros):
                            param_id = parametro["id"]
                            col_nombre, col_valor, col_quitar = st.columns([2, 2, 1])
                            etiquetas = "visible" if indice_param == 0 else "collapsed"
                            parametro["nombre"] = col_nombre.text_input(
                                "Parámetro",
                                value=parametro.get("nombre", ""),
                                key=f"especificaciones_tecnicas_specs_param_nombre_{indice}_{param_id}",
                                label_visibility=etiquetas,
                            )
                            # text_area (no text_input): algunas descripciones tecnicas
                            # traen listas en viñetas u otro texto multilinea, y un
                            # text_input de una sola linea le borraria los saltos de
                            # linea apenas el usuario/el archivo cargado los escribe.
                            parametro["valor"] = col_valor.text_area(
                                "Valor",
                                value=parametro.get("valor", ""),
                                key=f"especificaciones_tecnicas_specs_param_valor_{indice}_{param_id}",
                                label_visibility=etiquetas,
                                height=68,
                            )
                            if col_quitar.button(
                                ":material/delete:", key=f"especificaciones_tecnicas_specs_param_quitar_{indice}_{param_id}"
                            ):
                                parametros.pop(indice_param)
                                st.rerun()

                        col_agregar, col_cargar_archivo = st.columns([1, 2])
                        if col_agregar.button(":material/add: Añadir parámetro", key=f"especificaciones_tecnicas_specs_agregar_param_{indice}"):
                            st.session_state.especificaciones_tecnicas_siguiente_param_id += 1
                            parametros.append(
                                {
                                    "id": st.session_state.especificaciones_tecnicas_siguiente_param_id,
                                    "nombre": "",
                                    "valor": "",
                                }
                            )
                            st.rerun()

                        # Carga masiva: un Excel/CSV/TXT de 2 columnas (Parametro,
                        # Valor/Descripcion) se anexa a `parametros` -- nunca lo
                        # reemplaza, igual que el boton manual de arriba. La clave
                        # `especificaciones_tecnicas_specs_param_archivo_procesado_{indice}` guarda el
                        # file_id del ultimo archivo ya procesado para ESTE item:
                        # sin ese control, como el archivo subido sigue "presente"
                        # en el uploader en cada rerun posterior (Streamlit no lo
                        # limpia solo), sus filas se volverian a anexar una y otra
                        # vez en cualquier rerun futuro (ej. al tipear en otro campo).
                        archivo_subido = col_cargar_archivo.file_uploader(
                            ":material/attach_file: Cargar parámetros desde archivo (Excel/CSV/TXT, 2 columnas)",
                            type=["xlsx", "csv", "txt"],
                            key=f"especificaciones_tecnicas_specs_param_uploader_{indice}",
                        )
                        clave_procesado = f"especificaciones_tecnicas_specs_param_archivo_procesado_{indice}"
                        if archivo_subido is not None and st.session_state.get(clave_procesado) != archivo_subido.file_id:
                            try:
                                nuevos_parametros = _leer_parametros_desde_archivo(archivo_subido)
                            except ValueError as exc:
                                st.session_state[clave_procesado] = archivo_subido.file_id
                                st.error(f"No se pudo procesar «{archivo_subido.name}»: {exc}")
                            else:
                                for nuevo in nuevos_parametros:
                                    st.session_state.especificaciones_tecnicas_siguiente_param_id += 1
                                    parametros.append(
                                        {
                                            "id": st.session_state.especificaciones_tecnicas_siguiente_param_id,
                                            "nombre": nuevo["nombre"],
                                            "valor": nuevo["valor"],
                                        }
                                    )
                                st.session_state[clave_procesado] = archivo_subido.file_id
                                st.success(
                                    f"Se agregaron {len(nuevos_parametros)} parámetro(s) desde "
                                    f"«{archivo_subido.name}»."
                                )
                                st.rerun()
                    else:
                        spec["procedimiento"] = st.text_area(
                            "Procedimiento (Desmontaje/Montaje)",
                            value=spec.get("procedimiento", ""),
                            key=f"especificaciones_tecnicas_specs_procedimiento_{indice}",
                        )
                        spec["herramientas_equipo"] = st.text_area(
                            "Herramientas/Equipo",
                            value=spec.get("herramientas_equipo", ""),
                            key=f"especificaciones_tecnicas_specs_herramientas_{indice}",
                        )
                        spec["normas_aplicables"] = st.text_area(
                            "Normas aplicables",
                            value=spec.get("normas_aplicables", ""),
                            key=f"especificaciones_tecnicas_specs_normas_{indice}",
                        )
                        spec["medicion"] = st.text_area(
                            "Medición",
                            value=spec.get("medicion", ""),
                            key=f"especificaciones_tecnicas_specs_medicion_{indice}",
                        )
                        spec["forma_pago"] = st.text_area(
                            "Forma de Pago",
                            value=spec.get("forma_pago", ""),
                            key=f"especificaciones_tecnicas_specs_forma_pago_{indice}",
                        )
                        spec["obligaciones"] = st.text_area(
                            "Obligaciones",
                            value=spec.get("obligaciones", ""),
                            key=f"especificaciones_tecnicas_specs_obligaciones_{indice}",
                        )

    elif tab_activa == NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS[2]:
        with st.container(border=True):
            st.markdown("**Ítems**")
            st.caption(
                'Cada ítem tiene su propio selector "Tipo" (Bien/Servicio): distintos ítems del '
                'mismo proceso pueden ser de distinto tipo. La columna "Valor Total" se calcula '
                'automáticamente (Cantidad Solicitada × Valor Unitario) y no es editable. Presiona '
                '"Guardar Ítems" para aplicar los cambios.'
            )
            # La edicion vive dentro de un st.form: sin esto, CADA tecla/celda
            # confirmada dispara un rerun completo de todo el script mientras
            # el usuario sigue escribiendo, lo que puede chocar con el propio
            # render en curso del data_editor y competir con el resto de la
            # app por cada pulsacion. Dentro de un formulario, Streamlit NO
            # reejecuta el script hasta que se presiona el boton de submit:
            # todas las ediciones de celda se acumulan en el propio grid
            # (estado del navegador) y se entregan de una sola vez.
            #
            # La columna "Ítem" es NumberColumn(disabled=True): el usuario no
            # puede escribir en ella, asi que una fila nueva (num_rows are
            # "dynamic") queda con ese valor en None hasta que se recalcula.
            # Si esa fila con None se guarda tal cual en session_state y se
            # vuelve a pasar como `data=` al MISMO key de data_editor, el
            # dtype de la columna cambia de una corrida a otra (numpy "int"
            # no admite None, así que pandas lo sube silenciosamente a
            # float/object): el grid del frontend (glide-data-grid) recibe un
            # esquema de columnas distinto al que ya tenia montado para ese
            # key y su reconciliacion de React falla con "NotFoundError:
            # Failed to execute 'removeChild'", tipicamente ocultando o
            # perdiendo filas incompletas en el proceso. La solucion no es
            # solo evitar recalcular -- es no reutilizar el mismo key con un
            # dataframe de forma/dtype distinta: version = un key nuevo cada
            # vez que se guarda, forzando un remount limpio del grid en vez
            # de un diff incremental sobre un esquema que ya no coincide.
            with st.form("especificaciones_tecnicas_form_items", clear_on_submit=False):
                df_editado = st.data_editor(
                    st.session_state.especificaciones_tecnicas_items_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    key=f"especificaciones_tecnicas_data_editor_{st.session_state.especificaciones_tecnicas_items_editor_version}",
                    column_order=COLUMNAS_VISIBLES_ITEMS_ESPECIFICACIONES_TECNICAS,
                    column_config={
                        "Ítem": st.column_config.NumberColumn("Ítem", disabled=True, default=0),
                        "Tipo": st.column_config.SelectboxColumn(
                            "Tipo", options=["Bien", "Servicio"], required=True, default="Bien"
                        ),
                        "Cantidad Solicitada": st.column_config.NumberColumn(
                            "Cantidad Solicitada", min_value=0.0, step=1.0, default=0.0
                        ),
                        "Valor Unitario": st.column_config.NumberColumn(
                            "Valor Unitario", min_value=0.0, format="%.2f", default=0.0
                        ),
                        "Valor Total": st.column_config.NumberColumn("Valor Total", disabled=True, format="%.2f"),
                    },
                )
                guardar_items = st.form_submit_button(":material/save: Guardar Ítems", type="primary")

            if guardar_items:
                # Al guardar SI se recalcula (a diferencia de antes): "Ítem"
                # y "Valor Total" quedan bien formados (sin None) antes de
                # persistir a session_state, y el key con version bumped
                # fuerza al grid a remontarse desde cero con ese dataframe ya
                # limpio en el siguiente rerun -- no hay diff incremental que
                # pueda desincronizarse. _asignar_fila_ids_especificaciones_tecnicas (identidad
                # estable por fila) y el autocompletado de "Descripción CPC"
                # corren ANTES de ese recalculo/remount, por la misma razon:
                # nunca se reintroduce un dataframe a medio transformar en el
                # mismo key.
                df_con_ids = _asignar_fila_ids_especificaciones_tecnicas(df_editado)
                df_autocompletado, cpc_no_encontrados = _autocompletar_descripcion_cpc(
                    df_con_ids, st.session_state.especificaciones_tecnicas_items_df, _cargar_catalogo_cpc()
                )
                st.session_state.especificaciones_tecnicas_items_df = _recalcular_items_especificaciones_tecnicas(df_autocompletado)
                st.session_state.especificaciones_tecnicas_items_editor_version += 1
                if cpc_no_encontrados:
                    codigos_unicos = ", ".join(sorted(set(cpc_no_encontrados)))
                    st.warning(f"Código(s) CPC no encontrado(s) en el catálogo: {codigos_unicos}")
                st.success("Ítems guardados.")
                st.rerun()

            # "_fila_id" es un detalle interno (identidad estable entre
            # guardados, ver _asignar_fila_ids_especificaciones_tecnicas): se excluye de la
            # vista de solo lectura y del Excel exportado, igual que ya se
            # excluye del data_editor via column_order.
            df_items_calculado = _recalcular_items_especificaciones_tecnicas(st.session_state.especificaciones_tecnicas_items_df)
            df_items_visible = df_items_calculado.drop(columns=["_fila_id"], errors="ignore")
            st.dataframe(
                df_items_visible.style.format(
                    {"Valor Unitario": formatear_moneda_ec, "Valor Total": formatear_moneda_ec}
                ),
                use_container_width=True,
                hide_index=True,
            )

            # Sumatoria Total: misma fuente (_sumar_valor_total_items_especificaciones_tecnicas)
            # que autocompleta el Presupuesto Referencial de mas abajo -- los
            # dos numeros siempre coinciden porque ambos se calculan de este
            # mismo dataframe. Contenedor con key propio para el resalte
            # visual de metricas financieras (ver _inyectar_estilos_especificaciones_tecnicas_cards).
            with st.container(key="especificaciones_tecnicas_metrica_sumatoria", border=True):
                st.metric("Sumatoria Total", formatear_moneda_ec(_sumar_valor_total_items_especificaciones_tecnicas(df_items_visible)))

            buffer_excel = io.BytesIO()
            df_items_visible.to_excel(buffer_excel, index=False, engine="openpyxl")
            st.download_button(
                ":material/table_chart: Descargar Tabla de Ítems en Excel",
                data=buffer_excel.getvalue(),
                file_name="EspecificacionesTecnicas_items.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="especificaciones_tecnicas_descargar_excel",
            )

        with st.expander("Presupuesto y Alcance", expanded=True):
            # Bloqueado y autocompletado con la Sumatoria Total de arriba
            # (_sumar_valor_total_items_especificaciones_tecnicas): el usuario ya no puede
            # escribir un presupuesto distinto al que resulta de sumar los
            # items, para que ambos numeros nunca se desincronicen. Se
            # recalcula del items_df en session_state en cada rerun de esta
            # seccion, no de un valor guardado, asi que siempre refleja el
            # estado actual de los items aunque se hayan editado despues de
            # la ultima vez que se vio esta seccion.
            st.session_state.especificaciones_tecnicas_presupuesto = _sumar_valor_total_items_especificaciones_tecnicas(
                _recalcular_items_especificaciones_tecnicas(st.session_state.especificaciones_tecnicas_items_df)
            )
            with st.container(key="especificaciones_tecnicas_metrica_presupuesto"):
                st.number_input(
                    "Presupuesto Referencial (USD)",
                    min_value=0.0,
                    format="%.2f",
                    key="especificaciones_tecnicas_presupuesto",
                    disabled=True,
                    help=(
                        "Se autocompleta con la Sumatoria Total de los ítems y no se puede editar "
                        "aquí. Se muestra en el documento con formato ecuatoriano, ej. "
                        "$ 9.106.285,46."
                    ),
                )
            st.markdown("**Requerimientos Adicionales Obligatorios**")
            st.session_state.especificaciones_tecnicas_cpc_df = st.data_editor(
                st.session_state.especificaciones_tecnicas_cpc_df,
                num_rows="dynamic",
                use_container_width=True,
                key="especificaciones_tecnicas_cpc_editor",
            )
            st.text_input(
                "Código CPC (detallar el código y la descripción del de mayor peso económico)",
                key="especificaciones_tecnicas_codigo_cpc_mayor_peso",
            )
            st.text_area("Alcance", key="especificaciones_tecnicas_alcance")
            st.text_input("Plazo de Ejecución: parcial y/o total (en días)", key="especificaciones_tecnicas_plazo")
            st.markdown("**Personal Técnico/Equipo de Trabajo/Recursos según corresponda**")
            st.text_area("1.- Personal Técnico Principal", key="especificaciones_tecnicas_personal_tecnico_principal")
            st.text_area(
                "2.- Personal Técnico Auxiliar o Secundario", key="especificaciones_tecnicas_personal_tecnico_auxiliar"
            )
            st.text_area("3.- Equipo de Trabajo", key="especificaciones_tecnicas_equipo_trabajo")
            st.text_area("4.- Recursos", key="especificaciones_tecnicas_recursos")
            st.text_area("Forma y condiciones de pago", key="especificaciones_tecnicas_forma_pago")
            st.text_input("Lugar y dirección de entrega/ejecución", key="especificaciones_tecnicas_lugar")

    elif tab_activa == NOMBRES_SECCIONES_ESPECIFICACIONES_TECNICAS[3]:
        with st.expander("Obligaciones y Garantías"):
            st.text_area("Obligaciones de la Entidad Contratante", key="especificaciones_tecnicas_obligaciones_entidad")
            st.text_area("Obligaciones de la Contratista", key="especificaciones_tecnicas_obligaciones_contratista")
            st.text_area(
                "Garantías técnicas, en el caso de que aplique", key="especificaciones_tecnicas_garantias_tecnicas"
            )
            st.number_input(
                "Monto USD de la Garantía de Responsabilidad Civil (mínimo USD 3.000)",
                min_value=3000.0,
                format="%.2f",
                value=None,
                key="especificaciones_tecnicas_monto_garantia_rc",
            )
            st.number_input(
                "Vigencia de la oferta (días)", min_value=0, step=1, value=90, key="especificaciones_tecnicas_vigencia_oferta"
            )
            st.text_input("Tipo de adjudicación", key="especificaciones_tecnicas_tipo_adjudicacion")
            st.caption(
                "El documento incluye, con el texto fijo del modelo institucional: Multas (1 por "
                "1000), Garantía de Fiel Cumplimiento y Garantía de Buen Uso de Anticipo, y "
                "Reajuste de Precios."
            )

        with st.expander("Administrador y Contactos"):
            st.markdown("**Administrador del Contrato**")
            col1, col2, col3 = st.columns(3)
            col1.text_input("Nombre del Administrador", key="especificaciones_tecnicas_admin_nombre")
            col2.text_input("Cargo del Administrador", key="especificaciones_tecnicas_admin_cargo")
            col3.text_input("Cédula del Administrador", key="especificaciones_tecnicas_admin_cedula")
            st.caption(
                f"El documento incluye, a continuación, la lista fija de "
                f"{len(TEXTO_ATRIBUCIONES_ADMINISTRADOR)} atribuciones numeradas del Administrador del "
                f"Contrato, más {len(TEXTO_ADMINISTRADOR_OBLIGACIONES_ADICIONALES)} obligaciones "
                f"adicionales en viñetas y el párrafo de cierre sobre cambio de administrador."
            )

            st.markdown("**Técnico que no interviene en la contratación**")
            col4, col5, col6 = st.columns(3)
            col4.text_input("Nombre del Técnico", key="especificaciones_tecnicas_tecnico_nombre")
            col5.text_input("Cargo del Técnico", key="especificaciones_tecnicas_tecnico_cargo")
            col6.text_input("Correo del Técnico", key="especificaciones_tecnicas_tecnico_correo")

            st.markdown("**Contacto**")
            col7, col8 = st.columns(2)
            col7.text_input("Dirección de contacto", key="especificaciones_tecnicas_direccion_contacto")
            col8.text_input("Teléfono de contacto", key="especificaciones_tecnicas_telefono_contacto")

            st.text_input("Proceso de contratación a aplicar", key="especificaciones_tecnicas_proceso_aplicar")
            st.markdown("**Análisis para definir la estrategia de adquisición**")
            st.caption(
                "Editor de texto enriquecido: puedes pegar tablas e imágenes copiadas "
                "directamente desde Excel o Word y se insertan en el documento manteniendo "
                "su estructura. Requiere conexión a internet (el editor se carga desde cdnjs)."
            )
            # value=... se reusa como `default` (ver tinymce_editor): si esta
            # seccion no se instancio en el rerun anterior, Streamlit
            # borra el estado del widget con key="especificaciones_tecnicas_analisis_estrategia_editor"
            # (mismo mecanismo que motivo _ESPECIFICACIONES_TECNICAS_CAMPOS_SIMPLES_PERSISTENTES,
            # aplicado tambien a componentes custom con key), y el componente
            # cae de vuelta a `default` -- por eso "especificaciones_tecnicas_analisis_estrategia_html"
            # tambien esta en esa lista, aunque este widget no sea uno de los
            # ~44 "simples": no quitar `value=` de aqui sin mantener ese respaldo.
            st.session_state["especificaciones_tecnicas_analisis_estrategia_html"] = tinymce_editor(
                value=st.session_state.get("especificaciones_tecnicas_analisis_estrategia_html", ""),
                height=350,
                key="especificaciones_tecnicas_analisis_estrategia_editor",
            )

        with st.expander("Evaluación y Calificación"):
            col1, col2 = st.columns(2)
            col1.number_input(
                "% mínimo de experiencia general requerido",
                min_value=0.0,
                max_value=100.0,
                value=None,
                key="especificaciones_tecnicas_pct_general",
            )
            col2.number_input(
                "% mínimo de experiencia específica requerido",
                min_value=0.0,
                max_value=100.0,
                value=None,
                key="especificaciones_tecnicas_pct_especifica",
            )
            st.text_input(
                "Título profesional requerido para el personal técnico",
                key="especificaciones_tecnicas_titulo_profesional",
            )
            st.text_area("Equipo de trabajo/recursos a evaluar", key="especificaciones_tecnicas_equipo_evaluar")
            st.selectbox(
                "Certificado de proveedor exclusivo o autorizado",
                ["No", "Sí"],
                key="especificaciones_tecnicas_certificado_proveedor",
            )
            st.selectbox("¿Aplica Patrimonio?", ["No", "Sí"], key="especificaciones_tecnicas_patrimonio_aplica")
            if st.session_state.get("especificaciones_tecnicas_patrimonio_aplica") == "Sí":
                st.caption(
                    "Se incluirán en el documento las 2 tablas fijas de rangos de Patrimonio "
                    "(Bienes y/o Servicios, y Obras)."
                )
            st.text_area(
                "Evaluación del análisis de estrategia de adquisición",
                key="especificaciones_tecnicas_evaluacion_estrategia",
            )
            st.text_area(
                "Otros parámetros de evaluación y calificación", key="especificaciones_tecnicas_otros_parametros"
            )
            st.caption(
                "El documento incluye, con texto y puntajes fijos del modelo institucional: la "
                "tabla de checklist Cumple/No Cumple, y la metodología de evaluación por puntaje "
                "(Experiencia General 10, Experiencia Específica 20, Experiencia del Personal "
                "Técnico 10, Oferta Económica 50, Valor Agregado Ecuatoriano 10, Total 100)."
            )

        with st.expander("Fecha y Firmas"):
            st.text_input("Fecha del documento", key="especificaciones_tecnicas_fecha")
            st.markdown("**Firmas de responsabilidad**")
            col_e1, col_e2, col_e3 = st.columns(3)
            col_e1.text_input("Elaborado por — Nombre", key="especificaciones_tecnicas_firma_elaborado_nombre")
            col_e2.text_input("Elaborado por — Cargo", key="especificaciones_tecnicas_firma_elaborado_cargo")
            col_e3.text_input("Elaborado por — Firmado por", key="especificaciones_tecnicas_firma_elaborado_firmado")

            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.text_input("Revisado por — Nombre", key="especificaciones_tecnicas_firma_revisado_nombre")
            col_r2.text_input("Revisado por — Cargo", key="especificaciones_tecnicas_firma_revisado_cargo")
            col_r3.text_input("Revisado por — Firmado por", key="especificaciones_tecnicas_firma_revisado_firmado")

            col_a1, col_a2, col_a3 = st.columns(3)
            col_a1.text_input(
                "Aprobado por — Nombre",
                value=FIRMA_APROBADO_POR_DEFECTO_NOMBRE,
                key="especificaciones_tecnicas_firma_aprobado_nombre",
            )
            col_a2.text_input(
                "Aprobado por — Cargo",
                value=FIRMA_APROBADO_POR_DEFECTO_CARGO,
                key="especificaciones_tecnicas_firma_aprobado_cargo",
            )
            col_a3.text_input("Aprobado por — Firmado por", key="especificaciones_tecnicas_firma_aprobado_firmado")

        st.divider()
        if st.button(":material/description: Descargar Especificaciones Técnicas en Word", key="especificaciones_tecnicas_generar", type="primary"):
            if st.session_state.especificaciones_tecnicas_items_df.empty:
                st.warning(
                    'Agrega al menos un ítem en la sección "Ítems y Presupuesto" '
                    "antes de generar el documento."
                )
            else:
                datos = _recolectar_datos_especificaciones_tecnicas()
                nombre_archivo = f"EspecificacionesTecnicas_{_slug_nombre_archivo(datos['objeto_contratacion'] or 'documento')}.docx"
                ruta_temporal = Path(tempfile.gettempdir()) / nombre_archivo
                generar_especificaciones_tecnicas(datos, ruta_temporal)
                st.session_state.especificaciones_tecnicas_docx_bytes = ruta_temporal.read_bytes()
                st.session_state.especificaciones_tecnicas_docx_nombre = nombre_archivo
                ruta_temporal.unlink(missing_ok=True)
                st.success("Documento generado correctamente.")

        if st.session_state.get("especificaciones_tecnicas_docx_bytes"):
            st.download_button(
                ":material/download: Descargar " + st.session_state.especificaciones_tecnicas_docx_nombre,
                data=st.session_state.especificaciones_tecnicas_docx_bytes,
                file_name=st.session_state.especificaciones_tecnicas_docx_nombre,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="especificaciones_tecnicas_descargar_docx",
            )

        st.divider()
        st.markdown("**Vista Previa**")
        st.caption(
            "Se actualiza automáticamente a medida que completas los datos en las otras "
            "secciones. Los campos vacíos se muestran en blanco, resaltados en amarillo."
        )
        _render_vista_previa_especificaciones_tecnicas(_recolectar_datos_especificaciones_tecnicas())

    _guardar_campos_simples_especificaciones_tecnicas()


def render_pagina_municipalidad_guayaquil(registros_totales: list[dict]) -> None:
    st.header(":material/location_city: Municipalidad de Guayaquil")
    registros_municipio = filtrar_por_entidad(registros_totales, ENTIDAD_MUNICIPALIDAD_GUAYAQUIL)
    if registros_municipio:
        render_contadores(registros_municipio)
        st.divider()
        render_metricas_resumen(registros_municipio)
        render_tabla_con_color(registros_municipio)
    else:
        st.info(f'No se encontraron procesos para "{ENTIDAD_MUNICIPALIDAD_GUAYAQUIL}".')

    st.divider()
    render_formularios_y_registro()


def render_pagina_configuracion() -> None:
    st.header(":material/settings: Configuración")
    render_vaciar_base_datos()


def main():
    st.set_page_config(page_title="SERCOP Analytics", layout="wide")
    _inyectar_estilos_sidebar()

    if "resultados" not in st.session_state:
        st.session_state.resultados = None
    if "pagina_activa" not in st.session_state:
        st.session_state.pagina_activa = "Dashboard"

    if st.session_state.get("mensaje_vaciado"):
        st.success(st.session_state.mensaje_vaciado)
        st.session_state.mensaje_vaciado = None

    render_navegacion_sidebar()

    # obtener_contrataciones() esta cacheada (ttl=30s), pero igual evitamos
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


if __name__ == "__main__":
    main()
