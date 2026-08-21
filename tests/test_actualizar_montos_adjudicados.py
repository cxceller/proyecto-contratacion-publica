"""Tests de scripts/actualizar_montos_adjudicados.py: base de datos SQLite
temporal (mismo patron que db_temporal en test_explicar_estado_desierta.py)
y dobles falsos de Playwright/_obtener_montos_adjudicados (mismo patron de
"fake" explicito que ClienteLLMFalso en ese mismo archivo) -- nunca se abre
un navegador real ni se visita el portal.

TestActualizar cubre especificamente el bug que motivo este archivo: antes
del fix, `montos = await _obtener_montos_adjudicados(...)` guardaba la tupla
completa `(montos, motivos)` en vez de desempaquetarla, y `mapa_urls` se
armaba con el `id` en vez del `codigo` -- lo segundo rompia en silencio la
deteccion de procesos VPN (_es_proceso_produccion_nacional mira el prefijo
del codigo, no del id). Si cualquiera de los dos reaparece, estos tests
fallan: el primero con un AttributeError real (no mockeado), el segundo
porque el monto del proceso VPN quedaria sin actualizar."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import actualizar_montos_adjudicados  # noqa: E402
from scripts.actualizar_montos_adjudicados import (  # noqa: E402
    _es_estado_adjudicable,
    _procesos_pendientes,
    actualizar,
)
from src import database  # noqa: E402

ENTIDAD = "Municipalidad de Guayaquil"


@pytest.fixture()
def db_temporal(tmp_path, monkeypatch):
    """Mismo mecanismo que db_temporal en test_explicar_estado_desierta.py."""
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return db_file


def _crear_proceso(
    codigo: str,
    estado: str,
    entidad_contratante: str = "MUNICIPALIDAD DE GUAYAQUIL",
    url: str | None = "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/informacionProcesoContratacion2.cpe?idSoliCompra=1",
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


class TestEsEstadoAdjudicable:
    @pytest.mark.parametrize(
        "estado",
        [
            "Adjudicado - Registro de Contratos",
            "Ejecución de Contrato",
            "En Recepción",
            "Finalizada",
            "Finalizado por mutuo acuerdo",
            "adjudicado - registro de contratos",  # insensible a mayusculas
            "ADJUDICADO - REGISTRO DE CONTRATOS",
            "Adjudicado -",  # version truncada, ver NOMBRES_ESTADO_COMPLETOS en app_ui.py
            "Ejecución de",  # idem
        ],
    )
    def test_estados_adjudicables(self, estado):
        assert _es_estado_adjudicable(estado) is True

    @pytest.mark.parametrize(
        "estado",
        [
            "Desierta",
            "Suspendido",
            "Calificación de Participantes",
            "Preguntas, Respuestas y Aclaraciones",
            "Por Adjudicar",
            None,
            "",
        ],
    )
    def test_estados_no_adjudicables(self, estado):
        assert _es_estado_adjudicable(estado) is False


class TestProcesosPendientes:
    def test_incluye_solo_los_que_tienen_url_sin_monto_y_estado_adjudicable(self, db_temporal):
        _crear_proceso("SIE-001", "Finalizada")  # candidato valido
        _crear_proceso("SIE-002", "Desierta")  # estado no adjudicable
        _crear_proceso("SIE-003", "Finalizada", url=None)  # sin url
        _crear_proceso("SIE-004", "Finalizada", monto_adjudicado=41060.00)  # ya completo

        pendientes = _procesos_pendientes(entidad=None)

        assert {p["codigo"] for p in pendientes} == {"SIE-001"}

    def test_filtra_por_entidad_insensible_a_mayusculas(self, db_temporal):
        _crear_proceso("SIE-005", "Finalizada", entidad_contratante="MUNICIPALIDAD DE GUAYAQUIL")
        _crear_proceso("SIE-006", "Finalizada", entidad_contratante="OTRA ENTIDAD")

        pendientes = _procesos_pendientes(entidad=ENTIDAD)

        assert {p["codigo"] for p in pendientes} == {"SIE-005"}


class _FakeBrowser:
    def __init__(self):
        self.cerrado = False

    async def new_context(self, user_agent=None):
        return object()

    async def close(self):
        self.cerrado = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser):
        self._browser = browser

    async def launch(self, headless=True):
        assert headless is True, "el script debe seguir corriendo headless"
        return self._browser


class _FakePlaywrightInstance:
    def __init__(self, browser: _FakeBrowser):
        self.chromium = _FakeChromium(browser)


class _FakeAsyncPlaywright:
    """Doble del context manager que devuelve `async_playwright()` real."""

    def __init__(self):
        self.browser = _FakeBrowser()

    async def __aenter__(self):
        return _FakePlaywrightInstance(self.browser)

    async def __aexit__(self, *exc_info):
        return False


def _fake_obtener_montos_adjudicados(mapa_urls_capturado: dict, montos: dict, motivos: dict):
    """Doble de _obtener_montos_adjudicados: registra la clave real con la
    que se lo llamo (para verificar que es `codigo`, no `id`) y devuelve la
    tupla (montos, motivos) tal como la funcion real -- nunca un solo dict."""

    async def _fake(context, mapa_urls):
        mapa_urls_capturado.update(mapa_urls)
        return montos, motivos

    return _fake


class TestActualizar:
    def test_actualiza_por_codigo_sin_romper_con_la_tupla(self, db_temporal, monkeypatch):
        _crear_proceso("SIE-010", "Finalizada")
        _crear_proceso("VPN-MIMG-2026-001", "Finalizada")

        urls_capturadas: dict[str, str] = {}
        monkeypatch.setattr(
            actualizar_montos_adjudicados,
            "_obtener_montos_adjudicados",
            _fake_obtener_montos_adjudicados(
                urls_capturadas,
                montos={"SIE-010": 41060.00, "VPN-MIMG-2026-001": 410000.00},
                motivos={},
            ),
        )
        monkeypatch.setattr(actualizar_montos_adjudicados, "async_playwright", _FakeAsyncPlaywright)

        actualizados, sin_adjudicar, con_error = asyncio.run(actualizar(entidad=ENTIDAD))

        assert (actualizados, sin_adjudicar, con_error) == (2, 0, 0)
        # La clave que recibe _obtener_montos_adjudicados debe ser el
        # codigo real (incluido el prefijo VPN-), nunca el id numerico.
        assert set(urls_capturadas.keys()) == {"SIE-010", "VPN-MIMG-2026-001"}

        filas = {r["codigo"]: r for r in database.get_all_contrataciones()}
        assert filas["SIE-010"]["monto_adjudicado"] == 41060.00
        assert filas["VPN-MIMG-2026-001"]["monto_adjudicado"] == 410000.00

    def test_proceso_sin_monto_en_la_respuesta_queda_sin_adjudicar(self, db_temporal, monkeypatch):
        _crear_proceso("SIE-011", "Finalizada")

        urls_capturadas: dict[str, str] = {}
        monkeypatch.setattr(
            actualizar_montos_adjudicados,
            "_obtener_montos_adjudicados",
            _fake_obtener_montos_adjudicados(urls_capturadas, montos={}, motivos={}),
        )
        monkeypatch.setattr(actualizar_montos_adjudicados, "async_playwright", _FakeAsyncPlaywright)

        actualizados, sin_adjudicar, con_error = asyncio.run(actualizar(entidad=ENTIDAD))

        assert (actualizados, sin_adjudicar, con_error) == (0, 1, 0)
        fila = database.get_all_contrataciones()[0]
        assert fila["monto_adjudicado"] is None

    def test_procesos_en_estado_no_adjudicable_nunca_se_visitan(self, db_temporal, monkeypatch):
        _crear_proceso("SIE-012", "Desierta")

        urls_capturadas: dict[str, str] = {}
        monkeypatch.setattr(
            actualizar_montos_adjudicados,
            "_obtener_montos_adjudicados",
            _fake_obtener_montos_adjudicados(urls_capturadas, montos={}, motivos={}),
        )
        monkeypatch.setattr(actualizar_montos_adjudicados, "async_playwright", _FakeAsyncPlaywright)

        actualizados, sin_adjudicar, con_error = asyncio.run(actualizar(entidad=ENTIDAD))

        assert (actualizados, sin_adjudicar, con_error) == (0, 0, 0)
        assert urls_capturadas == {}

    def test_sin_procesos_pendientes_no_abre_navegador(self, db_temporal, monkeypatch):
        def _no_deberia_llamarse(*_args, **_kwargs):
            raise AssertionError("no deberia lanzarse Playwright sin procesos pendientes")

        monkeypatch.setattr(actualizar_montos_adjudicados, "async_playwright", _no_deberia_llamarse)

        actualizados, sin_adjudicar, con_error = asyncio.run(actualizar(entidad=ENTIDAD))

        assert (actualizados, sin_adjudicar, con_error) == (0, 0, 0)
