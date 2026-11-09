"""Plantilla Plotly comun de la app: UNA sola fuente de verdad para tipografia, paleta, fondo y formato Ecuador.

Se registra con `registrar_plantilla_sercop()` (idempotente) y queda como plantilla por defecto
(`plotly+sercop`): cualquier figura nueva (px o go) la hereda sin repetir estilos. Cada grafico solo pone lo
propio (datos, altura, ejes concretos).

- Fuente IBM Plex Sans (la misma de la UI, vendorizada en static/fonts/), con respaldo del sistema.
- Fondo BLANCO = el de las tarjetas (`--card`), sin el lienzo crema de antes ni transparencia (un fondo
  transparente heredaria el del tema y haria ilegible el texto si cambiara).
- Colores: solo la familia azul de `PALETA_DATOS`; el maximo se resalta con azul fuerte (`COLOR_BARRA_DESTACADA`),
  nunca con naranja.
- Formato Ecuador: `separators=",."` (coma decimal, punto de miles) y meses en espanol via `etiqueta_mes_es`
  (el bundle de Plotly.js de Streamlit no trae el locale "es", por eso los meses se rotulan desde Python).
"""

import plotly.graph_objects as go
import plotly.io as pio

from ui.tema import (
    COLOR_AXIS,
    COLOR_GRID,
    COLOR_TARJETA,
    COLOR_TEXTO_EJE,
    PALETA_DATOS,
)

NOMBRE_PLANTILLA = "sercop"
PLANTILLA_POR_DEFECTO = f"plotly+{NOMBRE_PLANTILLA}"
FUENTE_GRAFICOS = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"
MESES_ABREV_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def etiqueta_mes_es(anio_mes: str) -> str:
    """"2026-03" -> "mar 2026". Si el texto no es AAAA-MM valido se devuelve tal cual (nunca rompe un grafico)."""
    try:
        anio, mes = str(anio_mes).split("-")[:2]
        return f"{MESES_ABREV_ES[int(mes) - 1]} {int(anio)}"
    except (ValueError, IndexError):
        return str(anio_mes)


def construir_plantilla_sercop() -> go.layout.Template:
    eje = dict(
        gridcolor=COLOR_GRID,
        linecolor=COLOR_AXIS,
        zerolinecolor=COLOR_GRID,
        tickfont=dict(color=COLOR_TEXTO_EJE),
        automargin=True,
    )
    return go.layout.Template(
        layout=dict(
            font=dict(family=FUENTE_GRAFICOS, color=COLOR_TEXTO_EJE),
            colorway=PALETA_DATOS,
            paper_bgcolor=COLOR_TARJETA,
            plot_bgcolor=COLOR_TARJETA,
            separators=",.",
            hoverlabel=dict(bgcolor=COLOR_TARJETA, font=dict(family=FUENTE_GRAFICOS, size=13, color=COLOR_TEXTO_EJE)),
            xaxis=eje,
            yaxis=eje,
        )
    )


def registrar_plantilla_sercop() -> None:
    """Registra la plantilla y la deja por defecto. Se puede llamar varias veces."""
    pio.templates[NOMBRE_PLANTILLA] = construir_plantilla_sercop()
    pio.templates.default = PLANTILLA_POR_DEFECTO


def mostrar_grafico(fig, **kwargs):
    """`st.plotly_chart` con `theme=None`: por defecto Streamlit pisa la plantilla con su propio tema (fondo
    `secondaryBackgroundColor`, fuente y colores), y la plantilla `sercop` dejaria de aplicarse."""
    import streamlit as st

    kwargs.setdefault("theme", None)
    return st.plotly_chart(fig, **kwargs)
