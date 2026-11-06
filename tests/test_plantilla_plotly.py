import plotly.graph_objects as go
import plotly.io as pio
import pytest

from ui import tema
from ui.plantilla_plotly import (
    FUENTE_GRAFICOS,
    NOMBRE_PLANTILLA,
    PLANTILLA_POR_DEFECTO,
    construir_plantilla_sercop,
    etiqueta_mes_es,
    registrar_plantilla_sercop,
)


def test_se_registra_y_es_la_plantilla_por_defecto():
    registrar_plantilla_sercop()
    registrar_plantilla_sercop()  # idempotente
    assert NOMBRE_PLANTILLA in pio.templates
    assert pio.templates.default == PLANTILLA_POR_DEFECTO


def test_fuente_fondo_y_formato_ecuador():
    layout = construir_plantilla_sercop().layout
    assert layout.font.family == FUENTE_GRAFICOS and "IBM Plex Sans" in FUENTE_GRAFICOS
    assert layout.paper_bgcolor == layout.plot_bgcolor == tema.COLOR_TARJETA == "#FFFFFF"
    assert layout.separators == ",."


def test_la_paleta_es_azul_y_no_hay_naranja():
    colores = [c.lower() for c in construir_plantilla_sercop().layout.colorway]
    assert colores == [c.lower() for c in tema.PALETA_DATOS]
    assert "#eb6834" not in colores and tema.COLOR_BARRA_DESTACADA.lower() != "#eb6834"
    # el destacado es un azul: el canal azul domina sobre el rojo
    r, g, b = (int(tema.COLOR_BARRA_DESTACADA[i : i + 2], 16) for i in (1, 3, 5))
    assert b > r


def test_una_figura_nueva_hereda_la_plantilla():
    registrar_plantilla_sercop()
    fig = go.Figure(go.Bar(x=[1], y=["a"]))
    assert fig.layout.template.layout.separators == ",."


@pytest.mark.parametrize(
    "entrada, esperado",
    [("2026-01", "ene 2026"), ("2026-03", "mar 2026"), ("2026-12", "dic 2026"), ("basura", "basura"), ("2026-13", "2026-13")],
)
def test_etiqueta_mes_es(entrada, esperado):
    assert etiqueta_mes_es(entrada) == esperado


def test_mostrar_grafico_desactiva_el_tema_de_streamlit(monkeypatch):
    import streamlit as st

    from ui.plantilla_plotly import mostrar_grafico

    llamadas = []
    monkeypatch.setattr(st, "plotly_chart", lambda fig, **kw: llamadas.append(kw))
    mostrar_grafico(go.Figure(), width="stretch")
    mostrar_grafico(go.Figure(), theme="streamlit")
    assert llamadas[0]["theme"] is None and llamadas[1]["theme"] == "streamlit"
