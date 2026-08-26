"""Tests de scripts/explicar_estado_desierta.py: base de datos SQLite
temporal (mismo patron que el fixture `client` de conftest.py, aca sin
pasar por la API -- se llama a database.* directo) y una funcion RAG falsa
inyectada en `enriquecer(explicar_fn=...)` -- nunca se llama al RAG real
(Proyecto_02) por HTTP."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.explicar_estado_desierta import enriquecer  # noqa: E402
from src import database  # noqa: E402


class ExplicarDesiertaFalso:
    """Doble de services.criterio_juridico.explicar_desierta: misma firma
    (motivo_raw, objeto, codigo) -> dict | None. `respuestas` es una cola
    de resultados (uno por llamada esperada); un dict se devuelve tal
    cual (simulando 200 OK del RAG), None simula que el RAG no respondio
    o fallo (mismo contrato que la funcion real, que nunca lanza)."""

    def __init__(self, respuestas: list):
        self._respuestas = list(respuestas)
        self.llamadas = 0
        self.ultima_llamada: dict | None = None

    def __call__(self, motivo_raw: str, objeto: str = "", codigo: str = "") -> dict | None:
        self.llamadas += 1
        self.ultima_llamada = {"motivo_raw": motivo_raw, "objeto": objeto, "codigo": codigo}
        return self._respuestas.pop(0)


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


class TestEnriquecer:
    def test_sin_procesos_pendientes_no_llama_al_rag(self, db_temporal):
        explicar_fn = ExplicarDesiertaFalso(respuestas=[])
        explicados, con_error = enriquecer(explicar_fn=explicar_fn)
        assert (explicados, con_error) == (0, 0)
        assert explicar_fn.llamadas == 0

    def test_explica_proceso_desierta_pendiente(self, db_temporal):
        _crear_proceso_desierta("SIE-001", "Razón: ofertas inhabilitadas.")
        explicar_fn = ExplicarDesiertaFalso(
            respuestas=[
                {
                    "explicacion": "Se declaró desierto porque las ofertas no eran válidas.",
                    "causal_legal": "Art. 31 literal b) LOSNCP",
                    "fuentes": ["Art. 31 LOSNCP"],
                }
            ]
        )

        explicados, con_error = enriquecer(explicar_fn=explicar_fn)

        assert (explicados, con_error) == (1, 0)
        filas = database.get_all_contrataciones(status="Desierta")
        assert filas[0]["explicacion_estado"] == "Se declaró desierto porque las ofertas no eran válidas."

    def test_limite_corta_el_lote_a_los_primeros_n_pendientes(self, db_temporal):
        """`--limite 1` (prueba controlada antes del lote completo): con 3
        procesos pendientes, solo se llama a explicar_fn una vez."""
        _crear_proceso_desierta("SIE-010", "motivo uno")
        _crear_proceso_desierta("SIE-011", "motivo dos")
        _crear_proceso_desierta("SIE-012", "motivo tres")
        explicar_fn = ExplicarDesiertaFalso(
            respuestas=[{"explicacion": "Explicación única.", "causal_legal": "Art. 31 LOSNCP", "fuentes": []}]
        )

        explicados, con_error = enriquecer(explicar_fn=explicar_fn, limite=1)

        assert (explicados, con_error) == (1, 0)
        assert explicar_fn.llamadas == 1

    def test_pasa_motivo_objeto_y_codigo_a_explicar_fn(self, db_temporal):
        contratacion_id = database.upsert_contratacion(
            {
                "codigo": "SIE-006",
                "entidad_contratante": "MUNICIPALIDAD DE GUAYAQUIL",
                "objeto_proceso": "Adquisición de luminarias",
                "estado": "Desierta",
                "motivo_estado_raw": "No se presentaron ofertas.",
            }
        )
        assert contratacion_id
        explicar_fn = ExplicarDesiertaFalso(respuestas=[{"explicacion": "Explicación.", "causal_legal": "", "fuentes": []}])

        enriquecer(explicar_fn=explicar_fn)

        assert explicar_fn.ultima_llamada == {
            "motivo_raw": "No se presentaron ofertas.",
            "objeto": "Adquisición de luminarias",
            "codigo": "SIE-006",
        }

    def test_no_reexplica_procesos_ya_explicados(self, db_temporal):
        _crear_proceso_desierta("SIE-002", "motivo", explicacion_estado="ya explicado antes")
        explicar_fn = ExplicarDesiertaFalso(respuestas=[])

        explicados, con_error = enriquecer(explicar_fn=explicar_fn)

        assert (explicados, con_error) == (0, 0)
        assert explicar_fn.llamadas == 0

    def test_ignora_procesos_desierta_sin_motivo_estado_raw(self, db_temporal):
        _crear_proceso_desierta("SIE-003", motivo_estado_raw=None)
        explicar_fn = ExplicarDesiertaFalso(respuestas=[])

        explicados, con_error = enriquecer(explicar_fn=explicar_fn)

        assert (explicados, con_error) == (0, 0)
        assert explicar_fn.llamadas == 0

    def test_rag_no_disponible_no_interrumpe_el_resto_del_lote(self, db_temporal):
        """El cliente RAG (services/criterio_juridico.py) nunca lanza: ante
        cualquier fallo (red, timeout, status != 200) devuelve None -- mismo
        contrato que se prueba aca con la respuesta None de la cola."""
        _crear_proceso_desierta("SIE-004", "motivo que falla")
        _crear_proceso_desierta("SIE-005", "motivo que funciona")
        explicar_fn = ExplicarDesiertaFalso(
            respuestas=[None, {"explicacion": "Explicación generada con éxito.", "causal_legal": "", "fuentes": []}]
        )

        explicados, con_error = enriquecer(explicar_fn=explicar_fn)

        assert (explicados, con_error) == (1, 1)

    def test_respuesta_del_rag_sin_explicacion_cuenta_como_error(self, db_temporal):
        _crear_proceso_desierta("SIE-007", "motivo")
        explicar_fn = ExplicarDesiertaFalso(respuestas=[{"explicacion": "", "causal_legal": "", "fuentes": []}])

        explicados, con_error = enriquecer(explicar_fn=explicar_fn)

        assert (explicados, con_error) == (0, 1)
