"""Tests de la API de borradores de contratacion (pytest + httpx TestClient).

El fixture `client` (con base de datos temporal y API_KEY de prueba ya
configurada) vive en tests/conftest.py y se comparte con toda la suite."""

import json

import pytest


@pytest.fixture()
def borrador_payload():
    return {
        "nombre_contratacion": "Adquisición de Luminarias",
        "datos_json": json.dumps({"anexo1_objeto_contratacion": "Adquisición de Luminarias"}),
    }


def crear_borrador(client, payload):
    response = client.post("/api/borradores", json=payload)
    assert response.status_code == 201
    return response.json()


class TestPost:
    def test_crear_borrador_valido(self, client, borrador_payload):
        creado = crear_borrador(client, borrador_payload)
        assert creado["nombre_contratacion"] == borrador_payload["nombre_contratacion"]
        assert creado["datos_json"] == borrador_payload["datos_json"]
        assert "id" in creado
        assert "fecha_actualizacion" in creado

    def test_crear_borrador_sin_nombre_devuelve_422(self, client):
        response = client.post(
            "/api/borradores", json={"nombre_contratacion": "", "datos_json": "{}"}
        )
        assert response.status_code == 422

    def test_crear_borrador_sin_api_key_devuelve_401(self, client, borrador_payload):
        response = client.post(
            "/api/borradores", json=borrador_payload, headers={"X-API-Key": ""}
        )
        assert response.status_code == 401


class TestGet:
    def test_listar_borradores_vacio(self, client):
        response = client.get("/api/borradores")
        assert response.status_code == 200
        assert response.json() == []

    def test_listar_borradores_no_incluye_datos_json(self, client, borrador_payload):
        crear_borrador(client, borrador_payload)
        response = client.get("/api/borradores")
        assert response.status_code == 200
        [resumen] = response.json()
        assert resumen["nombre_contratacion"] == borrador_payload["nombre_contratacion"]
        assert "datos_json" not in resumen

    def test_obtener_borrador_por_id(self, client, borrador_payload):
        creado = crear_borrador(client, borrador_payload)
        response = client.get(f"/api/borradores/{creado['id']}")
        assert response.status_code == 200
        assert response.json()["datos_json"] == borrador_payload["datos_json"]

    def test_obtener_borrador_inexistente_devuelve_404(self, client):
        response = client.get("/api/borradores/9999")
        assert response.status_code == 404


class TestPut:
    def test_actualizar_borrador_reemplaza_datos_json(self, client, borrador_payload):
        creado = crear_borrador(client, borrador_payload)
        nuevo_payload = {
            "nombre_contratacion": "Adquisición de Luminarias LED",
            "datos_json": json.dumps({"anexo1_objeto_contratacion": "Adquisición de Luminarias LED"}),
        }
        response = client.put(f"/api/borradores/{creado['id']}", json=nuevo_payload)
        assert response.status_code == 200
        actualizado = response.json()
        assert actualizado["id"] == creado["id"]
        assert actualizado["nombre_contratacion"] == nuevo_payload["nombre_contratacion"]
        assert actualizado["datos_json"] == nuevo_payload["datos_json"]

    def test_actualizar_borrador_inexistente_devuelve_404(self, client, borrador_payload):
        response = client.put("/api/borradores/9999", json=borrador_payload)
        assert response.status_code == 404


class TestDelete:
    def test_eliminar_borrador(self, client, borrador_payload):
        creado = crear_borrador(client, borrador_payload)
        response = client.delete(f"/api/borradores/{creado['id']}")
        assert response.status_code == 204
        assert client.get(f"/api/borradores/{creado['id']}").status_code == 404

    def test_eliminar_borrador_inexistente_devuelve_404(self, client):
        response = client.delete("/api/borradores/9999")
        assert response.status_code == 404

    def test_eliminar_borrador_sin_api_key_devuelve_401(self, client, borrador_payload):
        creado = crear_borrador(client, borrador_payload)
        response = client.delete(f"/api/borradores/{creado['id']}", headers={"X-API-Key": ""})
        assert response.status_code == 401
