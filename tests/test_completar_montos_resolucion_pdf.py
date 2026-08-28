"""Tests de scripts/completar_montos_resolucion_pdf.py. Las funciones puras
(normaliza_monto, texto_a_numero, extraer_monto_en_letras, validar_monto,
extraer_monto_de_texto) se prueban directo, incluidas contra el fragmento
REAL extraido de la resolucion de PE-MIMG-2025-1 (Municipalidad de
Guayaquil) para no depender de un caso sintetico que no reproduzca el
formato real del portal (separador "´" de millones, "CON XX/100", etc.).
_procesos_pendientes y completar() usan el mismo patron de BD temporal +
dobles de Playwright que test_actualizar_montos_adjudicados.py -- nunca se
abre un navegador real ni se visita el portal."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import completar_montos_resolucion_pdf as mod  # noqa: E402
from scripts.completar_montos_resolucion_pdf import (  # noqa: E402
    _procesos_pendientes,
    completar,
    extraer_monto_de_texto,
    extraer_monto_en_letras,
    normaliza_monto,
    texto_a_numero,
    validar_monto,
)
from src import database  # noqa: E402

ENTIDAD = "Municipalidad de Guayaquil"

# Fragmento real (extraido con PyMuPDF de la resolucion de adjudicacion de
# PE-MIMG-2025-1, portal SERCOP) -- confirma que el pipeline funciona
# contra el formato real, no uno inventado.
TEXTO_REAL_PE_MIMG_2025_1 = (
    "los miembros de la Comisión Técnica, recomiendan a usted en su calidad de Delegado \n"
    "de la Máxima Autoridad ADJUDICAR el proceso de CONCURSO PÚBLICO \n"
    "INTERNACIONAL No. PE-MIMG-2025-1, a la firma consultora \n"
    "oferente: CONSORCIO QUINTO ACUEDUCTO, por un monto de USD$ 2´390.123,53 (DOS MILLONES \n"
    "TRESCIENTOS NOVENTA MIL CIENTO VEINTE Y TRES CON 53/100 DOLARES DE \n"
    "LOS ESTADOS UNIDOS DE AMERICA) más IVA,  con un plazo de ejecución de \n"
    "SETECIENTOS VEINTE (720) DÍAS."
)


class TestNormalizaMonto:
    @pytest.mark.parametrize(
        ("crudo", "esperado"),
        [
            ("2´390.123,53", 2390123.53),  # separador de millones del portal (confirmado real)
            ("1.234.567,89", 1234567.89),  # miles con ".", decimal con ","
            ("1,234,567.89", 1234567.89),  # miles con ",", decimal con "."
            ("100", 100.0),
            ("41060.00", 41060.00),
            ("41060,00", 41060.00),
        ],
    )
    def test_formatos_mezclados(self, crudo, esperado):
        assert normaliza_monto(crudo) == esperado


class TestTextoANumero:
    def test_numero_real_del_pdf(self):
        assert texto_a_numero("DOS MILLONES TRESCIENTOS NOVENTA MIL CIENTO VEINTE Y TRES") == 2_390_123

    def test_veinte_y_tres_con_y_separada(self):
        assert texto_a_numero("VEINTE Y TRES") == 23

    def test_centena_simple(self):
        assert texto_a_numero("CIENTO VEINTE") == 120

    def test_mil_sin_uno_explicito(self):
        assert texto_a_numero("MIL QUINIENTOS") == 1500

    def test_palabra_desconocida_da_none(self):
        assert texto_a_numero("XYZ ABC") is None


class TestExtraerMontoEnLetras:
    def test_fragmento_real(self):
        assert extraer_monto_en_letras(TEXTO_REAL_PE_MIMG_2025_1) == pytest.approx(2_390_123.53)

    def test_sin_parentesis_da_none(self):
        assert extraer_monto_en_letras("no hay nada relevante aca") is None


class TestValidarMonto:
    def test_coincide(self):
        assert validar_monto(2_390_123.53, TEXTO_REAL_PE_MIMG_2025_1) is True

    def test_no_coincide_marca_revisar(self):
        assert validar_monto(999.99, TEXTO_REAL_PE_MIMG_2025_1) is False

    def test_sin_letras_no_bloquea(self):
        assert validar_monto(123.45, "texto sin monto en letras") is True


class TestExtraerMontoDeTexto:
    def test_fragmento_real_completo(self):
        resultado = extraer_monto_de_texto(TEXTO_REAL_PE_MIMG_2025_1)
        assert resultado is not None
        monto, fragmento = resultado
        assert monto == pytest.approx(2_390_123.53)
        assert "DOLARES" in fragmento.upper()

    def test_usd_pegado_al_simbolo(self):
        # "USD\$" debe ir antes que "USD" en la alternancia del patron --
        # confirmado real: el portal escribe "USD$" pegado, sin espacio.
        resultado = extraer_monto_de_texto("adjudicado por un monto de USD$1.500,00 mas IVA")
        assert resultado is not None
        assert resultado[0] == 1500.00

    def test_ultima_coincidencia_gana_sobre_una_recomendacion_previa(self):
        texto = (
            "se recomienda ADJUDICAR por un monto de USD$ 100,00 (CIEN DOLARES). "
            "RESUELVE: ADJUDICAR el contrato por un monto de USD$ 200,00 (DOSCIENTOS DOLARES)."
        )
        resultado = extraer_monto_de_texto(texto)
        assert resultado is not None
        assert resultado[0] == 200.00

    def test_sin_ninguna_plantilla_da_none(self):
        assert extraer_monto_de_texto("texto sin ningun monto mencionado") is None


@pytest.fixture()
def db_temporal(tmp_path, monkeypatch):
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return db_file


def _crear_proceso(
    codigo: str,
    estado: str,
    entidad_contratante: str = "MUNICIPALIDAD DE GUAYAQUIL",
    url: str | None = "https://www.compraspublicas.gob.ec/x?idSoliCompra=1",
    monto_adjudicado: float | None = None,
) -> int:
    return database.upsert_contratacion(
        {
            "codigo": codigo,
            "entidad_contratante": entidad_contratante,
            "objeto_proceso": "Objeto de prueba",
            "estado": estado,
            "url": url,
            "monto_adjudicado": monto_adjudicado,
        }
    )


class TestProcesosPendientes:
    def test_incluye_solo_adjudicada_y_finalizada_sin_monto_con_url(self, db_temporal):
        _crear_proceso("A-1", "Adjudicada")  # candidato valido
        _crear_proceso("A-2", "Finalizada")  # candidato valido
        _crear_proceso("A-3", "Desierta")  # estado fuera de objetivo
        _crear_proceso("A-4", "Adjudicada", url=None)  # sin url
        _crear_proceso("A-5", "Adjudicada", monto_adjudicado=100.0)  # ya completo
        _crear_proceso("A-6", "Adjudicado - Registro de Contratos")  # otro estado, no objetivo aca

        pendientes = _procesos_pendientes(entidad=None)

        assert {p["codigo"] for p in pendientes} == {"A-1", "A-2"}

    def test_filtra_por_entidad(self, db_temporal):
        _crear_proceso("B-1", "Adjudicada", entidad_contratante="MUNICIPALIDAD DE GUAYAQUIL")
        _crear_proceso("B-2", "Adjudicada", entidad_contratante="OTRA ENTIDAD")

        pendientes = _procesos_pendientes(entidad=ENTIDAD)

        assert {p["codigo"] for p in pendientes} == {"B-1"}


class _FakeContext:
    async def new_page(self):
        return object()


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser

    async def launch(self, headless=True):
        assert headless is True, "el script debe seguir corriendo headless"
        return self._browser


class _FakePlaywrightInstance:
    def __init__(self, browser):
        self.chromium = _FakeChromium(browser)


class _FakeAsyncPlaywright:
    def __init__(self):
        self.browser = _FakeBrowserConContext()

    async def __aenter__(self):
        return _FakePlaywrightInstance(self.browser)

    async def __aexit__(self, *exc_info):
        return False


class _FakeBrowserConContext:
    async def new_context(self, user_agent=None):
        return _FakeContext()

    async def close(self):
        pass


class TestCompletar:
    def test_dry_run_no_escribe_en_bd(self, db_temporal, monkeypatch, tmp_path):
        _crear_proceso("C-1", "Adjudicada")

        async def _fake_procesar_uno(context, pagina, proceso):
            return {"codigo": proceso["codigo"], "monto": 555.55, "pdf_url": "https://x/pdf"}

        monkeypatch.setattr(mod, "_procesar_uno", _fake_procesar_uno)
        monkeypatch.setattr(mod, "async_playwright", _FakeAsyncPlaywright)
        monkeypatch.setattr(mod, "_PAUSA_ENTRE_PROCESOS_S", 0)
        monkeypatch.setattr(mod, "RUTA_EXTRAIDOS", tmp_path / "extraidos.csv")
        monkeypatch.setattr(mod, "RUTA_FALLIDOS", tmp_path / "fallidos.csv")

        extraidos, fallidos = asyncio.run(completar(entidad=None, aplicar=False))

        assert len(extraidos) == 1 and not fallidos
        fila = database.get_all_contrataciones()[0]
        assert fila["monto_adjudicado"] is None, "dry-run (sin --apply) no debe escribir en la BD"
        assert (tmp_path / "extraidos.csv").exists()

    def test_apply_escribe_monto_y_metadatos(self, db_temporal, monkeypatch, tmp_path):
        _crear_proceso("D-1", "Finalizada")

        async def _fake_procesar_uno(context, pagina, proceso):
            return {"codigo": proceso["codigo"], "monto": 777.77, "pdf_url": "https://x/resolucion.pdf"}

        monkeypatch.setattr(mod, "_procesar_uno", _fake_procesar_uno)
        monkeypatch.setattr(mod, "async_playwright", _FakeAsyncPlaywright)
        monkeypatch.setattr(mod, "_PAUSA_ENTRE_PROCESOS_S", 0)
        monkeypatch.setattr(mod, "RUTA_EXTRAIDOS", tmp_path / "extraidos.csv")
        monkeypatch.setattr(mod, "RUTA_FALLIDOS", tmp_path / "fallidos.csv")

        asyncio.run(completar(entidad=None, aplicar=True))

        fila = database.get_all_contrataciones()[0]
        assert fila["monto_adjudicado"] == 777.77
        assert fila["monto_origen"] == "resolucion_pdf"
        assert fila["monto_pdf_url"] == "https://x/resolucion.pdf"

    def test_fallidos_no_tocan_la_bd_ni_con_apply(self, db_temporal, monkeypatch, tmp_path):
        _crear_proceso("E-1", "Adjudicada")

        async def _fake_procesar_uno(context, pagina, proceso):
            return {"codigo": proceso["codigo"], "motivo": "sin_pdf_resolucion_adjudicacion"}

        monkeypatch.setattr(mod, "_procesar_uno", _fake_procesar_uno)
        monkeypatch.setattr(mod, "async_playwright", _FakeAsyncPlaywright)
        monkeypatch.setattr(mod, "_PAUSA_ENTRE_PROCESOS_S", 0)
        monkeypatch.setattr(mod, "RUTA_EXTRAIDOS", tmp_path / "extraidos.csv")
        monkeypatch.setattr(mod, "RUTA_FALLIDOS", tmp_path / "fallidos.csv")

        extraidos, fallidos = asyncio.run(completar(entidad=None, aplicar=True))

        assert not extraidos and len(fallidos) == 1
        fila = database.get_all_contrataciones()[0]
        assert fila["monto_adjudicado"] is None

    def test_sin_procesos_pendientes_no_abre_navegador(self, db_temporal, monkeypatch):
        def _no_deberia_llamarse(*_args, **_kwargs):
            raise AssertionError("no deberia lanzarse Playwright sin procesos pendientes")

        monkeypatch.setattr(mod, "async_playwright", _no_deberia_llamarse)

        extraidos, fallidos = asyncio.run(completar(entidad=None, aplicar=False))

        assert extraidos == [] and fallidos == []
