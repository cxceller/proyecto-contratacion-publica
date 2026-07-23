"""Tests unitarios de las funciones de parseo/mapeo de import_csv.py
(pytest), con casos que simulan errores tipicos del portal de SERCOP:
separadores de miles/decimales en formato latino y anglosajon, simbolos
de moneda mal ubicados, espacios en blanco extra y fechas en formatos
irregulares."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.import_csv import mapear_columnas, parsear_fecha, parsear_presupuesto  # noqa: E402


class TestParsearPresupuesto:
    def test_formato_simple_con_punto_decimal(self):
        assert parsear_presupuesto("15000.50") == 15000.50

    def test_formato_anglosajon_miles_coma_decimal_punto(self):
        # Como viene realmente en la tabla de resultados del portal.
        assert parsear_presupuesto("15,000.50") == 15000.50
        assert parsear_presupuesto("1,515,318.00") == 1515318.00

    def test_formato_latino_miles_punto_decimal_coma(self):
        # Frecuente en presupuestos de obras de infraestructura exportados
        # con formato regional (punto de miles, coma decimal).
        assert parsear_presupuesto("15.000,50") == 15000.50
        assert parsear_presupuesto("1.234.567,89") == 1234567.89

    def test_solo_coma_como_decimal(self):
        assert parsear_presupuesto("45000,50") == 45000.50

    def test_solo_punto_de_miles_sin_decimales(self):
        # "250.000" son 250 mil, no 250,000 (no hay presupuestos con 3
        # decimales en este portal).
        assert parsear_presupuesto("250.000") == 250000.0

    def test_solo_coma_de_miles_sin_decimales(self):
        assert parsear_presupuesto("250,000") == 250000.0

    def test_multiples_puntos_de_miles(self):
        assert parsear_presupuesto("1.234.567") == 1234567.0

    def test_simbolo_moneda_al_inicio(self):
        assert parsear_presupuesto("$30,661.10") == 30661.10

    def test_simbolo_moneda_al_final(self):
        assert parsear_presupuesto("30.661,10 $") == 30661.10

    def test_simbolo_moneda_y_texto_mezclado(self):
        assert parsear_presupuesto("USD 21,940.00") == 21940.00
        assert parsear_presupuesto("21.940,00 dolares") == 21940.00

    def test_espacios_en_blanco_extra(self):
        assert parsear_presupuesto("   15,000.50   ") == 15000.50

    def test_espacio_como_separador_de_miles(self):
        assert parsear_presupuesto("15 000,50") == 15000.50

    def test_valor_negativo(self):
        # La validacion de negativos (ge=0) es responsabilidad de
        # ContratacionCreate, no de este parser.
        assert parsear_presupuesto("-100") == -100.0

    @pytest.mark.parametrize("valor", [None, "", "   ", "nan", "NaN", float("nan")])
    def test_valores_vacios_o_nulos_devuelven_none(self, valor):
        assert parsear_presupuesto(valor) is None

    @pytest.mark.parametrize("valor", ["N/A", "no disponible", "-", "$"])
    def test_texto_no_numerico_devuelve_none(self, valor):
        assert parsear_presupuesto(valor) is None


class TestParsearFecha:
    def test_fecha_iso_simple(self):
        assert parsear_fecha("2026-01-15") == "2026-01-15"

    def test_fecha_iso_con_hora_no_se_confunde_con_dayfirst(self):
        # Bug real detectado: con dayfirst=True a secas, pandas convertia
        # "2025-03-11" (11 de marzo) en 3 de noviembre.
        assert parsear_fecha("2025-03-11 11:00:00") == "2025-03-11"
        assert parsear_fecha("2025-06-05 16:20:00") == "2025-06-05"

    def test_fecha_dd_mm_aaaa_con_barras(self):
        assert parsear_fecha("15/01/2026") == "2026-01-15"

    def test_fecha_dd_mm_aaaa_con_guiones(self):
        assert parsear_fecha("15-01-2026") == "2026-01-15"

    def test_fecha_con_espacios_extra(self):
        assert parsear_fecha("   2026-01-15   ") == "2026-01-15"

    def test_fecha_invalida_devuelve_none(self):
        assert parsear_fecha("2026-13-45") is None
        assert parsear_fecha("31/02/2026") is None

    def test_fecha_en_texto_libre_devuelve_none(self):
        assert parsear_fecha("15 de enero de 2026") is None

    @pytest.mark.parametrize("valor", [None, "", "   ", "nan", "NaN", float("nan")])
    def test_valores_vacios_o_nulos_devuelven_none(self, valor):
        assert parsear_fecha(valor) is None


class TestMapearColumnas:
    def test_mapea_encabezados_reales_del_portal(self):
        df = pd.DataFrame(
            columns=[
                "Código",
                "Entidad Contratante",
                "Objeto del Proceso",
                "Estado del Proceso",
                "Provincia/Cantón",
                "Presupuesto Referencial Total(sin iva)",
                "Fecha de Publicación",
                "Opciones",
            ]
        )
        resultado = mapear_columnas(df)
        assert list(resultado.columns) == [
            "codigo",
            "entidad_contratante",
            "objeto_proceso",
            "estado",
            "provincia_canton",
            "presupuesto_referencial",
            "fecha_publicacion",
        ]

    def test_descarta_columnas_desconocidas(self):
        df = pd.DataFrame(columns=["Codigo", "Columna Desconocida", "Estado"])
        resultado = mapear_columnas(df)
        assert "Columna Desconocida" not in resultado.columns
        assert list(resultado.columns) == ["codigo", "estado"]

    def test_encabezados_alternativos_cortos(self):
        df = pd.DataFrame(columns=["Codigo", "Objeto", "Estado", "Provincia"])
        resultado = mapear_columnas(df)
        assert list(resultado.columns) == [
            "codigo",
            "objeto_proceso",
            "estado",
            "provincia_canton",
        ]

    def test_encabezados_con_espacios_extra_y_mayusculas(self):
        df = pd.DataFrame(columns=["  CÓDIGO  ", "ENTIDAD CONTRATANTE"])
        resultado = mapear_columnas(df)
        assert list(resultado.columns) == ["codigo", "entidad_contratante"]

    def test_conserva_los_datos_de_las_filas(self):
        df = pd.DataFrame(
            {
                "Codigo": ["ABC-1"],
                "Entidad Contratante": ["GAD Quito"],
                "Opciones": ["<botones>"],
            }
        )
        resultado = mapear_columnas(df)
        assert resultado.loc[0, "codigo"] == "ABC-1"
        assert resultado.loc[0, "entidad_contratante"] == "GAD Quito"
        assert "Opciones" not in resultado.columns
