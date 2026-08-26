"""Tests de scripts/analizar_oficios_desierta.py: solo la funcion pura
`extraer_oficios` (regex sobre texto, sin red/navegador) -- mismo criterio
que tests/test_scrape_portal.py, que tampoco prueba las funciones que
navegan con Playwright, solo el parseo determinístico."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analizar_oficios_desierta import extraer_oficios  # noqa: E402


class TestExtraerOficios:
    def test_un_solo_oficio(self):
        motivo = (
            "De acuerdo con la recomendación del SERCOP, contenida en el oficio Nro. "
            "SERCOP-DSP-2026-6563-OF, y a lo establecido en el artículo 31 de la LOSNCP"
        )
        assert extraer_oficios(motivo) == ["SERCOP-DSP-2026-6563-OF"]

    def test_varios_oficios_sin_duplicados_en_orden(self):
        motivo = (
            "En respuesta al oficio SERCOP-DSP-2026-5363-OF, y conforme al oficio "
            "SERCOP-DSP-2026-6563-OF, se declara desierto. Ref: SERCOP-DSP-2026-5363-OF."
        )
        assert extraer_oficios(motivo) == ["SERCOP-DSP-2026-5363-OF", "SERCOP-DSP-2026-6563-OF"]

    def test_insensible_a_mayusculas_normaliza_a_mayuscula(self):
        assert extraer_oficios("oficio sercop-dsp-2026-6563-of citado") == ["SERCOP-DSP-2026-6563-OF"]

    def test_sin_oficio_devuelve_lista_vacia(self):
        assert extraer_oficios("Desierta por falta de ofertas, sin más detalle.") == []

    def test_motivo_none_devuelve_lista_vacia(self):
        assert extraer_oficios(None) == []

    def test_prefijo_de_area_de_dos_o_mas_letras(self):
        # El patron exige {2,} letras en el prefijo de area (DSP, DNCP, etc.)
        assert extraer_oficios("oficio SERCOP-DNCP-2025-0042-OF") == ["SERCOP-DNCP-2025-0042-OF"]
