"""Generador de "Especificaciones Técnicas" (ET, antes "Anexo 1"): formulario
de Streamlit, vista previa HTML, exportacion a .docx y persistencia de
borradores. Separado de app_ui.py (P0-1 del plan de mejoras) porque es
~la mitad del archivo original y un dominio propio -- app_ui.py solo
importa `render_formularios_y_registro` (el punto de entrada de la
seccion "Formularios y Registro" de Municipalidad de Guayaquil),
`render_treemap_items_especificaciones_tecnicas` y
`_dataframe_items_especificaciones_tecnicas_vacio` (estas dos ultimas las
usa `_render_detalles_dashboard` para la pestaña "Presupuesto por Ítem"
del Dashboard).

Es un MOVE, no una reescritura: el patron diccionario-sombra de estado
(`_restaurar_campos_simples_*` / `_estado_pendiente_restaurar` / bump de
`editor_version`) es fragil pero esta battle-tested -- se mudo intacto,
sin simplificar."""
import base64
import html
import io
import json
import re
import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from scripts.dashboard_analitico import construir_datos_treemap_items
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
    TEXTO_ADMINISTRADOR_INTRO_PLANTILLA,
    TEXTO_ADMINISTRADOR_OBLIGACIONES_ADICIONALES,
    TEXTO_ADMINISTRADOR_OBLIGACIONES_INTRO,
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
from scripts.formato_ec import formatear_moneda_ec, formatear_numero_ec
from scripts.importador_items import (
    ErrorImportacionItems,
    ErrorLLMImportacionItems,
    importar_items,
)
from scripts.importador_parametros import (
    ErrorImportacionParametros,
    ErrorLLMImportacionParametros,
    importar_parametros,
)
from scripts.tinymce_editor import tinymce_editor
from services.sercop import (
    eliminar_borrador_especificaciones_tecnicas,
    guardar_borrador_especificaciones_tecnicas,
    listar_borradores_especificaciones_tecnicas,
    obtener_borrador_especificaciones_tecnicas,
)
from src.logging_config import obtener_logger
from ui.tema import COLOR_LIENZO, COLOR_SIDEBAR_ACENTO, COLOR_TEXTO_EJE, PALETA_DATOS

logger = obtener_logger(__name__)


def _construir_datos_treemap_items_cacheado(df_items: pd.DataFrame) -> pd.DataFrame:
    """Wrapper cacheado (@st.cache_data) sobre `construir_datos_treemap_items`
    (scripts/dashboard_analitico.py, sin Streamlit -- mismo motivo que
    _recalcular_items_especificaciones_tecnicas): el treemap se vuelve a dibujar en cada
    rerun del Dashboard Analítico sobre el mismo
    st.session_state.especificaciones_tecnicas_items_df, asi que sin cache se reagruparia
    identico varias veces por script run."""
    return construir_datos_treemap_items(df_items)


def render_treemap_items_especificaciones_tecnicas(df_items: pd.DataFrame) -> None:
    """Treemap de la distribucion del presupuesto DENTRO del documento de
    Especificaciones Técnicas actualmente cargado en el formulario (columna "Descripción"
    para las cajas, "Valor Total" como area/tamaño de cada una -- el color
    se asigna por Descripción, no por escala continua de Valor Total: ver
    el comentario junto a root_color en el cuerpo de la funcion) -- a
    diferencia de `render_treemap_presupuesto_tipo`, que agrega presupuesto
    entre procesos ya guardados, este lee directo de
    st.session_state.especificaciones_tecnicas_items_df (el mismo dataframe editable en
    la seccion "Ítems y Presupuesto"), asi que refleja los items que se
    esten cargando en ese momento, incluso antes de guardar el borrador.

    Fondo transparente (paper_bgcolor/plot_bgcolor="rgba(0,0,0,0)") en vez
    del lienzo blanco solido de `_aplicar_estilo_base`: la app fuerza tema
    claro con fondo blanco (.streamlit/config.toml), asi que el resultado
    visual es identico a un lienzo blanco, pero deja que el rectangulo se
    integre con el fondo real del contenedor (tarjeta neumorfista) en vez
    de dibujar un bloque blanco propio encima."""
    st.markdown("**Presupuesto por Ítem del documento actual de Especificaciones Técnicas (treemap)**")
    st.caption(
        "Se arma en vivo con los ítems cargados ahora mismo en la sección "
        "'Ítems y Presupuesto' de Especificaciones Técnicas (Municipalidad de Guayaquil) -- "
        "no depende de haber guardado el borrador."
    )
    resumen = _construir_datos_treemap_items_cacheado(df_items)
    if resumen.empty:
        st.info(
            "No hay ítems con Descripción y Valor Total cargados todavía en "
            "Especificaciones Técnicas para graficar."
        )
        return

    fig = px.treemap(
        resumen,
        path=["descripcion"],
        values="valor_total",
        color="descripcion",
        color_discrete_sequence=PALETA_DATOS,
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>$ %{value:,.2f}",
        textfont=dict(size=13, color="#FFFFFF"),
        marker=dict(line=dict(width=0)),  # sin bordes duros entre cajas
        hovertemplate="<b>%{label}</b><br>Valor Total: $ %{value:,.2f}<extra></extra>",
        # root_color es un no-op con color_continuous_scale (el tile raiz
        # queda en el gris rgb(68,68,68) por defecto de Plotly pase lo que
        # pase -- comportamiento documentado, no un bug de esta app), asi
        # que el color se asigna por categoria (color_discrete_sequence,
        # mismo patron que render_treemap_provincia_estado/
        # render_treemap_presupuesto_tipo) en vez de por escala continua de
        # Valor Total; el tamaño de cada caja SI sigue siendo Valor Total
        # (values="valor_total"). Con color discreto, root_color si aplica.
        root_color=COLOR_LIENZO,
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, 'Segoe UI', sans-serif", color=COLOR_TEXTO_EJE),
        margin=dict(l=10, r=10, t=20, b=10),
        height=480,
        showlegend=False,
        separators=",.",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


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


CATALOGO_CPC_PATH = Path(__file__).resolve().parent.parent / "data" / "cpc_n9.csv"


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
            background-color: #eaf2fb;  /* tinte suave del mismo azul de COLOR_SIDEBAR_ACENTO */
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

                        # Carga masiva: Excel/CSV/TXT con cualquier estructura de
                        # columnas se anexa a `parametros` -- nunca lo reemplaza,
                        # igual que el boton manual de arriba (ver
                        # scripts/importador_parametros.py: camino rapido
                        # determinístico para 2 columnas limpias, con escalada
                        # automática a un normalizador vía IA para archivos con
                        # celdas combinadas de Excel, columnas extra o texto
                        # libre). La clave
                        # `especificaciones_tecnicas_specs_param_archivo_procesado_{indice}` guarda el
                        # file_id del ultimo archivo ya procesado para ESTE item:
                        # sin ese control, como el archivo subido sigue "presente"
                        # en el uploader en cada rerun posterior (Streamlit no lo
                        # limpia solo), sus filas se volverian a anexar una y otra
                        # vez en cualquier rerun futuro (ej. al tipear en otro campo).
                        archivo_subido = col_cargar_archivo.file_uploader(
                            ":material/attach_file: Cargar parámetros desde archivo (Excel/CSV/TXT, cualquier estructura)",
                            type=["xlsx", "csv", "txt"],
                            key=f"especificaciones_tecnicas_specs_param_uploader_{indice}",
                        )
                        clave_procesado = f"especificaciones_tecnicas_specs_param_archivo_procesado_{indice}"
                        # Los errores del camino IA (red/timeout) son transitorios: a
                        # diferencia de un error de archivo (permanente, se marca
                        # `clave_procesado` para no reintentar solo), aquí NO se marca
                        # `clave_procesado` -- pero tampoco se reintenta automáticamente
                        # en cada rerun no relacionado (ej. al tipear en otro campo),
                        # porque eso dispararía llamadas a la API repetidas y silenciosas.
                        # En cambio se guarda el error y se ofrece un botón explícito de
                        # "Reintentar" que dispara un solo intento más.
                        clave_error_llm = f"especificaciones_tecnicas_specs_param_error_llm_{indice}"
                        clave_reintentar = f"especificaciones_tecnicas_specs_param_reintentar_{indice}"
                        if archivo_subido is None:
                            st.session_state[clave_error_llm] = None
                        else:
                            debe_procesar = st.session_state.get(
                                clave_procesado
                            ) != archivo_subido.file_id or st.session_state.get(clave_reintentar, False)
                            if debe_procesar:
                                st.session_state[clave_reintentar] = False
                                try:
                                    with st.spinner("Procesando archivo..."):
                                        resultado = importar_parametros(
                                            archivo_subido.name, archivo_subido.getvalue()
                                        )
                                except ErrorLLMImportacionParametros as exc:
                                    st.session_state[clave_error_llm] = str(exc)
                                except ErrorImportacionParametros as exc:
                                    st.session_state[clave_procesado] = archivo_subido.file_id
                                    st.session_state[clave_error_llm] = None
                                    st.error(f"No se pudo procesar «{archivo_subido.name}»: {exc}")
                                else:
                                    for nuevo in resultado.parametros:
                                        st.session_state.especificaciones_tecnicas_siguiente_param_id += 1
                                        parametros.append(
                                            {
                                                "id": st.session_state.especificaciones_tecnicas_siguiente_param_id,
                                                "nombre": nuevo["nombre"],
                                                "valor": nuevo["valor"],
                                            }
                                        )
                                    st.session_state[clave_procesado] = archivo_subido.file_id
                                    st.session_state[clave_error_llm] = None
                                    camino_legible = "con ayuda de IA" if resultado.camino == "llm" else "directamente"
                                    st.success(
                                        f"Se agregaron {len(resultado.parametros)} parámetro(s) desde "
                                        f"«{archivo_subido.name}» (procesado {camino_legible})."
                                    )
                                    if resultado.advertencia_integridad:
                                        st.warning(resultado.advertencia_integridad)
                                    if resultado.filas_descartadas:
                                        # st.container (no st.expander): esta seccion ya esta
                                        # dentro del expander "Item N" mas arriba, y Streamlit
                                        # no permite anidar expanders (StreamlitAPIException).
                                        with st.container(border=True):
                                            st.caption(
                                                f"{len(resultado.filas_descartadas)} fila(s) descartada(s) del archivo original:"
                                            )
                                            for descarte in resultado.filas_descartadas:
                                                st.caption(f"«{descarte['fila']}» — {descarte['motivo']}")
                                    st.rerun()

                        if archivo_subido is not None and st.session_state.get(clave_error_llm):
                            st.error(
                                f"No se pudo procesar «{archivo_subido.name}» con ayuda de IA: "
                                f"{st.session_state[clave_error_llm]}"
                            )
                            if col_cargar_archivo.button(
                                ":material/refresh: Reintentar",
                                key=f"especificaciones_tecnicas_specs_param_reintentar_btn_{indice}",
                            ):
                                st.session_state[clave_reintentar] = True
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

            # Importar items desde archivo: fuera del st.form a proposito --
            # un file_uploader dentro de un form no se procesa hasta el
            # submit, y aca se necesita feedback inmediato (resumen,
            # advertencias, boton de reintento) apenas se sube. Ver
            # scripts/importador_items.py: camino rapido deterministico
            # (deteccion de encabezado + fuzzy matching de columnas) con
            # respaldo via IA para archivos sin estructura de columnas clara.
            archivo_items_subido = st.file_uploader(
                ":material/upload_file: Cargar ítems desde archivo (Excel/CSV/TXT) -- columnas "
                "ÍTEM, DESCRIPCIÓN, UNIDAD, CANTIDAD, PRECIO UNITARIO y CPC (en cualquier orden, "
                "con encabezados alterados, o sin estructura de columnas clara)",
                type=["xlsx", "csv", "txt"],
                key="especificaciones_tecnicas_items_uploader",
            )
            clave_procesado_items = "especificaciones_tecnicas_items_archivo_procesado"
            # Mismo patron de dos niveles de error que el uploader de
            # Parametros: un error permanente (archivo vacio/corrupto) marca
            # el archivo como procesado y no reintenta solo; un error
            # transitorio del camino IA (red/timeout) NO lo marca, pero
            # tampoco reintenta automaticamente en cada rerun no relacionado
            # -- se guarda el mensaje y se ofrece un boton explicito de
            # "Reintentar" que dispara un solo intento mas.
            clave_error_llm_items = "especificaciones_tecnicas_items_error_llm"
            clave_reintentar_items = "especificaciones_tecnicas_items_reintentar"
            if archivo_items_subido is None:
                st.session_state[clave_error_llm_items] = None
            else:
                debe_procesar_items = st.session_state.get(
                    clave_procesado_items
                ) != archivo_items_subido.file_id or st.session_state.get(clave_reintentar_items, False)
                if debe_procesar_items:
                    st.session_state[clave_reintentar_items] = False
                    try:
                        with st.spinner("Procesando archivo de ítems..."):
                            resultado_items = importar_items(
                                archivo_items_subido.name,
                                archivo_items_subido.getvalue(),
                                catalogo_cpc=_cargar_catalogo_cpc(),
                            )
                    except ErrorLLMImportacionItems as exc:
                        st.session_state[clave_error_llm_items] = str(exc)
                    except ErrorImportacionItems as exc:
                        st.session_state[clave_procesado_items] = archivo_items_subido.file_id
                        st.session_state[clave_error_llm_items] = None
                        st.error(f"No se pudo procesar «{archivo_items_subido.name}»: {exc}")
                    else:
                        # Mismos dtypes que _dataframe_items_especificaciones_tecnicas_vacio():
                        # "Ítem" y "_fila_id" quedan en pd.NA (Int64), igual que una fila
                        # agregada a mano con el boton "+" del editor -- la logica ya
                        # existente (_asignar_fila_ids_especificaciones_tecnicas /
                        # _recalcular_items_especificaciones_tecnicas) los completa en el
                        # proximo "Guardar Ítems", sin que este importador toque esa parte.
                        cantidad_filas_nuevas = len(resultado_items.filas)
                        filas_nuevas = pd.DataFrame(
                            {
                                "Ítem": pd.array([pd.NA] * cantidad_filas_nuevas, dtype="Int64"),
                                "Tipo": [f["tipo"] for f in resultado_items.filas],
                                "Descripción": [f["descripcion"] for f in resultado_items.filas],
                                "Unidad de Medida": [f["unidad_medida"] for f in resultado_items.filas],
                                "Cantidad Solicitada": [f["cantidad_solicitada"] for f in resultado_items.filas],
                                "Valor Unitario": [f["valor_unitario"] for f in resultado_items.filas],
                                "Valor Total": [0.0] * cantidad_filas_nuevas,
                                "Descripción CPC": [f["descripcion_cpc"] for f in resultado_items.filas],
                                "Número CPC": [f["numero_cpc"] for f in resultado_items.filas],
                                "_fila_id": pd.array([pd.NA] * cantidad_filas_nuevas, dtype="Int64"),
                            }
                        )
                        st.session_state.especificaciones_tecnicas_items_df = pd.concat(
                            [st.session_state.especificaciones_tecnicas_items_df, filas_nuevas], ignore_index=True
                        )
                        st.session_state.especificaciones_tecnicas_items_editor_version += 1
                        st.session_state[clave_procesado_items] = archivo_items_subido.file_id
                        st.session_state[clave_error_llm_items] = None
                        camino_legible = "con ayuda de IA" if resultado_items.camino == "llm" else "directamente"
                        st.success(
                            f"Se agregaron {cantidad_filas_nuevas} ítem(s) desde "
                            f"«{archivo_items_subido.name}» (procesado {camino_legible})."
                        )
                        if resultado_items.cpc_no_encontrados:
                            codigos_unicos = ", ".join(sorted(set(resultado_items.cpc_no_encontrados)))
                            st.warning(f"Código(s) CPC no encontrado(s) en el catálogo: {codigos_unicos}")
                        if resultado_items.filas_con_error:
                            # st.container (no st.expander): aunque esta seccion no esta
                            # anidada en otro expander hoy, se usa el mismo patron ya
                            # corregido en el importador de Parametros para no reintroducir
                            # el StreamlitAPIException de expanders anidados si la UI se
                            # reestructura mas adelante.
                            with st.container(border=True):
                                st.caption(f"{len(resultado_items.filas_con_error)} fila(s) con advertencias:")
                                for error in resultado_items.filas_con_error:
                                    st.caption(f"«{error['fila']}» — {error['motivo']}")
                        st.rerun()

            if archivo_items_subido is not None and st.session_state.get(clave_error_llm_items):
                st.error(
                    f"No se pudo procesar «{archivo_items_subido.name}» con ayuda de IA: "
                    f"{st.session_state[clave_error_llm_items]}"
                )
                if st.button(":material/refresh: Reintentar", key="especificaciones_tecnicas_items_reintentar_btn"):
                    st.session_state[clave_reintentar_items] = True
                    st.rerun()

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
                # Import diferido (no al tope del modulo): _slug_nombre_archivo
                # vive en app_ui.py, que a su vez importa este modulo -- una
                # importacion al tope aca crearia un ciclo. Para cuando esta
                # linea corre (un clic del usuario), app_ui.py ya termino de
                # cargar, asi que el import diferido es seguro.
                from app_ui import _slug_nombre_archivo

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


