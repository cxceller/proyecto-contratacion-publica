"""Preparacion de datos para el "Dashboard Analitico" (Treemap de
presupuesto por tipo de compra y Gantt de procesos de contratacion).

Modulo puro (solo pandas, sin Streamlit ni llamadas a la API) para poder
testearlo de forma aislada -- mismo patron de separacion que
`scripts/especificaciones_tecnicas_generator.py` respecto de `app_ui.py`. Ambas funciones
reciben el DataFrame que ya produce `preparar_dataframe()` en app_ui.py
(el mismo que alimenta los KPIs y las tablas resumen del dashboard) y
SIEMPRE devuelven un DataFrame con las columnas esperadas -- vacio si no
hay datos suficientes, nunca None -- para que la vista pueda decidir con
un simple `.empty` sin arriesgar un AttributeError.
"""
from __future__ import annotations

import pandas as pd

COLUMNAS_TREEMAP_PRESUPUESTO = ["tipo_compra", "estado", "presupuesto_referencial", "procesos"]
COLUMNAS_GANTT_PROCESOS = [
    "codigo", "entidad_contratante", "objeto_proceso", "estado", "etiqueta", "inicio", "fin", "dias_transcurridos",
]


def construir_datos_treemap_presupuesto(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa el Presupuesto Referencial por Tipo de Compra -> Estado del
    Proceso, para el treemap jerarquico de distribucion del presupuesto
    (a diferencia del treemap Provincia -> Estado ya existente en
    app_ui.py, que pondera por conteo de procesos, este pondera por
    dinero). Requiere las columnas `tipo_compra`, `estado` y
    `presupuesto_referencial` (las mismas que ya produce
    `preparar_dataframe()`); si faltan o el DataFrame esta vacio, devuelve
    un DataFrame vacio con las columnas esperadas."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_TREEMAP_PRESUPUESTO)
    if not {"tipo_compra", "estado", "presupuesto_referencial"}.issubset(df.columns):
        return pd.DataFrame(columns=COLUMNAS_TREEMAP_PRESUPUESTO)

    datos = df.copy()
    datos["presupuesto_referencial"] = pd.to_numeric(datos["presupuesto_referencial"], errors="coerce").fillna(0)

    resumen = (
        datos.groupby(["tipo_compra", "estado"], as_index=False)
        .agg(presupuesto_referencial=("presupuesto_referencial", "sum"), procesos=("presupuesto_referencial", "size"))
    )
    # Un rectangulo con valor 0 (o negativo) no es representable en un
    # treemap -- Plotly lo descarta con un warning en consola.
    resumen = resumen[resumen["presupuesto_referencial"] > 0].reset_index(drop=True)
    return resumen


def _etiqueta_gantt(codigo: str, objeto_proceso: str, longitud: int = 40) -> str:
    """'CODIGO -- primeras N letras del objeto del proceso...' para el eje Y
    del Gantt: el codigo solo no es legible y el objeto completo desborda."""
    codigo = str(codigo or "").strip() or "(Sin código)"
    objeto = str(objeto_proceso or "").strip()
    if len(objeto) > longitud:
        objeto = objeto[:longitud].rstrip() + "…"
    return f"{codigo} — {objeto}" if objeto else codigo


def construir_datos_gantt_procesos(
    df: pd.DataFrame, hoy: pd.Timestamp | None = None, limite: int = 25,
) -> pd.DataFrame:
    """Arma las barras del Gantt de procesos: cada proceso va de su
    `fecha_publicacion` (la unica fecha real que expone el portal de
    Compras Publicas para el proceso) hasta `hoy` -- una linea de tiempo de
    "dias transcurridos desde la publicacion", coloreada por estado. No es
    un cronograma con fecha de cierre real de ejecucion (el portal no
    expone eso; el campo mas cercano, "Plazo de Ejecución", es un texto
    libre en dias que se captura por documento en Especificaciones Técnicas, no por
    proceso historico), asi que se documenta como tal en la UI.

    Devuelve como maximo `limite` filas (las de publicacion mas reciente),
    para que el grafico siga siendo legible. Si no hay ninguna fecha de
    publicacion valida, devuelve un DataFrame vacio con las columnas
    esperadas -- nunca None."""
    if df is None or df.empty or "fecha_publicacion" not in df.columns:
        return pd.DataFrame(columns=COLUMNAS_GANTT_PROCESOS)

    hoy = hoy or pd.Timestamp.now().normalize()
    datos = df.copy()
    datos["fecha_publicacion"] = pd.to_datetime(datos["fecha_publicacion"], errors="coerce")
    datos = datos.dropna(subset=["fecha_publicacion"])
    if datos.empty:
        return pd.DataFrame(columns=COLUMNAS_GANTT_PROCESOS)

    for columna in ("codigo", "entidad_contratante", "objeto_proceso", "estado"):
        if columna not in datos.columns:
            datos[columna] = ""

    datos = datos.sort_values("fecha_publicacion", ascending=False).head(limite).copy()
    datos["inicio"] = datos["fecha_publicacion"]
    datos["fin"] = hoy
    datos["dias_transcurridos"] = (datos["fin"] - datos["inicio"]).dt.days
    datos["etiqueta"] = datos.apply(lambda fila: _etiqueta_gantt(fila["codigo"], fila["objeto_proceso"]), axis=1)

    return datos[COLUMNAS_GANTT_PROCESOS].reset_index(drop=True)
