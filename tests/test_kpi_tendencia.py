"""Tests de las funciones puras detras de render_kpi_card_tendencia
(app_ui.py): _serie_mensual (agregacion mensual desde una lista de
registros crudos) y _variacion_pct_ultimo_periodo (variación % del
ultimo periodo de una serie vs. el anterior). No prueban
render_kpi_card_tendencia en si (requiere Streamlit) -- mismo criterio
que el resto de tests de app_ui.py, que solo cubren las funciones puras."""
from app_ui import _serie_mensual, _variacion_pct_ultimo_periodo


def _registros(pares: list[tuple[str, float]]) -> list[dict]:
    return [{"fecha_publicacion": f"{fecha}-01", "presupuesto_referencial": monto} for fecha, monto in pares]


class TestSerieMensual:
    def test_agrega_por_mes_ordenado_cronologicamente(self):
        registros = _registros([("2026-03", 100), ("2026-01", 50), ("2026-01", 25), ("2026-02", 10)])
        assert _serie_mensual(registros, "presupuesto_referencial") == [75, 10, 100]

    def test_sin_registros_devuelve_lista_vacia(self):
        assert _serie_mensual([], "presupuesto_referencial") == []

    def test_ignora_registros_sin_fecha_publicacion(self):
        registros = [
            {"fecha_publicacion": "2026-01-01", "presupuesto_referencial": 100},
            {"fecha_publicacion": None, "presupuesto_referencial": 999},
        ]
        assert _serie_mensual(registros, "presupuesto_referencial") == [100]

    def test_campo_distinto_a_presupuesto_referencial(self):
        registros = [
            {"fecha_publicacion": "2026-01-01", "monto_adjudicado": 40},
            {"fecha_publicacion": "2026-02-01", "monto_adjudicado": 60},
        ]
        assert _serie_mensual(registros, "monto_adjudicado") == [40, 60]


class TestVariacionPctUltimoPeriodo:
    def test_calcula_variacion_ultimo_vs_anterior(self):
        assert _variacion_pct_ultimo_periodo([100, 150]) == 50.0

    def test_variacion_negativa(self):
        assert _variacion_pct_ultimo_periodo([200, 100]) == -50.0

    def test_menos_de_dos_periodos_devuelve_none(self):
        assert _variacion_pct_ultimo_periodo([100]) is None
        assert _variacion_pct_ultimo_periodo([]) is None

    def test_periodo_anterior_en_cero_devuelve_none(self):
        assert _variacion_pct_ultimo_periodo([0, 100]) is None
