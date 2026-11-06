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


class TestCoherenciaDeLasTarjetas:
    """Series alineadas, badge que nombra el mes, montos compactos y fuente vendorizada."""

    def _df(self, pares):
        from app_ui import _df_con_anio_mes

        return _df_con_anio_mes(_registros(pares))

    def test_meses_continuos_sin_huecos(self):
        from app_ui import _meses_continuos

        assert _meses_continuos(self._df([("2026-01", 1), ("2026-04", 1)])) == [
            "2026-01", "2026-02", "2026-03", "2026-04",
        ]

    def test_serie_alineada_rellena_con_cero_los_meses_sin_datos(self):
        from app_ui import _meses_continuos, _serie_alineada

        df = self._df([("2026-01", 10), ("2026-03", 5), ("2026-03", 7)])
        meses = _meses_continuos(df)
        assert _serie_alineada(df, meses, "presupuesto_referencial") == [10.0, 0.0, 12.0]
        assert _serie_alineada(df, meses) == [1.0, 0.0, 2.0]

    def test_series_de_subconjuntos_usan_el_mismo_rango(self):
        # "En contratacion" empezaba en otro mes: ahora las tres series tienen la misma longitud
        from app_ui import _meses_continuos, _serie_alineada

        base = self._df([("2026-01", 1), ("2026-02", 1), ("2026-06", 1)])
        subconjunto = self._df([("2026-06", 1)])
        meses = _meses_continuos(base)
        assert len(_serie_alineada(subconjunto, meses, "presupuesto_referencial")) == len(meses) == 6

    def test_detalle_nombra_el_mes_y_compara_con_el_anterior(self):
        from app_ui import _detalle_ultimo_mes

        d = _detalle_ultimo_mes([36.0, 12.0], ["2026-10", "2026-11"], lambda v: f"{v:.0f}")
        assert d["mes"] == "nov 2026" and d["mes_previo"] == "oct 2026"
        assert d["valor"] == "12" and d["valor_previo"] == "36" and round(d["pct"], 1) == -66.7

    def test_detalle_sin_mes_previo_comparable(self):
        from app_ui import _detalle_ultimo_mes

        assert _detalle_ultimo_mes([0.0, 5.0], ["2026-10", "2026-11"])["pct"] is None
        assert _detalle_ultimo_mes([5.0], ["2026-11"])["mes_previo"] is None
        assert _detalle_ultimo_mes([], []) is None

    def test_moneda_compacta(self):
        from scripts.formato_ec import formatear_moneda_compacta_ec as c

        assert c(35_990_000) == "$ 35,99 M" and c(1_234_567_890) == "$ 1,23 mil M"
        assert c(45_678) == "$ 45,68 mil" and c(123.4) == "$ 123,40" and c(-2_500_000) == "-$ 2,50 M"
        assert c(None) == "" and c(float("nan")) == ""


class TestFuenteVendorizada:
    def test_estilos_no_usan_inter_ni_google_fonts(self):
        import estilos_sercop

        assert "Inter" not in estilos_sercop.CSS and "googleapis" not in estilos_sercop.CSS
        assert "gstatic" not in estilos_sercop.CSS and "@import" not in estilos_sercop.CSS
        assert "font-family:'IBM Plex Sans'" in estilos_sercop.CSS

    def test_los_archivos_de_la_fuente_existen_y_estan_referenciados(self):
        import re
        from pathlib import Path

        import estilos_sercop

        raiz = Path(__file__).resolve().parent.parent
        urls = re.findall(r"url\('/app/static/([^']+)'\)", estilos_sercop.CSS)
        assert len(urls) == 4
        for u in urls:
            assert (raiz / "static" / u).is_file(), u
        assert (raiz / "static" / "fonts" / "ibm-plex-sans" / "LICENSE.txt").is_file()

    def test_streamlit_sirve_static(self):
        from pathlib import Path

        config = (Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        assert "enableStaticServing = true" in config
