"""Interfaz Streamlit para visualizar procesos de contratacion publica.

Consume la API FastAPI (src/main.py) via requests. Arranque:

    uvicorn src.main:app --port 8000
    streamlit run app_ui.py --server.port 8501
"""
import os
from datetime import date

import pandas as pd
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


def color_por_estado(estado: str) -> str:
    if not estado:
        return "#616161"
    e = estado.strip().lower()
    if e.startswith("adjudicad"):
        return "#2e7d32"  # verde
    if e.startswith("suspendid"):
        return "#ef6c00"  # naranja
    if e.startswith("desiert"):
        return "#c62828"  # rojo
    if e.startswith("cancelad"):
        return "#b71c1c"  # rojo oscuro
    if e.startswith("terminado"):
        return "#6a1b9a"  # morado (terminacion unilateral)
    if e.startswith("finalizad"):
        return "#1565c0"  # azul
    if e.startswith("ejecuci"):
        return "#f9a825"  # ambar (en curso)
    if e.startswith("en recepci"):
        return "#00838f"  # teal (en curso)
    if e.startswith("por adjudicar"):
        return "#3949ab"  # indigo (pendiente de decision)
    return "#616161"  # gris (desconocido)


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


def render_metricas_resumen(registros: list[dict]):
    """Tarjetas de resumen sobre los resultados actualmente filtrados. No
    existe en el esquema un campo separado de "valor final adjudicado"
    (solo `presupuesto_referencial`), asi que ese total se calcula como la
    suma del presupuesto referencial de los procesos cuyo estado empieza
    por "Adjudicad..." (ver `color_por_estado`/`ESTADOS`)."""
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
    df_visible = df_mostrar[columnas_visibles]

    estilo = df_visible.style.map(
        lambda estado: (
            f"background-color: {color_por_estado(estado)}; color: white; "
            "border-radius: 999px; padding: 2px 10px; font-weight: 600; "
            "text-align: center;"
        ),
        subset=["Estado del Proceso"],
    )

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
        estilo,
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


def render_formulario_creacion():
    st.subheader("Nuevo proceso de contratación")
    with st.form("form_nueva_contratacion", clear_on_submit=True):
        col1, col2 = st.columns(2)
        codigo = col1.text_input("Código *")
        entidad_contratante = col2.text_input("Entidad Contratante *")
        objeto_proceso = st.text_area("Objeto del Proceso *")

        col3, col4 = st.columns(2)
        estado = col3.text_input("Estado del Proceso *", placeholder="Ej: Adjudicada")
        provincia_canton = col4.text_input("Provincia/Cantón")

        col5, col6 = st.columns(2)
        presupuesto = col5.number_input(
            "Presupuesto Referencial (sin IVA)", min_value=0.0, step=100.0, format="%.2f"
        )
        fecha_publicacion = col6.date_input("Fecha de Publicación", value=None)

        col7, col8 = st.columns(2)
        palabra_clave = col7.text_input("Palabra Clave", placeholder="Ej: luminarias")
        url = col8.text_input("URL", placeholder="Enlace al detalle en el portal")

        enviado = st.form_submit_button("Crear proceso de contratación")

        if enviado:
            payload = {
                "codigo": codigo,
                "entidad_contratante": entidad_contratante,
                "objeto_proceso": objeto_proceso,
                "estado": estado,
                "provincia_canton": provincia_canton or None,
                "presupuesto_referencial": presupuesto if presupuesto else None,
                "fecha_publicacion": (
                    fecha_publicacion.isoformat() if fecha_publicacion else None
                ),
                "palabra_clave": palabra_clave or None,
                "url": url or None,
            }
            response = api_request("POST", "/api/todos", json=payload)
            if response is None:
                return
            if response.status_code == 201:
                st.success(f"Proceso creado con id {response.json()['id']}")
                st.rerun()
            elif response.status_code == 422:
                errores = response.json().get("detail", [])
                mensaje = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errores
                )
                st.error(f"Datos inválidos: {mensaje}")
            else:
                st.error(f"Error al crear el proceso: {response.status_code}")


def render_gestion_registro():
    with st.expander("Eliminar un proceso de contratación por ID"):
        col1, col2 = st.columns([3, 1])
        contratacion_id = col1.number_input("ID a eliminar", min_value=1, step=1)
        if col2.button("Eliminar", type="secondary"):
            response = api_request("DELETE", f"/api/todos/{int(contratacion_id)}")
            if response is None:
                return
            if response.status_code == 204:
                st.success(f"Proceso {int(contratacion_id)} eliminado.")
                st.rerun()
            elif response.status_code == 404:
                st.warning(f"No existe un proceso con id {int(contratacion_id)}.")
            else:
                st.error(f"Error al eliminar: {response.status_code}")


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
    render_formulario_creacion()
    render_gestion_registro()

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
