"""Tests de scripts/explicar_estado_desierta.py: base de datos SQLite
temporal (mismo patron que el fixture `client` de conftest.py, aca sin
pasar por la API -- se llama a database.* directo) y un cliente LLM falso
(mismo patron que ClienteLLMFalso en test_importador_parametros.py) --
nunca se llama a la API real de Claude."""
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.explicar_estado_desierta import (  # noqa: E402
    ErrorLLMExplicacionEstado,
    _explicar_motivo,
    enriquecer,
)
from src import database  # noqa: E402


class ClienteLLMFalso:
    """Doble de anthropic.Anthropic(): implementa la misma cadena de
    llamadas que usa _explicar_motivo (`.with_options(...).messages.create(...)`)
    sin tocar la red. `respuestas` es una cola de resultados (uno por
    llamada esperada): un str se devuelve como el texto de respuesta de la
    IA; una excepcion se relanza tal cual, simulando una falla de
    red/timeout."""

    def __init__(self, respuestas: list):
        self._respuestas = list(respuestas)
        self.llamadas = 0

    def with_options(self, **_kwargs):
        return self

    @property
    def messages(self):
        return self

    def create(self, **_kwargs):
        self.llamadas += 1
        dato = self._respuestas.pop(0)
        if isinstance(dato, BaseException):
            raise dato
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=dato)])


@pytest.fixture()
def db_temporal(tmp_path, monkeypatch):
    """Base de datos SQLite temporal y aislada, mismo mecanismo que el
    fixture `client` de tests/conftest.py (monkeypatch de database.DB_PATH)
    pero sin la capa de TestClient/API, ya que enriquecer() llama a
    database.* directamente."""
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    database.init_db()
    return db_file


def _crear_proceso_desierta(
    codigo: str, motivo_estado_raw: str | None, explicacion_estado: str | None = None
) -> int:
    contratacion_id = database.upsert_contratacion(
        {
            "codigo": codigo,
            "entidad_contratante": "MUNICIPALIDAD DE GUAYAQUIL",
            "objeto_proceso": "Objeto de prueba",
            "estado": "Desierta",
            "motivo_estado_raw": motivo_estado_raw,
        }
    )
    if explicacion_estado is not None:
        database.update_contratacion(contratacion_id, {"explicacion_estado": explicacion_estado})
    return contratacion_id


class TestExplicarMotivo:
    def test_devuelve_el_texto_de_la_respuesta(self):
        cliente = ClienteLLMFalso(respuestas=["Quedó desierto porque las ofertas no cumplían los requisitos."])
        assert _explicar_motivo("texto crudo", cliente, "modelo-x") == (
            "Quedó desierto porque las ofertas no cumplían los requisitos."
        )

    def test_error_de_api_se_envuelve_en_error_transitorio(self):
        error_conexion = anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )
        cliente = ClienteLLMFalso(respuestas=[error_conexion])
        with pytest.raises(ErrorLLMExplicacionEstado):
            _explicar_motivo("texto crudo", cliente, "modelo-x")

    def test_respuesta_vacia_lanza_error(self):
        cliente = ClienteLLMFalso(respuestas=["   "])
        with pytest.raises(ErrorLLMExplicacionEstado):
            _explicar_motivo("texto crudo", cliente, "modelo-x")


class TestEnriquecer:
    def test_sin_procesos_pendientes_no_llama_al_llm(self, db_temporal):
        cliente = ClienteLLMFalso(respuestas=[])
        explicados, con_error = enriquecer(cliente_llm=cliente)
        assert (explicados, con_error) == (0, 0)
        assert cliente.llamadas == 0

    def test_explica_proceso_desierta_pendiente(self, db_temporal):
        _crear_proceso_desierta("SIE-001", "Razón: ofertas inhabilitadas.")
        cliente = ClienteLLMFalso(respuestas=["Se declaró desierto porque las ofertas no eran válidas."])

        explicados, con_error = enriquecer(cliente_llm=cliente)

        assert (explicados, con_error) == (1, 0)
        filas = database.get_all_contrataciones(status="Desierta")
        assert filas[0]["explicacion_estado"] == "Se declaró desierto porque las ofertas no eran válidas."

    def test_no_reexplica_procesos_ya_explicados(self, db_temporal):
        _crear_proceso_desierta("SIE-002", "motivo", explicacion_estado="ya explicado antes")
        cliente = ClienteLLMFalso(respuestas=[])

        explicados, con_error = enriquecer(cliente_llm=cliente)

        assert (explicados, con_error) == (0, 0)
        assert cliente.llamadas == 0

    def test_ignora_procesos_desierta_sin_motivo_estado_raw(self, db_temporal):
        _crear_proceso_desierta("SIE-003", motivo_estado_raw=None)
        cliente = ClienteLLMFalso(respuestas=[])

        explicados, con_error = enriquecer(cliente_llm=cliente)

        assert (explicados, con_error) == (0, 0)
        assert cliente.llamadas == 0

    def test_un_error_de_llm_no_interrumpe_el_resto_del_lote(self, db_temporal):
        _crear_proceso_desierta("SIE-004", "motivo que falla")
        _crear_proceso_desierta("SIE-005", "motivo que funciona")
        error_conexion = anthropic.APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )
        cliente = ClienteLLMFalso(respuestas=[error_conexion, "Explicación generada con éxito."])

        explicados, con_error = enriquecer(cliente_llm=cliente)

        assert (explicados, con_error) == (1, 1)
