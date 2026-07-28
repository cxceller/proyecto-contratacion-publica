"""Interfaz Streamlit para visualizar procesos de contratacion publica.

Consume la API FastAPI (src/main.py) via requests. Arranque:

    uvicorn src.main:app --port 8000
    streamlit run app_ui.py --server.port 8501
"""
import os
import re
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

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


def api_request(method: str, path: str, **kwargs):
    try:
        response = requests.request(method, f"{API_URL}{path}", timeout=10, **kwargs)
    except requests.exceptions.ConnectionError:
        st.error(
            f"No se pudo conectar a la API en {API_URL}. "
            "¿Está corriendo `uvicorn src.main:app --port 8000`?"
        )
        return None
    return response


def obtener_contrataciones(status=None, fecha_inicio=None, fecha_fin=None, palabra_clave=None):
    params = {}
    if status:
        params["status"] = status
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
    return primera_palabra.capitalize() if primera_palabra else "Otros"


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
    return df


def render_filtros_dashboard(df: pd.DataFrame) -> pd.DataFrame:
    """Fila de filtros superiores (Año, Mes, Provincia/Cantón) que acota
    todo lo que se muestra debajo: graficos, tablas y KPIs comparten el
    mismo dataframe filtrado, para que las cifras siempre coincidan."""
    col1, col2, col3 = st.columns(3)

    if df.empty:
        col1.selectbox("Año", ["(Todos)"], disabled=True)
        col2.selectbox("Mes", ["(Todos)"], disabled=True)
        col3.multiselect("Provincia/Cantón", [], disabled=True)
        return df

    anios_disponibles = sorted(df["anio"].dropna().unique().astype(int), reverse=True)
    anio_sel = col1.selectbox("Año", ["(Todos)"] + [str(a) for a in anios_disponibles])

    meses_disponibles = sorted(df["mes_num"].dropna().unique().astype(int))
    opciones_mes = ["(Todos)"] + [MESES_ES[m] for m in meses_disponibles]
    mes_sel = col2.selectbox("Mes", opciones_mes)

    provincias_disponibles = sorted(df["provincia_canton"].dropna().unique())
    provincias_sel = col3.multiselect("Provincia/Cantón", provincias_disponibles)

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
    )


def _tarjeta_kpi_html(etiqueta: str, valor: str) -> str:
    """Tarjeta KPI en HTML puro (no st.metric): el fondo se fuerza por
    inline-style con COLOR_LIENZO, igual que plot_bgcolor/paper_bgcolor de
    los graficos, para que ambos recuadros hagan juego sin depender del
    tema claro/oscuro de Streamlit."""
    return f"""
    <div style="background-color:{COLOR_LIENZO}; border-radius:0;
                border:none; box-shadow:none; padding:1.25rem 1.5rem;
                margin-bottom:0.5rem;">
        <div style="font-size:0.875rem; color:{COLOR_TEXTO_EJE}; opacity:0.7;">
            {etiqueta}
        </div>
        <div style="font-size:2rem; font-weight:600; color:{COLOR_TEXTO_EJE}; line-height:1.3;">
            {valor}
        </div>
    </div>
    """


def render_kpis_dashboard(df: pd.DataFrame):
    col1, col2 = st.columns(2)
    presupuesto_total = df["presupuesto_referencial"].fillna(0).sum() if not df.empty else 0
    col1.markdown(_tarjeta_kpi_html("Procesos (filtro actual)", str(len(df))), unsafe_allow_html=True)
    col2.markdown(
        _tarjeta_kpi_html("Presupuesto Total (filtro actual)", f"$ {presupuesto_total:,.2f}"),
        unsafe_allow_html=True,
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
    col1.caption("Por Estado del Proceso")
    col1.dataframe(
        resumen_estado,
        column_config={"Presupuesto Total": st.column_config.NumberColumn(format="$ %.2f")},
        hide_index=True,
        use_container_width=True,
    )

    resumen_tipo = (
        df.groupby("tipo_compra", as_index=False)
        .agg(Procesos=("id", "count"), Presupuesto_Total=("presupuesto_referencial", "sum"))
        .rename(columns={"tipo_compra": "Tipo de Compra", "Presupuesto_Total": "Presupuesto Total"})
        .sort_values("Presupuesto Total", ascending=False)
    )
    col2.caption("Por Tipo de Compra (inferido del Objeto del Proceso)")
    col2.dataframe(
        resumen_tipo,
        column_config={"Presupuesto Total": st.column_config.NumberColumn(format="$ %.2f")},
        hide_index=True,
        use_container_width=True,
    )


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
    col1.metric("Número de Procesos", len(registros))
    col2.metric("Presupuesto Total", f"$ {presupuesto_total:,.2f}")
    col3.metric(
        "Valor Adjudicado Total",
        f"$ {valor_adjudicado_total:,.2f}",
        help=(
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

    column_config = {
        "Código": st.column_config.LinkColumn(
            "Código", pinned=True, display_text=r"#(.*)$", width="medium"
        ),
        "Objeto del Proceso": st.column_config.TextColumn(
            "Objeto del Proceso", width="large"
        ),
        "Presupuesto Referencial (sin IVA)": st.column_config.NumberColumn(
            "Presupuesto Referencial (sin IVA)", format="$ %.2f", width="medium"
        ),
        "Fecha de Publicación": st.column_config.DateColumn(
            "Fecha de Publicación", format="YYYY-MM-DD"
        ),
    }

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
    cols[0].metric("Total", total)
    for i, estado_categoria in enumerate(etiquetas, start=1):
        cols[i % 4].metric(estado_categoria, conteos[estado_categoria])


def render_vaciar_base_datos():
    st.divider()
    st.subheader("⚠️ Zona de peligro")

    if "confirmar_vaciado" not in st.session_state:
        st.session_state.confirmar_vaciado = False

    if not st.session_state.confirmar_vaciado:
        if st.button("⚠️ Vaciar Base de Datos", use_container_width=True):
            st.session_state.confirmar_vaciado = True
            st.rerun()
        return

    st.warning(
        "Esto eliminará **todos** los procesos de contratación de la base "
        "de datos de forma permanente. Esta acción no se puede deshacer."
    )
    confirmado = st.checkbox("Sí, entiendo y quiero vaciar la base de datos por completo")

    col_confirmar, col_cancelar = st.columns(2)
    if col_confirmar.button(
        "Confirmar vaciado",
        type="primary",
        disabled=not confirmado,
        use_container_width=True,
    ):
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


def main():
    st.set_page_config(page_title="Contratación Pública Ecuador", layout="wide")
    st.title("Procesos de Contratación Pública")

    if "resultados" not in st.session_state:
        st.session_state.resultados = None

    if st.session_state.get("mensaje_vaciado"):
        st.success(st.session_state.mensaje_vaciado)
        st.session_state.mensaje_vaciado = None

    with st.sidebar:
        st.header("Búsqueda")
        estado_filtro = st.selectbox("Estado del Proceso", ["(Todos)"] + ESTADOS)
        fecha_inicio = st.date_input("Fecha inicio", value=None)
        fecha_fin = st.date_input("Fecha fin", value=None)
        palabra_clave_filtro = st.text_input("Palabra clave", placeholder="Ej: luminarias")

        col_buscar, col_limpiar = st.columns(2)
        buscar = col_buscar.button("🔍 Buscar", use_container_width=True)
        limpiar = col_limpiar.button("🧹 Limpiar", use_container_width=True)

        if buscar:
            st.session_state.resultados = obtener_contrataciones(
                status=None if estado_filtro == "(Todos)" else estado_filtro,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                palabra_clave=palabra_clave_filtro or None,
            )
        if limpiar:
            st.session_state.resultados = None
            st.rerun()

        render_vaciar_base_datos()

    registros_totales = obtener_contrataciones()
    render_contadores(registros_totales)

    st.divider()
    st.header("📊 Dashboard Analítico")
    df_totales = preparar_dataframe(registros_totales)
    df_filtrado = render_filtros_dashboard(df_totales)
    render_kpis_dashboard(df_filtrado)

    col_mensual, col_provincia = st.columns(2)
    with col_mensual:
        render_grafico_mensual(df_filtrado)
    with col_provincia:
        render_grafico_provincia(df_filtrado)

    render_tablas_resumen(df_filtrado)

    st.divider()
    st.subheader("Resultados")
    registros_mostrar = (
        st.session_state.resultados
        if st.session_state.resultados is not None
        else registros_totales
    )
    render_metricas_resumen(registros_mostrar)
    render_tabla_con_color(registros_mostrar)


if __name__ == "__main__":
    main()
