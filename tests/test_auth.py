"""Tests de autenticacion por API key (src/auth.py, fail-closed) en los
endpoints de escritura (pytest + httpx TestClient).

No usa el fixture `client` compartido de conftest.py (que ya manda el
header X-API-Key correcto en toda request): estos tests necesitan armar
sus propios clientes, con y sin ese header, para probar exactamente los
casos de autenticacion en si."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import auth, database  # noqa: E402

API_KEY_PRUEBA = "clave-secreta-de-prueba"


@pytest.fixture()
def client_sin_header(tmp_path, monkeypatch):
    """API_KEY configurada del lado del servidor, pero el cliente NO manda
    ningun header por defecto (cada test agrega el que necesite probar)."""
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    monkeypatch.setattr(auth, "API_KEY", API_KEY_PRUEBA)

    from src.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client_sin_configurar(tmp_path, monkeypatch):
    """El servidor NO tiene ninguna API_KEY configurada (caso por defecto
    en un despliegue sin esa variable de entorno seteada)."""
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    monkeypatch.setattr(auth, "API_KEY", None)

    from src.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def contratacion_payload():
    return {
        "codigo": "SIE-001-2026",
        "entidad_contratante": "GAD Municipal de Quito",
        "objeto_proceso": "Adquisicion de equipos informaticos",
        "estado": "Adjudicada",
        "provincia_canton": "Pichincha / Quito",
        "presupuesto_referencial": 15000.50,
        "fecha_publicacion": "2026-01-15",
    }


class TestAutenticacion:
    def test_post_sin_api_key_devuelve_401(self, client_sin_header, contratacion_payload):
        response = client_sin_header.post("/api/todos", json=contratacion_payload)
        assert response.status_code == 401

    def test_post_con_api_key_incorrecta_devuelve_401(self, client_sin_header, contratacion_payload):
        response = client_sin_header.post(
            "/api/todos", json=contratacion_payload, headers={"X-API-Key": "incorrecta"}
        )
        assert response.status_code == 401

    def test_post_con_api_key_correcta_funciona(self, client_sin_header, contratacion_payload):
        response = client_sin_header.post(
            "/api/todos",
            json=contratacion_payload,
            headers={"X-API-Key": API_KEY_PRUEBA},
        )
        assert response.status_code == 201

    def test_delete_todas_sin_api_key_devuelve_401(self, client_sin_header):
        response = client_sin_header.delete("/api/todos")
        assert response.status_code == 401

    def test_delete_por_id_sin_api_key_devuelve_401(self, client_sin_header):
        response = client_sin_header.delete("/api/todos/1")
        assert response.status_code == 401

    def test_patch_sin_api_key_devuelve_401(self, client_sin_header):
        response = client_sin_header.patch("/api/todos/1", json={"estado": "Finalizada"})
        assert response.status_code == 401

    def test_get_no_requiere_api_key(self, client_sin_header):
        response = client_sin_header.get("/api/todos")
        assert response.status_code == 200


class TestFailClosedSinConfigurar:
    """Si el servidor no tiene API_KEY configurada, los endpoints
    protegidos deben rechazar TODO -- incluso con un header presente --
    en vez de dejar pasar las solicitudes sin proteccion real."""

    def test_post_sin_api_key_configurada_devuelve_401(
        self, client_sin_configurar, contratacion_payload
    ):
        response = client_sin_configurar.post("/api/todos", json=contratacion_payload)
        assert response.status_code == 401

    def test_post_con_cualquier_header_sin_api_key_configurada_devuelve_401(
        self, client_sin_configurar, contratacion_payload
    ):
        response = client_sin_configurar.post(
            "/api/todos", json=contratacion_payload, headers={"X-API-Key": "lo-que-sea"}
        )
        assert response.status_code == 401

    def test_delete_sin_api_key_configurada_devuelve_401(self, client_sin_configurar):
        response = client_sin_configurar.delete("/api/todos")
        assert response.status_code == 401

    def test_get_sigue_abierto_sin_api_key_configurada(self, client_sin_configurar):
        response = client_sin_configurar.get("/api/todos")
        assert response.status_code == 200
