"""Tests del formato numerico/monetario de Ecuador (scripts/formato_ec.py):
punto de miles, coma decimal, simbolo $ para moneda."""
import math

from scripts.formato_ec import (
    formatear_moneda_ec,
    formatear_numero_ec,
    formatear_porcentaje_ec,
    limpiar_texto_libre,
)


class TestFormatearPorcentajeEC:
    def test_un_decimal_con_coma(self):
        assert formatear_porcentaje_ec(12.345) == "12,3%"

    def test_cero_y_cien(self):
        assert formatear_porcentaje_ec(0) == "0,0%"
        assert formatear_porcentaje_ec(100) == "100,0%"

    def test_vacio_y_nan(self):
        assert formatear_porcentaje_ec(None) == ""
        assert formatear_porcentaje_ec(float("nan")) == ""


class TestLimpiarTextoLibre:
    def test_none_da_cadena_vacia(self):
        assert limpiar_texto_libre(None) == ""

    def test_conserva_enie_y_tildes(self):
        assert limpiar_texto_libre("  Ñandú   canción ") == "Ñandú canción"

    def test_normaliza_unicode_a_nfc(self):
        assert limpiar_texto_libre("ñ") == "ñ"

    def test_elimina_caracteres_de_control_y_ancho_cero(self):
        assert limpiar_texto_libre("lumi\x00na​ri\x07as﻿") == "luminarias"

    def test_colapsa_saltos_de_linea_y_espacios(self):
        assert limpiar_texto_libre("a\n\t b") == "a b"

    def test_limita_longitud(self):
        assert len(limpiar_texto_libre("x" * 5000, max_len=100)) == 100

    def test_no_interpreta_html(self):
        # El saneador no escapa (eso es del punto de salida), pero no debe romperse.
        assert limpiar_texto_libre("<script>alert(1)</script>") == "<script>alert(1)</script>"

    def test_infinito_se_muestra_vacio(self):
        assert formatear_numero_ec(float("inf")) == ""
        assert formatear_numero_ec(float("-inf")) == ""


class TestFormatearNumeroEC:
    def test_miles_y_decimales(self):
        assert formatear_numero_ec(1234567.89) == "1.234.567,89"

    def test_ejemplo_del_enunciado(self):
        assert formatear_numero_ec(9106285.46) == "9.106.285,46"

    def test_entero_sin_decimales_por_defecto(self):
        assert formatear_numero_ec(10000) == "10.000"

    def test_entero_menor_a_mil_sin_separador(self):
        assert formatear_numero_ec(10) == "10"

    def test_decimales_forzados(self):
        assert formatear_numero_ec(10, decimales=2) == "10,00"

    def test_valor_none_da_cadena_vacia(self):
        assert formatear_numero_ec(None) == ""

    def test_cadena_vacia_da_cadena_vacia(self):
        assert formatear_numero_ec("") == ""

    def test_nan_da_cadena_vacia(self):
        assert formatear_numero_ec(float("nan")) == ""

    def test_acepta_string_numerico(self):
        assert formatear_numero_ec("9106285.46") == "9.106.285,46"


class TestFormatearMonedaEC:
    def test_ejemplo_del_enunciado(self):
        assert formatear_moneda_ec(9106285.46) == "$ 9.106.285,46"

    def test_valor_none_da_cadena_vacia(self):
        assert formatear_moneda_ec(None) == ""

    def test_simbolo_personalizado(self):
        assert formatear_moneda_ec(1000, simbolo="USD") == "USD 1.000,00"
