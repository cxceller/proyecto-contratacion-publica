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


class TestPeriodoYFormatoEcuador:
    """Texto explicito de los badges, periodo del sparkline y porcentajes con coma decimal."""

    def test_etiqueta_mes_en_espanol(self):
        from app_ui import _etiqueta_mes

        assert _etiqueta_mes("2025-01") == "ene 2025" and _etiqueta_mes("2025-12") == "dic 2025"

    def test_periodo_es_el_rango_de_meses_de_la_serie(self):
        from app_ui import _df_con_anio_mes, _periodo_mensual_desde_df

        df = _df_con_anio_mes(_registros([("2026-03", 1), ("2026-01", 1), ("2026-05", 1)]))
        assert _periodo_mensual_desde_df(df) == "ene 2026 – may 2026"

    def test_periodo_de_un_solo_mes_y_sin_datos(self):
        import pandas as pd

        from app_ui import _df_con_anio_mes, _periodo_mensual_desde_df

        assert _periodo_mensual_desde_df(_df_con_anio_mes(_registros([("2026-03", 1)]))) == "mar 2026"
        assert _periodo_mensual_desde_df(pd.DataFrame()) is None
        assert _periodo_mensual_desde_df(_df_con_anio_mes([{"fecha_publicacion": None}])) is None

    def test_serie_de_conteo_mensual(self):
        from app_ui import _df_con_anio_mes, _serie_conteo_mensual_desde_df

        df = _df_con_anio_mes(_registros([("2026-02", 5), ("2026-01", 9), ("2026-01", 1)]))
        assert _serie_conteo_mensual_desde_df(df) == [2.0, 1.0]

    def test_insignia_de_participacion_es_explicita_y_con_coma(self):
        from app_ui import _insignia_participacion

        assert _insignia_participacion(1, 7) == "14,3 % del total"
        assert _insignia_participacion(5, 0) is None

    def test_porcentaje_de_ahorro_con_coma(self):
        from app_ui import _formatear_porcentaje_ahorro

        assert _formatear_porcentaje_ahorro(51.58) == "🟢 51,58 %"
        assert _formatear_porcentaje_ahorro(-12.3) == "🔴 -12,30 %"
        assert _formatear_porcentaje_ahorro(None) == ""

    def test_formato_de_fecha_de_la_ui_es_dd_mm_aaaa(self):
        from app_ui import FORMATO_FECHA_UI

        assert FORMATO_FECHA_UI == "DD/MM/YYYY"
