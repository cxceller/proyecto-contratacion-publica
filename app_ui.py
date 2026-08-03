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

from scripts.anexo1_generator import (
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
    TEXTO_ANALISIS_ESTRATEGIA_FIJO,
    TEXTO_ATRIBUCIONES_ADMINISTRADOR,
    TEXTO_CERTIFICADO_PROVEEDOR_EXCLUSIVO_INTRO,
    TEXTO_EXPERIENCIA_PERSONAL_TECNICO,
    TEXTO_GARANTIA_BUEN_USO_ANTICIPO,
    TEXTO_GARANTIA_FIEL_CUMPLIMIENTO,
    TEXTO_MULTAS,
    TEXTO_PARAMETROS_EVALUACION_INTRO,
    TEXTO_PATRIMONIO_INTRO,
    TEXTO_PUNTAJE_INTRO,
    TEXTO_REAJUSTE_PRECIOS,
    TEXTO_TIEMPO_EXISTENCIA_LEGAL,
    TITULO_ANEXO_FIJO,
    TITULO_PROCESO_FIJO,
    generar_anexo1,
)
from scripts.formato_ec import formatear_moneda_ec, formatear_numero_ec

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
    ("Dashboard", "📊"),
    ("Procesos", "📋"),
    ("Reportes", "📄"),
    ("Municipalidad de Guayaquil", "🏙️"),
    ("Configuración", "⚙️"),
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


@st.cache_data
def cargar_geojson_provincias() -> dict:
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


def preparar_dataframe(registros: list[dict]) -> pd.DataFrame:
    """Construye el DataFrame base del dashboard analitico: parsea fecha de
    publicacion en año/mes y deriva el 'tipo de compra' del objeto."""
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
        if st.button("🧹 Limpiar filtros", key="dashboard_limpiar_filtros", use_container_width=True):
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
        "💡 Las celdas con texto largo (ej. Objeto del Proceso) se truncan con "
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
        label="⬇ Descargar tabla (CSV)",
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
    st.subheader("📄 Generación de Reportes Automáticos")
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
    if st.button("🧹 Limpiar filtros", key="reportes_limpiar_filtros"):
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
        enviado = st.form_submit_button("📝 Generar Reporte Word", type="primary", use_container_width=True)

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
            label="⬇ Descargar Reporte_SERCOP.docx",
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
    st.subheader("⚠️ Zona de peligro")

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
            if st.button("⚠️ Vaciar Base de Datos", use_container_width=True):
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
                "🗑️ Confirmar vaciado definitivo",
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
                    st.session_state.mensaje_vaciado = "✅ Base de datos vaciada por completo."
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
        .sercop-brand {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.25rem 0 1.5rem 0;
            font-size: 1.05rem;
            font-weight: 700;
            color: {COLOR_SIDEBAR_TEXTO_ACTIVO} !important;
            letter-spacing: 0.02em;
        }}
        .sercop-brand-icon {{
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
        st.markdown(
            '<div class="sercop-brand">'
            '<span class="sercop-brand-icon">🏛️</span>'
            '<span>SERCOP ANALYTICS</span>'
            "</div>",
            unsafe_allow_html=True,
        )
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


def render_pagina_dashboard(registros_totales: list[dict]) -> None:
    """Revelacion progresiva: por defecto solo se ven los contadores y los
    3 KPIs principales (Procesos, Presupuesto, Adjudicado); el resto del
    detalle (evolucion mensual, provincia, mapa, treemap, tablas resumen)
    queda agrupado en pestañas, para no abrumar con todo el dashboard de
    una sola vez."""
    render_contadores(registros_totales)
    st.divider()
    st.header("📊 Dashboard Analítico")
    df_totales = preparar_dataframe(registros_totales)
    df_filtrado = render_filtros_dashboard(df_totales)
    render_kpis_dashboard(df_filtrado)

    tab_mensual, tab_provincia, tab_treemap, tab_resumen = st.tabs(
        [
            "📅 Ver detalle por mes",
            "📍 Ver detalle por provincia",
            "🌳 Ver Provincia → Estado",
            "🧾 Ver resumen por estado y tipo de compra",
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


CLAVES_FILTRO_PROCESOS = [
    "procesos_estado",
    "procesos_fecha_inicio",
    "procesos_fecha_fin",
    "procesos_palabra_clave",
]


def render_pagina_procesos(registros_totales: list[dict]) -> None:
    st.header("📋 Procesos de Contratación")

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
    buscar = col_buscar.button("🔍 Buscar", type="primary", use_container_width=True)
    limpiar = col_limpiar.button("🧹 Limpiar filtros", use_container_width=True)

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
    st.header("📄 Reportes")
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


COLUMNAS_ITEMS_ANEXO1 = [
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


@st.cache_data
def _cargar_catalogo_cpc() -> dict[str, str]:
    """Catalogo oficial 'Listado de CPC N9' (SERCOP, ~30.000 codigos):
    codigo -> descripcion. Se carga UNA sola vez por sesion (cache_data) y
    se expone como dict, no como DataFrame, para que la busqueda del
    autocompletado sea O(1) por codigo en vez de recorrer/filtrar
    30.000 filas en cada guardado."""
    df = pd.read_csv(CATALOGO_CPC_PATH, dtype=str)
    return dict(zip(df["codigo_cpc"].str.strip(), df["descripcion_cpc"].str.strip()))


COLUMNAS_VISIBLES_ITEMS_ANEXO1 = [
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


def _asignar_fila_ids_anexo1(df: pd.DataFrame) -> pd.DataFrame:
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
        st.session_state.anexo1_siguiente_fila_id += 1
        df.at[indice, "_fila_id"] = st.session_state.anexo1_siguiente_fila_id
    return df


def _autocompletar_descripcion_cpc(
    df_nuevo: pd.DataFrame, df_anterior: pd.DataFrame, catalogo: dict[str, str]
) -> tuple[pd.DataFrame, list[str]]:
    """Autocompleta 'Descripción CPC' fila por fila cuando el 'Número CPC'
    de ESA fila (identificada por su '_fila_id' estable, no por su
    posicion -- ver _asignar_fila_ids_anexo1) cambio respecto al guardado
    anterior, y el codigo se encuentra en el catalogo oficial. Si el
    codigo no cambio, se respeta lo que el usuario haya dejado en
    'Descripción CPC' (no se sobreescribe). Si el codigo cambio pero NO
    esta en el catalogo, tampoco se sobreescribe -- se reporta como no
    encontrado para mostrar una advertencia. df_nuevo debe venir ya
    procesado por _asignar_fila_ids_anexo1 (toda fila, incluidas las
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


def _dataframe_items_anexo1_vacio() -> pd.DataFrame:
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


def _dataframe_cpc_anexo1_vacio() -> pd.DataFrame:
    return pd.DataFrame({"Código CPC": pd.Series(dtype="str"), "Descripción del CPC": pd.Series(dtype="str")})


def _recalcular_items_anexo1(df: pd.DataFrame) -> pd.DataFrame:
    """Recalcula Item # (posicion) y Valor Total = Cantidad Solicitada *
    Valor Unitario tras cada edicion -- ninguna de las dos columnas es
    editable directamente por el usuario (ver column_config en
    render_formularios_y_registro). "Tipo" tambien se rellena con "Bien"
    por defecto para filas nuevas (el selector Bien/Servicio es POR
    ITEM, via SelectboxColumn, no un unico selector global)."""
    df = df.reset_index(drop=True).copy()
    df["Ítem"] = df.index + 1
    if "Tipo" not in df.columns:
        df["Tipo"] = "Bien"
    df["Tipo"] = df["Tipo"].fillna("Bien")
    cantidad = pd.to_numeric(df["Cantidad Solicitada"], errors="coerce").fillna(0)
    valor_unitario = pd.to_numeric(df["Valor Unitario"], errors="coerce").fillna(0)
    df["Valor Total"] = (cantidad * valor_unitario).round(2)
    return df


def _formatear_numero_anexo1(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return formatear_numero_ec(valor)


def _formatear_moneda_anexo1(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return formatear_numero_ec(valor, decimales=2)


def _specs_vacias_anexo1(tipo: str) -> dict:
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


def _recolectar_datos_anexo1() -> dict:
    """Arma el mismo diccionario `datos` que consume generar_anexo1(), a
    partir de TODO lo que el usuario ya cargo en session_state. Se usa
    tanto para el boton de descarga en Word como para la Vista Previa,
    para garantizar que ambos muestren exactamente lo mismo."""
    df_items = _recalcular_items_anexo1(st.session_state.anexo1_items_df)
    specs = st.session_state.anexo1_specs
    items_datos = []
    for indice, fila in df_items.reset_index(drop=True).iterrows():
        tipo_fila = fila.get("Tipo") or "Bien"
        item = {
            "tipo": tipo_fila,
            "descripcion": str(fila.get("Descripción") or ""),
            "unidad_medida": str(fila.get("Unidad de Medida") or ""),
            "cantidad_solicitada": _formatear_numero_anexo1(fila.get("Cantidad Solicitada")),
            "valor_unitario": _formatear_moneda_anexo1(fila.get("Valor Unitario")),
            "valor_total": _formatear_moneda_anexo1(fila.get("Valor Total")),
            "descripcion_cpc": str(fila.get("Descripción CPC") or ""),
            "numero_cpc": str(fila.get("Número CPC") or ""),
        }
        spec = specs[indice] if indice < len(specs) else _specs_vacias_anexo1(tipo_fila)
        item.update(spec)
        items_datos.append(item)

    df_cpc = st.session_state.anexo1_cpc_df
    requerimientos_cpc = [
        {"cpc": str(fila.get("Código CPC") or ""), "descripcion": str(fila.get("Descripción del CPC") or "")}
        for _, fila in df_cpc.iterrows()
    ]

    return {
        "objeto_contratacion": st.session_state.get("anexo1_objeto_contratacion", ""),
        "items": items_datos,
        "presupuesto_referencial": formatear_moneda_ec(st.session_state.get("anexo1_presupuesto")),
        "requerimientos_cpc": requerimientos_cpc,
        "codigo_cpc_mayor_peso": st.session_state.get("anexo1_codigo_cpc_mayor_peso", ""),
        "alcance": st.session_state.get("anexo1_alcance", ""),
        "plazo_ejecucion": st.session_state.get("anexo1_plazo", ""),
        "personal_tecnico_principal": st.session_state.get("anexo1_personal_tecnico_principal", ""),
        "personal_tecnico_auxiliar": st.session_state.get("anexo1_personal_tecnico_auxiliar", ""),
        "equipo_trabajo": st.session_state.get("anexo1_equipo_trabajo", ""),
        "recursos": st.session_state.get("anexo1_recursos", ""),
        "forma_condiciones_pago": st.session_state.get("anexo1_forma_pago", ""),
        "lugar_direccion": st.session_state.get("anexo1_lugar", ""),
        "obligaciones_entidad": st.session_state.get("anexo1_obligaciones_entidad", ""),
        "obligaciones_contratista": st.session_state.get("anexo1_obligaciones_contratista", ""),
        "garantias_tecnicas": st.session_state.get("anexo1_garantias_tecnicas", ""),
        "monto_garantia_responsabilidad_civil": _formatear_moneda_anexo1(
            st.session_state.get("anexo1_monto_garantia_rc")
        ),
        "vigencia_oferta_dias": _formatear_numero_anexo1(st.session_state.get("anexo1_vigencia_oferta")),
        "tipo_adjudicacion": st.session_state.get("anexo1_tipo_adjudicacion", ""),
        "analisis_estrategia": st.session_state.get("anexo1_analisis_estrategia", ""),
        "administrador_nombre": st.session_state.get("anexo1_admin_nombre", ""),
        "administrador_cargo": st.session_state.get("anexo1_admin_cargo", ""),
        "administrador_cedula": st.session_state.get("anexo1_admin_cedula", ""),
        "tecnico_no_interviene_nombre": st.session_state.get("anexo1_tecnico_nombre", ""),
        "tecnico_no_interviene_cargo": st.session_state.get("anexo1_tecnico_cargo", ""),
        "tecnico_no_interviene_correo": st.session_state.get("anexo1_tecnico_correo", ""),
        "direccion_contacto": st.session_state.get("anexo1_direccion_contacto", ""),
        "telefono_contacto": st.session_state.get("anexo1_telefono_contacto", ""),
        "proceso_contratacion_aplicar": st.session_state.get("anexo1_proceso_aplicar", ""),
        "pct_experiencia_general": _formatear_numero_anexo1(st.session_state.get("anexo1_pct_general")),
        "pct_experiencia_especifica": _formatear_numero_anexo1(st.session_state.get("anexo1_pct_especifica")),
        "titulo_profesional_personal_tecnico": st.session_state.get("anexo1_titulo_profesional", ""),
        "equipo_trabajo_recursos_evaluar": st.session_state.get("anexo1_equipo_evaluar", ""),
        "certificado_proveedor_exclusivo": st.session_state.get("anexo1_certificado_proveedor", "No"),
        "patrimonio_aplica": st.session_state.get("anexo1_patrimonio_aplica", "No"),
        "evaluacion_estrategia_adquisicion": st.session_state.get("anexo1_evaluacion_estrategia", ""),
        "otros_parametros_evaluacion": st.session_state.get("anexo1_otros_parametros", ""),
        "fecha_documento": st.session_state.get("anexo1_fecha", ""),
        "firmas": {
            "elaborado": {
                "nombre": st.session_state.get("anexo1_firma_elaborado_nombre", ""),
                "cargo": st.session_state.get("anexo1_firma_elaborado_cargo", ""),
                "firmado_por": st.session_state.get("anexo1_firma_elaborado_firmado", ""),
            },
            "revisado": {
                "nombre": st.session_state.get("anexo1_firma_revisado_nombre", ""),
                "cargo": st.session_state.get("anexo1_firma_revisado_cargo", ""),
                "firmado_por": st.session_state.get("anexo1_firma_revisado_firmado", ""),
            },
            "aprobado": {
                "nombre": st.session_state.get("anexo1_firma_aprobado_nombre") or FIRMA_APROBADO_POR_DEFECTO_NOMBRE,
                "cargo": st.session_state.get("anexo1_firma_aprobado_cargo") or FIRMA_APROBADO_POR_DEFECTO_CARGO,
                "firmado_por": st.session_state.get("anexo1_firma_aprobado_firmado", ""),
            },
        },
    }


# --- Vista previa HTML (pestaña 5): reutiliza los mismos textos fijos
# que scripts/anexo1_generator.py (importados arriba) para que la
# previsualizacion y el .docx final coincidan siempre. No pretende ser
# pixel-perfect con el Word (eso ya lo garantiza generar_anexo1 en si);
# el objetivo es que el usuario vea la estructura, el contenido y los
# resaltados de color completos sin tener que descargar el archivo. ---
_LLENAR = '<span style="background:#fff59d; padding:0 2px;">LLENAR</span>'


def _html_valor_o_llenar(valor: str) -> str:
    return html.escape(valor) if valor else _LLENAR


def _html_fila_ancho_completo(contenido_html: str, *, fondo: str = "white", negrita: bool = False) -> str:
    """Una fila-tabla de ancho completo, con borde solido en las 4 caras.
    margin:0 0 -1px 0 hace que el borde inferior de una fila se superponga
    con el superior de la siguiente (misma tecnica que usa la tabla real
    de items), para que la Vista Previa se vea como una sola hoja/tabla
    institucional continua en vez de parrafos sueltos."""
    peso = "font-weight:bold;" if negrita else ""
    return (
        '<table style="width:100%; border-collapse:collapse; margin:0 0 -1px 0;">'
        f'<tr><td style="border:1px solid #000; padding:5px 8px; background:{fondo}; {peso}">'
        f"{contenido_html}</td></tr></table>"
    )


def _html_campo(etiqueta: str, valor: str) -> str:
    contenido = (
        '<table style="width:100%; border-collapse:collapse;"><tr>'
        f'<td style="border:none; padding:0; font-weight:bold; width:38%; vertical-align:top;">'
        f"{html.escape(etiqueta)}</td>"
        f'<td style="border:none; padding:0; vertical-align:top;">'
        f'<span style="background:#fff59d; padding:0 2px;">{_html_valor_o_llenar(valor)}</span></td>'
        "</tr></table>"
    )
    return _html_fila_ancho_completo(contenido)


def _html_parrafo_fijo(texto: str) -> str:
    parrafos = "".join(
        f'<p style="margin:3px 0; text-align:justify;">{html.escape(linea)}</p>' for linea in texto.split("\n")
    )
    return _html_fila_ancho_completo(parrafos)


def _html_titulo(texto: str) -> str:
    return _html_fila_ancho_completo(html.escape(texto), fondo="#f2f2f2", negrita=True)


def _html_lista_numerada(items: list[str]) -> str:
    parrafos = "".join(
        f'<p style="margin:2px 0; text-align:justify; font-size:12px;">{numero}. {html.escape(texto)}</p>'
        for numero, texto in enumerate(items, start=1)
    )
    return _html_fila_ancho_completo(parrafos)


def _html_lista_vinetas(items: list[str]) -> str:
    parrafos = "".join(
        f'<p style="margin:2px 0; text-align:justify; font-size:12px;">● {html.escape(texto)}</p>'
        for texto in items
    )
    return _html_fila_ancho_completo(parrafos)


def _html_tabla(encabezados: list[str], filas: list[list[str]]) -> str:
    ths = "".join(
        f'<th style="border:1px solid #000; padding:3px; background:#f2f2f2; font-size:11px;">{html.escape(h)}</th>'
        for h in encabezados
    )
    trs = "".join(
        "<tr>" + "".join(f'<td style="border:1px solid #000; padding:3px; font-size:11px;">{html.escape(str(v))}</td>' for v in fila) + "</tr>"
        for fila in filas
    )
    return f'<table style="width:100%; border-collapse:collapse; margin-bottom:8px;"><tr>{ths}</tr>{trs}</table>'


def _html_bloque_item(numero: int, item: dict) -> str:
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
        f'<th style="border:1px solid #000; padding:2px; background:#f2f2f2; font-size:10px;">{html.escape(h)}</th>'
        for h in encabezados
    )
    fila_datos = "".join(
        f'<td style="border:1px solid #000; padding:2px; font-size:10px;">{_html_valor_o_llenar(str(v)) if not v else html.escape(str(v))}</td>'
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
                f'{_html_valor_o_llenar(item.get(clave, ""))}</p>'
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
                f'<tr><td style="border:1px solid #000; padding:2px; font-weight:bold; font-size:10px;">'
                f'{html.escape(p.get("nombre",""))}</td>'
                f'<td style="border:1px solid #000; padding:2px; font-size:10px;">{html.escape(p.get("valor",""))}</td></tr>'
                for p in parametros
            )
            contenido_specs += f'<table style="width:100%; border-collapse:collapse;">{filas_parametros}</table>'

    return (
        '<table style="width:100%; border-collapse:collapse; margin-bottom:2px;">'
        f"<tr>{fila_encabezado}</tr>"
        f"<tr>{fila_datos}</tr>"
        '<tr>'
        '<td style="border:1px solid #000; padding:3px; font-weight:bold; text-align:center; font-size:11px;">PARÁMETROS</td>'
        '<td colspan="7" style="border:1px solid #000; padding:3px; font-weight:bold; text-align:center; font-size:11px;">ESPECIFICACIONES TÉCNICAS</td>'
        "</tr>"
        "<tr>"
        f'<td style="border:1px solid #000; padding:3px; font-weight:bold; text-align:center; font-size:11px;">{etiqueta_label}</td>'
        f'<td colspan="7" style="border:1px solid #000; padding:5px;">{contenido_specs}</td>'
        "</tr>"
        "</table>"
    )


@st.cache_data
def _imagenes_anexo1_base64() -> tuple[str, str]:
    return (
        base64.b64encode(IMAGEN_ENCABEZADO.read_bytes()).decode(),
        base64.b64encode(IMAGEN_PIE_PAGINA.read_bytes()).decode(),
    )


def _render_vista_previa_anexo1(datos: dict) -> None:
    encabezado_b64, pie_b64 = _imagenes_anexo1_base64()

    partes = [
        '<div style="background:white; color:#111; padding:20px; border:1px solid #ccc; '
        'font-family: Arial, sans-serif; max-height:75vh; overflow-y:auto;">',
        f'<img src="data:image/jpeg;base64,{encabezado_b64}" style="width:100%; margin-bottom:10px;">',
        '<table style="width:100%; border-collapse:collapse; text-align:center; font-weight:bold; margin-bottom:14px;">',
        f'<tr><td style="border:1px solid #000; padding:6px;">{html.escape(TITULO_ANEXO_FIJO)}</td></tr>',
        f'<tr><td style="border:1px solid #000; padding:6px;">{html.escape(TITULO_PROCESO_FIJO)}</td></tr>',
        f'<tr><td style="border:1px solid #000; padding:6px;">{html.escape(COORDINACION_FIJA)}</td></tr>',
        f'<tr><td style="border:1px solid #000; padding:8px; background:#fff59d;">'
        f'{_html_valor_o_llenar(datos.get("objeto_contratacion", ""))}</td></tr>',
        "</table>",
    ]

    items = datos.get("items", [])
    if not items:
        partes.append('<p style="color:#999;">(sin ítems agregados todavía en la pestaña "2. Ítems y Valores")</p>')
    for numero, item in enumerate(items, start=1):
        partes.append(_html_bloque_item(numero, item))

    partes.append(_html_titulo("CONDICIONES LEGALES Y ADMINISTRATIVAS"))
    partes.append(_html_campo("PRESUPUESTO REFERENCIAL", datos.get("presupuesto_referencial", "")))

    partes.append(_html_titulo("REQUERIMIENTOS ADICIONALES OBLIGATORIOS"))
    requerimientos = datos.get("requerimientos_cpc") or [{"cpc": "", "descripcion": ""}]
    partes.append(
        _html_tabla(
            ["CPC", "DESCRIPCIÓN DEL CPC"],
            [[r.get("cpc") or "LLENAR", r.get("descripcion") or "LLENAR"] for r in requerimientos],
        )
    )

    partes.append(_html_campo("CÓDIGO CPC (MAYOR PESO ECONÓMICO)", datos.get("codigo_cpc_mayor_peso", "")))
    partes.append(_html_campo("ALCANCE", datos.get("alcance", "")))
    partes.append(_html_campo("PLAZO DE EJECUCIÓN (DÍAS)", datos.get("plazo_ejecucion", "")))
    partes.append(_html_titulo("PERSONAL TÉCNICO/EQUIPO DE TRABAJO/RECURSOS SEGÚN CORRESPONDA"))
    partes.append(_html_campo("1.- Personal Técnico Principal", datos.get("personal_tecnico_principal", "")))
    partes.append(
        _html_campo("2.- Personal Técnico Auxiliar o Secundario", datos.get("personal_tecnico_auxiliar", ""))
    )
    partes.append(_html_campo("3.- Equipo de Trabajo", datos.get("equipo_trabajo", "")))
    partes.append(_html_campo("4.- Recursos", datos.get("recursos", "")))
    partes.append(_html_campo("FORMA Y CONDICIONES DE PAGO", datos.get("forma_condiciones_pago", "")))
    partes.append(_html_campo("LUGAR Y DIRECCIÓN DE ENTREGA/EJECUCIÓN", datos.get("lugar_direccion", "")))

    partes.append(_html_titulo("MULTAS"))
    partes.append(_html_parrafo_fijo(TEXTO_MULTAS))

    partes.append(_html_titulo("OBLIGACIONES DE LAS PARTES"))
    partes.append(_html_campo("OBLIGACIONES DE LA ENTIDAD CONTRATANTE", datos.get("obligaciones_entidad", "")))
    partes.append(_html_campo("OBLIGACIONES DE LA CONTRATISTA", datos.get("obligaciones_contratista", "")))

    partes.append(_html_titulo("GARANTÍAS TÉCNICAS, EN EL CASO DE QUE APLIQUE"))
    partes.append(_html_campo("Garantías técnicas", datos.get("garantias_tecnicas", "")))

    partes.append(_html_titulo("GARANTÍAS ADICIONALES, EN EL CASO DE QUE APLIQUE"))
    partes.append(_html_parrafo_fijo(TEXTO_GARANTIA_FIEL_CUMPLIMIENTO))
    partes.append(_html_parrafo_fijo(TEXTO_GARANTIA_BUEN_USO_ANTICIPO))
    partes.append(
        _html_fila_ancho_completo(
            '<p style="margin:3px 0; font-weight:bold;">GARANTÍA DE RESPONSABILIDAD CIVIL</p>'
            f'<p style="margin:3px 0; text-align:justify;">Al momento de suscribir el contrato de '
            f'"{_html_valor_o_llenar(datos.get("objeto_contratacion", ""))}", la contratista deberá '
            f'justificar que cuenta con una póliza de responsabilidad civil con un valor asegurado '
            f'mínimo de USD {_html_valor_o_llenar(datos.get("monto_garantia_responsabilidad_civil", ""))} '
            f"por evento (texto completo en el documento final).</p>"
        )
    )

    partes.append(_html_titulo("VIGENCIA DE LA OFERTA"))
    partes.append(_html_campo("Días de vigencia", datos.get("vigencia_oferta_dias", "")))

    partes.append(_html_titulo("REAJUSTE DE PRECIOS"))
    partes.append(_html_parrafo_fijo(TEXTO_REAJUSTE_PRECIOS))

    partes.append(_html_campo("TIPO DE ADJUDICACIÓN", datos.get("tipo_adjudicacion", "")))

    partes.append(_html_titulo("ADMINISTRADOR DEL CONTRATO"))
    partes.append(_html_campo("Nombre", datos.get("administrador_nombre", "")))
    partes.append(_html_campo("Cargo", datos.get("administrador_cargo", "")))
    partes.append(_html_campo("Cédula", datos.get("administrador_cedula", "")))
    partes.append(
        '<p style="margin:3px 0; text-align:justify;">Para los efectos deberá cumplir con las '
        "siguientes atribuciones:</p>"
    )
    partes.append(_html_lista_numerada(TEXTO_ATRIBUCIONES_ADMINISTRADOR))
    partes.append(_html_parrafo_fijo(TEXTO_ADMINISTRADOR_OBLIGACIONES_INTRO))
    partes.append(_html_lista_vinetas(TEXTO_ADMINISTRADOR_OBLIGACIONES_ADICIONALES))
    partes.append(_html_parrafo_fijo(TEXTO_ADMINISTRADOR_CIERRE))

    partes.append(_html_titulo("TÉCNICO QUE NO INTERVIENE EN LA CONTRATACIÓN"))
    partes.append(_html_campo("Nombre", datos.get("tecnico_no_interviene_nombre", "")))
    partes.append(_html_campo("Cargo", datos.get("tecnico_no_interviene_cargo", "")))
    partes.append(_html_campo("Correo", datos.get("tecnico_no_interviene_correo", "")))
    partes.append(_html_campo("Dirección de contacto", datos.get("direccion_contacto", "")))
    partes.append(_html_campo("Teléfono de contacto", datos.get("telefono_contacto", "")))

    partes.append(_html_titulo("ANÁLISIS PARA DEFINIR LA ESTRATÉGIA DE ADQUISICIÓN"))
    partes.append(_html_parrafo_fijo(TEXTO_ANALISIS_ESTRATEGIA_FIJO))
    partes.append(_html_campo("Análisis específico de la contratación", datos.get("analisis_estrategia", "")))
    partes.append(_html_campo("PROCESO DE CONTRATACIÓN A APLICAR", datos.get("proceso_contratacion_aplicar", "")))

    partes.append(_html_titulo("PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN"))
    partes.append(_html_parrafo_fijo(TEXTO_PARAMETROS_EVALUACION_INTRO))
    partes.append(_html_campo("% experiencia general mínima", datos.get("pct_experiencia_general", "")))
    partes.append(_html_campo("% experiencia específica mínima", datos.get("pct_experiencia_especifica", "")))
    partes.append(_html_campo("Título profesional del personal técnico", datos.get("titulo_profesional_personal_tecnico", "")))
    partes.append(_html_titulo("EXPERIENCIA DEL PERSONAL TÉCNICO"))
    partes.append(_html_parrafo_fijo(TEXTO_EXPERIENCIA_PERSONAL_TECNICO))
    partes.append(_html_campo("EQUIPO DE TRABAJO/RECURSOS A EVALUAR", datos.get("equipo_trabajo_recursos_evaluar", "")))
    partes.append(
        _html_campo(
            "CERTIFICADO DE PROVEEDOR EXCLUSIVO O AUTORIZADO",
            datos.get("certificado_proveedor_exclusivo", "No"),
        )
    )

    partes.append(_html_titulo("PATRIMONIO"))
    patrimonio_aplica = datos.get("patrimonio_aplica", "No")
    partes.append(_html_campo("¿Aplica?", patrimonio_aplica))
    if patrimonio_aplica == "Sí":
        partes.append(_html_parrafo_fijo(TEXTO_PATRIMONIO_INTRO))
        partes.append(_html_titulo("Bienes y/o Servicios"))
        partes.append(_html_tabla(TABLA_PATRIMONIO_ENCABEZADO, TABLA_PATRIMONIO_BIENES_SERVICIOS))
        partes.append(_html_titulo("Obras"))
        partes.append(_html_tabla(TABLA_PATRIMONIO_ENCABEZADO, TABLA_PATRIMONIO_OBRAS))

    partes.append(_html_titulo("TIEMPO DE EXISTENCIA LEGAL DE PERSONAS JURÍDICAS"))
    partes.append(_html_parrafo_fijo(TEXTO_TIEMPO_EXISTENCIA_LEGAL))

    partes.append(_html_titulo("METODOLOGÍA DE EVALUACIÓN DE OFERTA (CUMPLE/NO CUMPLE)"))
    partes.append(
        _html_tabla(TABLA_CHECKLIST_ENCABEZADO, [[c, "", "", ""] for c in TABLA_CHECKLIST_CRITERIOS_FIJOS])
    )

    partes.append(_html_campo("EVALUACIÓN DEL ANÁLISIS DE ESTRATEGIA DE ADQUISICIÓN", datos.get("evaluacion_estrategia_adquisicion", "")))
    partes.append(_html_campo("OTROS PARÁMETROS DE EVALUACIÓN Y CALIFICACIÓN", datos.get("otros_parametros_evaluacion", "")))

    partes.append(_html_titulo("METODOLOGÍA DE EVALUACIÓN DE OFERTA POR PUNTAJE"))
    partes.append(_html_parrafo_fijo(TEXTO_PUNTAJE_INTRO))
    partes.append(_html_tabla(TABLA_PUNTAJE_ENCABEZADO, TABLA_PUNTAJE_FIJA))

    partes.append(_html_campo("FECHA", datos.get("fecha_documento", "")))

    firmas = datos.get("firmas", {})
    partes.append(_html_titulo("FIRMAS DE RESPONSABILIDAD"))
    filas_firmas = []
    for clave, etiqueta in (("elaborado", "Elaborado por"), ("revisado", "Revisado por"), ("aprobado", "Aprobado por")):
        d = firmas.get(clave, {})
        filas_firmas.append(
            [etiqueta, d.get("nombre") or "LLENAR", d.get("cargo") or "LLENAR", d.get("firmado_por") or "LLENAR"]
        )
    partes.append(_html_tabla(["", "Nombre", "Cargo", "Firmado por"], filas_firmas))

    partes.append(f'<img src="data:image/jpeg;base64,{pie_b64}" style="width:100%; margin-top:14px;">')
    partes.append("</div>")

    st.markdown("".join(partes), unsafe_allow_html=True)


def render_formularios_y_registro() -> None:
    """Subseccion "Formularios y Registro": genera el .docx (y la tabla
    de items en Excel) del Anexo 1 - Especificaciones Tecnicas para los
    Procesos de Bienes, replicando el formato exacto de un modelo Word
    de referencia (ver scripts/anexo1_generator.py). El encabezado fijo,
    la tabla de items con calculo automatico y su tipo Bien/Servicio POR
    ITEM, las especificaciones tecnicas condicionales, ~30 campos de
    condiciones legales (organizados en expanders) y una vista previa en
    vivo se organizan en pestañas para no ser un formulario gigante."""
    st.subheader("📝 Formularios y Registro")
    st.caption(
        "Genera el Anexo 1 - Especificaciones Técnicas para los Procesos de Bienes, "
        "con el mismo formato del modelo institucional."
    )

    if "anexo1_items_df" not in st.session_state:
        st.session_state.anexo1_items_df = _dataframe_items_anexo1_vacio()
    if "anexo1_items_editor_version" not in st.session_state:
        st.session_state.anexo1_items_editor_version = 0
    if "anexo1_siguiente_fila_id" not in st.session_state:
        st.session_state.anexo1_siguiente_fila_id = 0
    if "anexo1_cpc_df" not in st.session_state:
        st.session_state.anexo1_cpc_df = _dataframe_cpc_anexo1_vacio()
    if "anexo1_specs" not in st.session_state:
        st.session_state.anexo1_specs = []
    if "anexo1_siguiente_param_id" not in st.session_state:
        st.session_state.anexo1_siguiente_param_id = 0

    # st.tabs() nativo no acepta key/session_state: su pestaña activa se
    # rastrea solo en el frontend, y se sabe que se resetea a la primera
    # pestaña cuando el script hace st.rerun() manual (como los botones
    # "Añadir/Quitar item"/"Añadir/Quitar parametro" mas abajo) en vez de
    # un rerun nativo disparado por el propio widget editado. Un selector
    # respaldado en session_state (mismo patron ya probado en
    # render_navegacion_sidebar) elimina ese reseteo de forma
    # deterministica, sin depender de como Streamlit maneje cada rerun.
    NOMBRES_TABS_ANEXO1 = [
        "1. Datos Generales",
        "2. Ítems y Valores",
        "3. Especificaciones Técnicas",
        "4. Condiciones Legales y Descarga",
        "5. Vista Previa",
    ]
    if "anexo1_tab_activa" not in st.session_state:
        st.session_state.anexo1_tab_activa = NOMBRES_TABS_ANEXO1[0]
    tab_activa = st.radio(
        "Sección",
        NOMBRES_TABS_ANEXO1,
        key="anexo1_tab_activa",
        horizontal=True,
        label_visibility="collapsed",
    )

    if tab_activa == NOMBRES_TABS_ANEXO1[0]:
        st.markdown("**Encabezado fijo del documento**")
        st.info(f"{TITULO_ANEXO_FIJO}\n\n{TITULO_PROCESO_FIJO}\n\n{COORDINACION_FIJA}")
        st.text_area(
            'Objeto de contratación (se resalta en amarillo en el documento generado)',
            placeholder="Ej: SUMINISTRO, INSTALACIÓN, MANTENIMIENTO PREVENTIVO Y REPOTENCIACIÓN DE...",
            key="anexo1_objeto_contratacion",
        )

    elif tab_activa == NOMBRES_TABS_ANEXO1[1]:
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
        with st.form("anexo1_form_items", clear_on_submit=False):
            df_editado = st.data_editor(
                st.session_state.anexo1_items_df,
                num_rows="dynamic",
                use_container_width=True,
                key=f"anexo1_data_editor_{st.session_state.anexo1_items_editor_version}",
                column_order=COLUMNAS_VISIBLES_ITEMS_ANEXO1,
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
            guardar_items = st.form_submit_button("💾 Guardar Ítems", type="primary")

        if guardar_items:
            # Al guardar SI se recalcula (a diferencia de antes): "Ítem"
            # y "Valor Total" quedan bien formados (sin None) antes de
            # persistir a session_state, y el key con version bumped
            # fuerza al grid a remontarse desde cero con ese dataframe ya
            # limpio en el siguiente rerun -- no hay diff incremental que
            # pueda desincronizarse. _asignar_fila_ids_anexo1 (identidad
            # estable por fila) y el autocompletado de "Descripción CPC"
            # corren ANTES de ese recalculo/remount, por la misma razon:
            # nunca se reintroduce un dataframe a medio transformar en el
            # mismo key.
            df_con_ids = _asignar_fila_ids_anexo1(df_editado)
            df_autocompletado, cpc_no_encontrados = _autocompletar_descripcion_cpc(
                df_con_ids, st.session_state.anexo1_items_df, _cargar_catalogo_cpc()
            )
            st.session_state.anexo1_items_df = _recalcular_items_anexo1(df_autocompletado)
            st.session_state.anexo1_items_editor_version += 1
            if cpc_no_encontrados:
                codigos_unicos = ", ".join(sorted(set(cpc_no_encontrados)))
                st.warning(f"Código(s) CPC no encontrado(s) en el catálogo: {codigos_unicos}")
            st.success("Ítems guardados.")
            st.rerun()

        # "_fila_id" es un detalle interno (identidad estable entre
        # guardados, ver _asignar_fila_ids_anexo1): se excluye de la
        # vista de solo lectura y del Excel exportado, igual que ya se
        # excluye del data_editor via column_order.
        df_items_calculado = _recalcular_items_anexo1(st.session_state.anexo1_items_df)
        df_items_visible = df_items_calculado.drop(columns=["_fila_id"], errors="ignore")
        st.dataframe(
            df_items_visible.style.format({"Valor Unitario": formatear_moneda_ec, "Valor Total": formatear_moneda_ec}),
            use_container_width=True,
            hide_index=True,
        )

        buffer_excel = io.BytesIO()
        df_items_visible.to_excel(buffer_excel, index=False, engine="openpyxl")
        st.download_button(
            "📊 Descargar Tabla de Ítems en Excel",
            data=buffer_excel.getvalue(),
            file_name="Anexo1_items.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="anexo1_descargar_excel",
        )

    elif tab_activa == NOMBRES_TABS_ANEXO1[2]:
        df_items = _recalcular_items_anexo1(st.session_state.anexo1_items_df)
        cantidad_items = len(df_items)
        specs = st.session_state.anexo1_specs
        tipos_por_fila = df_items["Tipo"].fillna("Bien").tolist() if cantidad_items else []

        while len(specs) < cantidad_items:
            specs.append(_specs_vacias_anexo1(tipos_por_fila[len(specs)]))
        del specs[cantidad_items:]
        for indice, tipo_fila in enumerate(tipos_por_fila):
            # si el usuario cambio el Tipo de ESE item en la pestaña
            # anterior, la spec ya cargada tiene la forma equivocada y
            # hay que reiniciarla (no se puede mezclar, ej., parametros
            # de Bien con campos de Servicio).
            es_spec_de_servicio = "procedimiento" in specs[indice]
            if es_spec_de_servicio != (tipo_fila == "Servicio"):
                specs[indice] = _specs_vacias_anexo1(tipo_fila)

        if cantidad_items == 0:
            st.info(
                'Agrega ítems en la pestaña "2. Ítems y Valores" para poder '
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
                            key=f"anexo1_specs_material_{indice}",
                        )
                        spec["subtitulo_specs"] = st.text_input(
                            'Subtítulo (equivalente a "Modelo de Ejemplo", se resalta en verde)',
                            value=spec.get("subtitulo_specs", "MODELO DE EJEMPLO"),
                            key=f"anexo1_specs_subtitulo_{indice}",
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
                                key=f"anexo1_specs_param_nombre_{indice}_{param_id}",
                                label_visibility=etiquetas,
                            )
                            parametro["valor"] = col_valor.text_input(
                                "Valor",
                                value=parametro.get("valor", ""),
                                key=f"anexo1_specs_param_valor_{indice}_{param_id}",
                                label_visibility=etiquetas,
                            )
                            if col_quitar.button(
                                "🗑️", key=f"anexo1_specs_param_quitar_{indice}_{param_id}"
                            ):
                                parametros.pop(indice_param)
                                st.rerun()
                        if st.button("➕ Añadir parámetro", key=f"anexo1_specs_agregar_param_{indice}"):
                            st.session_state.anexo1_siguiente_param_id += 1
                            parametros.append(
                                {
                                    "id": st.session_state.anexo1_siguiente_param_id,
                                    "nombre": "",
                                    "valor": "",
                                }
                            )
                            st.rerun()
                    else:
                        spec["procedimiento"] = st.text_area(
                            "Procedimiento (Desmontaje/Montaje)",
                            value=spec.get("procedimiento", ""),
                            key=f"anexo1_specs_procedimiento_{indice}",
                        )
                        spec["herramientas_equipo"] = st.text_area(
                            "Herramientas/Equipo",
                            value=spec.get("herramientas_equipo", ""),
                            key=f"anexo1_specs_herramientas_{indice}",
                        )
                        spec["normas_aplicables"] = st.text_area(
                            "Normas aplicables",
                            value=spec.get("normas_aplicables", ""),
                            key=f"anexo1_specs_normas_{indice}",
                        )
                        spec["medicion"] = st.text_area(
                            "Medición",
                            value=spec.get("medicion", ""),
                            key=f"anexo1_specs_medicion_{indice}",
                        )
                        spec["forma_pago"] = st.text_area(
                            "Forma de Pago",
                            value=spec.get("forma_pago", ""),
                            key=f"anexo1_specs_forma_pago_{indice}",
                        )
                        spec["obligaciones"] = st.text_area(
                            "Obligaciones",
                            value=spec.get("obligaciones", ""),
                            key=f"anexo1_specs_obligaciones_{indice}",
                        )

    elif tab_activa == NOMBRES_TABS_ANEXO1[3]:
        with st.expander("Presupuesto y Alcance", expanded=True):
            st.number_input(
                "Presupuesto Referencial (USD)",
                min_value=0.0,
                format="%.2f",
                value=None,
                key="anexo1_presupuesto",
                help="Se muestra en el documento con formato ecuatoriano, ej. $ 9.106.285,46.",
            )
            st.markdown("**Requerimientos Adicionales Obligatorios**")
            st.session_state.anexo1_cpc_df = st.data_editor(
                st.session_state.anexo1_cpc_df,
                num_rows="dynamic",
                use_container_width=True,
                key="anexo1_cpc_editor",
            )
            st.text_input(
                "Código CPC (detallar el código y la descripción del de mayor peso económico)",
                key="anexo1_codigo_cpc_mayor_peso",
            )
            st.text_area("Alcance", key="anexo1_alcance")
            st.text_input("Plazo de Ejecución: parcial y/o total (en días)", key="anexo1_plazo")
            st.markdown("**Personal Técnico/Equipo de Trabajo/Recursos según corresponda**")
            st.text_area("1.- Personal Técnico Principal", key="anexo1_personal_tecnico_principal")
            st.text_area(
                "2.- Personal Técnico Auxiliar o Secundario", key="anexo1_personal_tecnico_auxiliar"
            )
            st.text_area("3.- Equipo de Trabajo", key="anexo1_equipo_trabajo")
            st.text_area("4.- Recursos", key="anexo1_recursos")
            st.text_area("Forma y condiciones de pago", key="anexo1_forma_pago")
            st.text_input("Lugar y dirección de entrega/ejecución", key="anexo1_lugar")

        with st.expander("Obligaciones y Garantías"):
            st.text_area("Obligaciones de la Entidad Contratante", key="anexo1_obligaciones_entidad")
            st.text_area("Obligaciones de la Contratista", key="anexo1_obligaciones_contratista")
            st.text_area(
                "Garantías técnicas, en el caso de que aplique", key="anexo1_garantias_tecnicas"
            )
            st.number_input(
                "Monto USD de la Garantía de Responsabilidad Civil (mínimo USD 3.000)",
                min_value=3000.0,
                format="%.2f",
                value=None,
                key="anexo1_monto_garantia_rc",
            )
            st.number_input(
                "Vigencia de la oferta (días)", min_value=0, step=1, value=90, key="anexo1_vigencia_oferta"
            )
            st.text_input("Tipo de adjudicación", key="anexo1_tipo_adjudicacion")
            st.caption(
                "El documento incluye, con el texto fijo del modelo institucional: Multas (1 por "
                "1000), Garantía de Fiel Cumplimiento y Garantía de Buen Uso de Anticipo, y "
                "Reajuste de Precios."
            )

        with st.expander("Administrador y Contactos"):
            st.markdown("**Administrador del Contrato**")
            col1, col2, col3 = st.columns(3)
            col1.text_input("Nombre del Administrador", key="anexo1_admin_nombre")
            col2.text_input("Cargo del Administrador", key="anexo1_admin_cargo")
            col3.text_input("Cédula del Administrador", key="anexo1_admin_cedula")
            st.caption(
                f"El documento incluye, a continuación, la lista fija de "
                f"{len(TEXTO_ATRIBUCIONES_ADMINISTRADOR)} atribuciones numeradas del Administrador del "
                f"Contrato, más {len(TEXTO_ADMINISTRADOR_OBLIGACIONES_ADICIONALES)} obligaciones "
                f"adicionales en viñetas y el párrafo de cierre sobre cambio de administrador."
            )

            st.markdown("**Técnico que no interviene en la contratación**")
            col4, col5, col6 = st.columns(3)
            col4.text_input("Nombre del Técnico", key="anexo1_tecnico_nombre")
            col5.text_input("Cargo del Técnico", key="anexo1_tecnico_cargo")
            col6.text_input("Correo del Técnico", key="anexo1_tecnico_correo")

            st.markdown("**Contacto**")
            col7, col8 = st.columns(2)
            col7.text_input("Dirección de contacto", key="anexo1_direccion_contacto")
            col8.text_input("Teléfono de contacto", key="anexo1_telefono_contacto")

            st.text_input("Proceso de contratación a aplicar", key="anexo1_proceso_aplicar")
            st.text_area(
                "Análisis para definir la estrategia de adquisición", key="anexo1_analisis_estrategia"
            )

        with st.expander("Evaluación y Calificación"):
            col1, col2 = st.columns(2)
            col1.number_input(
                "% mínimo de experiencia general requerido",
                min_value=0.0,
                max_value=100.0,
                value=None,
                key="anexo1_pct_general",
            )
            col2.number_input(
                "% mínimo de experiencia específica requerido",
                min_value=0.0,
                max_value=100.0,
                value=None,
                key="anexo1_pct_especifica",
            )
            st.text_input(
                "Título profesional requerido para el personal técnico",
                key="anexo1_titulo_profesional",
            )
            st.text_area("Equipo de trabajo/recursos a evaluar", key="anexo1_equipo_evaluar")
            st.selectbox(
                "Certificado de proveedor exclusivo o autorizado",
                ["No", "Sí"],
                key="anexo1_certificado_proveedor",
            )
            st.selectbox("¿Aplica Patrimonio?", ["No", "Sí"], key="anexo1_patrimonio_aplica")
            if st.session_state.get("anexo1_patrimonio_aplica") == "Sí":
                st.caption(
                    "Se incluirán en el documento las 2 tablas fijas de rangos de Patrimonio "
                    "(Bienes y/o Servicios, y Obras)."
                )
            st.text_area(
                "Evaluación del análisis de estrategia de adquisición",
                key="anexo1_evaluacion_estrategia",
            )
            st.text_area(
                "Otros parámetros de evaluación y calificación", key="anexo1_otros_parametros"
            )
            st.caption(
                "El documento incluye, con texto y puntajes fijos del modelo institucional: la "
                "tabla de checklist Cumple/No Cumple, y la metodología de evaluación por puntaje "
                "(Experiencia General 10, Experiencia Específica 20, Experiencia del Personal "
                "Técnico 10, Oferta Económica 50, Valor Agregado Ecuatoriano 10, Total 100)."
            )

        with st.expander("Fecha y Firmas"):
            st.text_input("Fecha del documento", key="anexo1_fecha")
            st.markdown("**Firmas de responsabilidad**")
            col_e1, col_e2, col_e3 = st.columns(3)
            col_e1.text_input("Elaborado por — Nombre", key="anexo1_firma_elaborado_nombre")
            col_e2.text_input("Elaborado por — Cargo", key="anexo1_firma_elaborado_cargo")
            col_e3.text_input("Elaborado por — Firmado por", key="anexo1_firma_elaborado_firmado")

            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.text_input("Revisado por — Nombre", key="anexo1_firma_revisado_nombre")
            col_r2.text_input("Revisado por — Cargo", key="anexo1_firma_revisado_cargo")
            col_r3.text_input("Revisado por — Firmado por", key="anexo1_firma_revisado_firmado")

            col_a1, col_a2, col_a3 = st.columns(3)
            col_a1.text_input(
                "Aprobado por — Nombre",
                value=FIRMA_APROBADO_POR_DEFECTO_NOMBRE,
                key="anexo1_firma_aprobado_nombre",
            )
            col_a2.text_input(
                "Aprobado por — Cargo",
                value=FIRMA_APROBADO_POR_DEFECTO_CARGO,
                key="anexo1_firma_aprobado_cargo",
            )
            col_a3.text_input("Aprobado por — Firmado por", key="anexo1_firma_aprobado_firmado")

        st.divider()
        if st.button("📄 Descargar Anexo 1 en Word", key="anexo1_generar", type="primary"):
            if st.session_state.anexo1_items_df.empty:
                st.warning(
                    'Agrega al menos un ítem en la pestaña "2. Ítems y Valores" '
                    "antes de generar el documento."
                )
            else:
                datos = _recolectar_datos_anexo1()
                nombre_archivo = f"Anexo1_{_slug_nombre_archivo(datos['objeto_contratacion'] or 'documento')}.docx"
                ruta_temporal = Path(tempfile.gettempdir()) / nombre_archivo
                generar_anexo1(datos, ruta_temporal)
                st.session_state.anexo1_docx_bytes = ruta_temporal.read_bytes()
                st.session_state.anexo1_docx_nombre = nombre_archivo
                ruta_temporal.unlink(missing_ok=True)
                st.success("Documento generado correctamente.")

        if st.session_state.get("anexo1_docx_bytes"):
            st.download_button(
                "⬇ Descargar " + st.session_state.anexo1_docx_nombre,
                data=st.session_state.anexo1_docx_bytes,
                file_name=st.session_state.anexo1_docx_nombre,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="anexo1_descargar_docx",
            )

    elif tab_activa == NOMBRES_TABS_ANEXO1[4]:
        st.caption(
            "Se actualiza automáticamente a medida que completas los datos en las otras "
            'pestañas. Los campos vacíos se muestran como "LLENAR".'
        )
        _render_vista_previa_anexo1(_recolectar_datos_anexo1())


def render_pagina_municipalidad_guayaquil(registros_totales: list[dict]) -> None:
    st.header("🏙️ Municipalidad de Guayaquil")
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
    st.header("⚙️ Configuración")
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
