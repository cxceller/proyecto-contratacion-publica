"""Tests de las funciones puras detras de render_kpi_card_tendencia
(app_ui.py): _serie_mensual (agregacion mensual desde una lista de
registros crudos) y _variacion_pct_ultimo_periodo (variación % del
ultimo periodo de una serie vs. el anterior). No prueban
render_kpi_card_tendencia en si (requiere Streamlit) -- mismo criterio
que el resto de tests de app_ui.py, que solo cubren las funciones puras."""
from datetime import UTC

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
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        # hoy fijo posterior a nov: ambos meses estan completos
        d = _detalle_ultimo_mes([36.0, 12.0], ["2026-10", "2026-11"], lambda v: f"{v:.0f}", hoy=date(2026, 12, 15))
        assert d["mes"] == "nov 2026" and d["mes_previo"] == "oct 2026"
        assert d["valor"] == "12" and d["valor_previo"] == "36" and round(d["pct"], 1) == -66.7

    def test_detalle_sin_mes_previo_comparable(self):
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        hoy = date(2026, 12, 15)
        assert _detalle_ultimo_mes([0.0, 5.0], ["2026-10", "2026-11"], hoy=hoy)["pct"] is None
        assert _detalle_ultimo_mes([5.0], ["2026-11"], hoy=hoy)["mes_previo"] is None
        assert _detalle_ultimo_mes([], [], hoy=hoy) is None

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


class TestMesCompletoVsEnCurso:
    """El badge compara el ultimo mes COMPLETO con el anterior; el mes en curso se rotula aparte, sin porcentaje.
    Todas con fechas fijas (America/Guayaquil)."""

    MESES = ["2026-08", "2026-09", "2026-10", "2026-11"]

    def test_hoy_en_guayaquil_es_utc_menos_5(self):
        from datetime import date, datetime

        from app_ui import _hoy_guayaquil

        assert _hoy_guayaquil(datetime(2026, 11, 6, 15, 0, tzinfo=UTC)) == date(2026, 11, 6)
        # 03:00 UTC del 1 de diciembre todavia es 30 de noviembre en Ecuador (22:00)
        assert _hoy_guayaquil(datetime(2026, 12, 1, 3, 0, tzinfo=UTC)) == date(2026, 11, 30)
        assert _hoy_guayaquil(datetime(2026, 12, 1, 5, 0)) == date(2026, 12, 1)  # naive = UTC

    def test_mes_en_curso_no_se_compara_oct_vs_sep(self):
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        d = _detalle_ultimo_mes([10.0, 20.0, 30.0, 5.0], self.MESES, lambda v: f"{v:.0f}", hoy=date(2026, 11, 6))
        assert d["parcial"] is True
        assert d["mes"] == "oct 2026" and d["mes_corto"] == "oct" and d["mes_previo"] == "sep 2026"
        assert d["valor"] == "30" and d["valor_previo"] == "20" and d["pct"] == 50.0  # +50 %, no -83 %
        assert d["en_curso"]["mes"] == "nov 2026" and d["en_curso"]["valor"] == "5"

    def test_al_cerrar_el_mes_ya_se_compara_noviembre(self):
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        d = _detalle_ultimo_mes([10.0, 20.0, 30.0, 5.0], self.MESES, lambda v: f"{v:.0f}", hoy=date(2026, 12, 1))
        assert d["parcial"] is False and d["en_curso"] is None
        assert d["mes"] == "nov 2026" and round(d["pct"], 1) == -83.3

    def test_el_limite_de_mes_usa_la_fecha_de_guayaquil_no_utc(self):
        from datetime import datetime

        from app_ui import _detalle_ultimo_mes, _hoy_guayaquil

        hoy = _hoy_guayaquil(datetime(2026, 12, 1, 3, 0, tzinfo=UTC))  # 30/11 en Ecuador
        assert _detalle_ultimo_mes([10.0, 20.0, 30.0, 5.0], self.MESES, hoy=hoy)["parcial"] is True

    def test_si_los_datos_terminan_antes_del_mes_actual_todo_esta_completo(self):
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        d = _detalle_ultimo_mes([20.0, 30.0], ["2026-09", "2026-10"], hoy=date(2026, 11, 6))
        assert d["parcial"] is False and d["mes"] == "oct 2026" and d["pct"] == 50.0

    def test_solo_el_mes_en_curso_no_tiene_porcentaje(self):
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        d = _detalle_ultimo_mes([5.0], ["2026-11"], lambda v: f"{v:.0f}", hoy=date(2026, 11, 6))
        assert d["parcial"] is True and d["mes"] is None and d["pct"] is None
        assert d["en_curso"]["mes"] == "nov 2026"

    def test_un_mes_completo_y_el_en_curso_no_dan_porcentaje(self):
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        d = _detalle_ultimo_mes([30.0, 5.0], ["2026-10", "2026-11"], hoy=date(2026, 11, 6))
        assert d["mes"] == "oct 2026" and d["pct"] is None and d["mes_previo"] is None

    def test_mes_previo_en_cero_no_da_porcentaje(self):
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        assert _detalle_ultimo_mes([0.0, 7.0, 3.0], ["2026-09", "2026-10", "2026-11"], hoy=date(2026, 11, 6))["pct"] is None

    def test_serie_vacia(self):
        from datetime import date

        from app_ui import _detalle_ultimo_mes

        assert _detalle_ultimo_mes([], [], hoy=date(2026, 11, 6)) is None


class TestSparklineParcial:
    def test_con_mes_en_curso_el_ultimo_tramo_es_punteado_y_el_punto_hueco(self):
        from app_ui import _figura_sparkline

        fig = _figura_sparkline([1.0, 2.0, 3.0, 1.0], parcial=True)
        assert len(fig.data) == 3
        assert list(fig.data[0].y) == [1.0, 2.0, 3.0] and fig.data[0].line.dash is None  # meses completos: continua
        assert fig.data[1].line.dash == "dot" and list(fig.data[1].y) == [3.0, 1.0]  # tramo parcial: punteado
        assert fig.data[2].mode == "markers" and fig.data[2].marker.color == "#FFFFFF"  # punto hueco

    def test_sin_parcial_es_una_sola_linea(self):
        from app_ui import _figura_sparkline

        fig = _figura_sparkline([1.0, 2.0, 3.0])
        assert len(fig.data) == 1 and fig.data[0].mode == "lines"


class TestCifraPrincipalCorta:
    def test_formato_corto_con_un_decimal(self):
        from scripts.formato_ec import formatear_moneda_compacta_ec as c

        assert c(242_532_054.24, decimales=1) == "$ 242,5 M"
        assert c(122_680_393.95, decimales=1) == "$ 122,7 M"
        assert c(35_990_000, decimales=1) == "$ 36,0 M"

    def test_total_lleva_pie_de_texto_no_badge(self):
        from app_ui import _tarjeta_kpi_html

        html_total = _tarjeta_kpi_html("Total", "337", pie="procesos registrados")
        assert "procesos registrados" in html_total and "<span" not in html_total
        con_insignia = _tarjeta_kpi_html("Adjudicada", "5", insignia="1,5 % del total")
        assert "<span>1,5 % del total</span>" in con_insignia


class TestTarjetaAhorro:
    """El "% de Ahorro General" ya no es un gauge: tarjeta KPI con cifra, barra de progreso y significado."""

    def test_cifra_barra_y_significado(self):
        from app_ui import _tarjeta_ahorro_html

        h = _tarjeta_ahorro_html(39.8, "ayuda <b>")
        assert "39,8%" in h and 'role="progressbar"' in h and "width:39.8%" in h
        assert "por debajo del presupuesto referencial" in h
        assert "\n" not in h and "<b>" not in h  # una sola linea y la ayuda va escapada

    def test_la_barra_se_satura_sin_romper(self):
        from app_ui import _tarjeta_ahorro_html

        assert "width:100.0%" in _tarjeta_ahorro_html(250.0)
        negativo = _tarjeta_ahorro_html(-5.0)
        assert "width:0.0%" in negativo and "por encima del presupuesto referencial" in negativo


class TestCategoriaUnica:
    def test_el_aviso_nombra_la_categoria_y_no_dibuja_barra(self, monkeypatch):
        import app_ui

        mensajes = []
        monkeypatch.setattr(app_ui.st, "info", lambda texto, **kw: mensajes.append(texto))
        app_ui._aviso_categoria_unica("Provincia/Cantón", "GUAYAS / GUAYAQUIL", 70, 526783688.55)
        assert len(mensajes) == 1
        assert "GUAYAS / GUAYAQUIL" in mensajes[0] and "70" in mensajes[0] and "526.783.688,55" in mensajes[0]
