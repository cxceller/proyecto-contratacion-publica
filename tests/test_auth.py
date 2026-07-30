"""Tests de autenticacion por API key (src/auth.py) en los endpoints de
escritura (pytest + httpx TestClient)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import auth, database  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App con una base de datos SQLite temporal y una API_KEY de prueba
    activada (sin esto, la autenticacion queda desactivada -- ver
    src/auth.py -- y estos tests no probarian nada)."""
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    monkeypatch.setattr(auth, "API_KEY", "clave-secreta-de-prueba")

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
    def test_post_sin_api_key_devuelve_401(self, client, contratacion_payload):
        response = client.post("/api/todos", json=contratacion_payload)
        assert response.status_code == 401

    def test_post_con_api_key_incorrecta_devuelve_401(self, client, contratacion_payload):
        response = client.post(
            "/api/todos", json=contratacion_payload, headers={"X-API-Key": "incorrecta"}
        )
        assert response.status_code == 401

    def test_post_con_api_key_correcta_funciona(self, client, contratacion_payload):
        response = client.post(
            "/api/todos",
            json=contratacion_payload,
            headers={"X-API-Key": "clave-secreta-de-prueba"},
        )
        assert response.status_code == 201

    def test_delete_todas_sin_api_key_devuelve_401(self, client):
        response = client.delete("/api/todos")
        assert response.status_code == 401

    def test_delete_por_id_sin_api_key_devuelve_401(self, client):
        response = client.delete("/api/todos/1")
        assert response.status_code == 401

    def test_patch_sin_api_key_devuelve_401(self, client):
        response = client.patch("/api/todos/1", json={"estado": "Finalizada"})
        assert response.status_code == 401

    def test_generar_reporte_sin_api_key_devuelve_401(self, client):
        response = client.post(
            "/api/generar-reporte",
            json={
                "palabras_clave": ["algo"],
                "fecha_inicio": "2026-01-01",
                "fecha_fin": "2026-12-31",
            },
        )
        assert response.status_code == 401

    def test_get_no_requiere_api_key(self, client):
        response = client.get("/api/todos")
        assert response.status_code == 200
