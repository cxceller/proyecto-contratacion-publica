"""Tests de scripts/actualizar_motivos_desierta.py: base de datos SQLite
temporal (mismo patron que db_temporal en test_actualizar_montos_adjudicados.py)
y dobles falsos de Playwright/_obtener_motivos (mismo patron de "fake"
explicito que ese archivo) -- nunca se abre un navegador real ni se visita
el portal."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import actualizar_motivos_desierta  # noqa: E402
from scripts.actualizar_motivos_desierta import _procesos_pendientes, actualizar  # noqa: E402
from src import database  # noqa: E402

ENTIDAD = "Municipalidad de Guayaquil"


@pytest.fixture()
def db_temporal(tmp_path, monkeypatch):
    """Mismo mecanismo que db_temporal en test_actualizar_montos_adjudicados.py."""
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return db_file


def _crear_proceso_desierta(
    codigo: str,
    entidad_contratante: str = "MUNICIPALIDAD DE GUAYAQUIL",
    url: str | None = "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/informacionProcesoContratacion2.cpe?idSoliCompra=1",
    motivo_estado_raw: str | None = None,
) -> int:
    return database.upsert_contratacion(
        {
            "codigo": codigo,
            "entidad_contratante": entidad_contratante,
            "objeto_proceso": "Objeto de prueba",
            "estado": "Desierta",
            "url": url,
            "motivo_estado_raw": motivo_estado_raw,
        }
    )


class TestProcesosPendientes:
    def test_incluye_solo_los_que_tienen_url_y_sin_motivo(self, db_temporal):
        _crear_proceso_desierta("SIE-001")  # candidato valido
        _crear_proceso_desierta("SIE-002", url=None)  # sin url
        _crear_proceso_desierta("SIE-003", motivo_estado_raw="ya tiene motivo")  # ya completo
        database.upsert_contratacion(  # otro estado, no debe aparecer
            {
                "codigo": "SIE-004",
                "entidad_contratante": "MUNICIPALIDAD DE GUAYAQUIL",
                "objeto_proceso": "Objeto",
                "estado": "Suspendido",
                "url": "https://www.compraspublicas.gob.ec/x",
            }
        )

        pendientes = _procesos_pendientes(entidad=None)

        assert {p["codigo"] for p in pendientes} == {"SIE-001"}

    def test_filtra_por_entidad_insensible_a_mayusculas(self, db_temporal):
        _crear_proceso_desierta("SIE-005", entidad_contratante="MUNICIPALIDAD DE GUAYAQUIL")
        _crear_proceso_desierta("SIE-006", entidad_contratante="OTRA ENTIDAD")

        pendientes = _procesos_pendientes(entidad=ENTIDAD)

        assert {p["codigo"] for p in pendientes} == {"SIE-005"}


class _FakeBrowser:
    async def new_context(self, user_agent=None):
        return object()

    async def close(self):
        pass


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
    def __init__(self):
        self.browser = _FakeBrowser()

    async def __aenter__(self):
        return _FakePlaywrightInstance(self.browser)

    async def __aexit__(self, *exc_info):
        return False


def _fake_obtener_motivos(mapa_urls_capturado: dict, motivos: dict):
    """Doble de _obtener_motivos: registra la clave real con la que se lo
    llamo (para verificar que es `codigo`) y devuelve el dict {codigo:
    motivo} tal como la funcion real."""

    async def _fake(context, mapa_urls):
        mapa_urls_capturado.update(mapa_urls)
        return motivos

    return _fake


class TestActualizar:
    def test_actualiza_por_codigo(self, db_temporal, monkeypatch):
        _crear_proceso_desierta("SIE-010")
        _crear_proceso_desierta("SIE-011")

        urls_capturadas: dict[str, str] = {}
        monkeypatch.setattr(
            actualizar_motivos_desierta,
            "_obtener_motivos",
            _fake_obtener_motivos(
                urls_capturadas,
                motivos={
                    "SIE-010": "Desierta\nRazón: ofertas inhabilitadas.",
                    "SIE-011": "Desierta\nRazón: sin ofertas presentadas.",
                },
            ),
        )
        monkeypatch.setattr(actualizar_motivos_desierta, "async_playwright", _FakeAsyncPlaywright)

        actualizados, sin_motivo, con_error = asyncio.run(actualizar(entidad=ENTIDAD))

        assert (actualizados, sin_motivo, con_error) == (2, 0, 0)
        assert set(urls_capturadas.keys()) == {"SIE-010", "SIE-011"}

        filas = {r["codigo"]: r for r in database.get_all_contrataciones()}
        assert filas["SIE-010"]["motivo_estado_raw"] == "Desierta\nRazón: ofertas inhabilitadas."
        assert filas["SIE-011"]["motivo_estado_raw"] == "Desierta\nRazón: sin ofertas presentadas."

    def test_proceso_sin_motivo_en_la_respuesta_queda_pendiente(self, db_temporal, monkeypatch):
        _crear_proceso_desierta("SIE-012")

        urls_capturadas: dict[str, str] = {}
        monkeypatch.setattr(
            actualizar_motivos_desierta,
            "_obtener_motivos",
            _fake_obtener_motivos(urls_capturadas, motivos={}),
        )
        monkeypatch.setattr(actualizar_motivos_desierta, "async_playwright", _FakeAsyncPlaywright)

        actualizados, sin_motivo, con_error = asyncio.run(actualizar(entidad=ENTIDAD))

        assert (actualizados, sin_motivo, con_error) == (0, 1, 0)
        fila = database.get_all_contrataciones()[0]
        assert fila["motivo_estado_raw"] is None

    def test_sin_procesos_pendientes_no_abre_navegador(self, db_temporal, monkeypatch):
        def _no_deberia_llamarse(*_args, **_kwargs):
            raise AssertionError("no deberia lanzarse Playwright sin procesos pendientes")

        monkeypatch.setattr(actualizar_motivos_desierta, "async_playwright", _no_deberia_llamarse)

        actualizados, sin_motivo, con_error = asyncio.run(actualizar(entidad=ENTIDAD))

        assert (actualizados, sin_motivo, con_error) == (0, 0, 0)
