"""Tests del sanitizador por lista blanca (scripts/sanitizar_html.py)."""
import pytest

from scripts.sanitizar_html import sanitizar_html_enriquecido as limpiar

DATA_PNG = "data:image/png;base64,iVBORw0KGgo="


class TestVectoresXSS:
    @pytest.mark.parametrize(
        "entrada",
        [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            '<img src="x" onerror="alert(1)">',
            "<svg onload=alert(1)></svg>",
            '<svg><script>alert(1)</script></svg>',
            '<a href="javascript:alert(1)">x</a>',
            '<a href="JaVaScRiPt:alert(1)">x</a>',
            '<a href="  javascript:alert(1)">x</a>',
            '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
            '<img src="data:text/html;base64,PHNjcmlwdD4=">',
            '<img src="data:image/svg+xml;base64,PHN2Zz4=">',
            '<iframe src="https://evil"></iframe>',
            '<object data="x"></object><embed src="x">',
            '<div onclick="alert(1)">x</div>',
            '<body onload="alert(1)">',
            '<form action="https://evil"><input></form>',
            "<style>body{background:url(javascript:alert(1))}</style>",
            '<p style="background:url(javascript:alert(1))">x</p>',
            '<p style="width: expression(alert(1))">x</p>',
            '<p style="color:red;position:fixed;top:0">x</p>',
            '<math><mtext><script>alert(1)</script></mtext></math>',
            "<!--<script>alert(1)</script>-->",
        ],
    )
    def test_no_queda_nada_ejecutable(self, entrada):
        salida = limpiar(entrada).lower()
        for peligro in ("<script", "onerror", "onload", "onclick", "javascript:", "<iframe", "<object", "<embed",
                        "<svg", "<form", "<style", "expression(", "url(", "position", "text/html", "svg+xml"):
            assert peligro not in salida, (entrada, salida)


class TestContenidoLegitimo:
    def test_conserva_formato_basico_y_tablas(self):
        html = "<p>Hola <b>mundo</b></p><ul><li>uno</li></ul><table><tr><td colspan='2'>x</td></tr></table>"
        salida = limpiar(html)
        assert "<b>mundo</b>" in salida and "<li>uno</li>" in salida and 'colspan="2"' in salida

    def test_conserva_estilos_seguros(self):
        salida = limpiar('<p style="text-align: center; color: #333; font-weight: bold">x</p>')
        assert "text-align: center" in salida and "color: #333" in salida

    def test_quita_solo_el_estilo_peligroso(self):
        salida = limpiar('<p style="text-align:center; position:fixed">x</p>')
        assert "text-align: center" in salida and "position" not in salida

    def test_enlaces_http_y_mailto_con_rel(self):
        salida = limpiar('<a href="https://compraspublicas.gob.ec">c</a><a href="mailto:a@b.ec">m</a>')
        assert 'href="https://compraspublicas.gob.ec"' in salida
        assert 'href="mailto:a@b.ec"' in salida and "noopener noreferrer" in salida

    def test_imagen_pegada_como_data_uri_png_se_conserva(self):
        assert f'src="{DATA_PNG}"' in limpiar(f'<img src="{DATA_PNG}" width="100">')

    def test_conserva_tildes_y_enie(self):
        assert "Ñandú canción" in limpiar("<p>Ñandú canción</p>")

    def test_vacio_y_none(self):
        assert limpiar("") == "" and limpiar(None) == ""
