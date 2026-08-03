"""Tests del formato numerico/monetario de Ecuador (scripts/formato_ec.py):
punto de miles, coma decimal, simbolo $ para moneda."""
import math

from scripts.formato_ec import formatear_moneda_ec, formatear_numero_ec


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
