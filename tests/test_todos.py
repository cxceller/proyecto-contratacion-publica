"""Tests de la API de contratacion publica (pytest + httpx TestClient).

El fixture `client` (con base de datos temporal y API_KEY de prueba ya
configurada) vive en tests/conftest.py y se comparte con toda la suite."""


import pytest


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


def crear_contratacion(client, payload):
    response = client.post("/api/todos", json=payload)
    assert response.status_code == 201
    return response.json()


class TestPost:
    def test_crear_contratacion_valida(self, client, contratacion_payload):
        creada = crear_contratacion(client, contratacion_payload)
        assert creada["codigo"] == contratacion_payload["codigo"]
        assert creada["estado"] == "Adjudicada"
        assert creada["palabra_clave"] is None
        assert creada["url"] is None
        assert "id" in creada

    def test_crear_contratacion_con_palabra_clave(self, client, contratacion_payload):
        contratacion_payload["palabra_clave"] = "luminarias"
        creada = crear_contratacion(client, contratacion_payload)
        assert creada["palabra_clave"] == "luminarias"

    def test_crear_contratacion_con_url(self, client, contratacion_payload):
        contratacion_payload["url"] = (
            "https://www.compraspublicas.gob.ec/.../informacionProcesoContratacion2.cpe?idSoliCompra=ABC123,"
        )
        creada = crear_contratacion(client, contratacion_payload)
        assert creada["url"] == contratacion_payload["url"]

    def test_crear_contratacion_invalida_devuelve_422(self, client):
        response = client.post(
            "/api/todos",
            json={
                "codigo": "",
                "entidad_contratante": "",
                "objeto_proceso": "obj",
                "estado": "Adjudicada",
            },
        )
        assert response.status_code == 422

    def test_crear_contratacion_presupuesto_negativo_devuelve_422(
        self, client, contratacion_payload
    ):
        contratacion_payload["presupuesto_referencial"] = -100
        response = client.post("/api/todos", json=contratacion_payload)
        assert response.status_code == 422


class TestGetTodos:
    def test_listar_contrataciones_vacio(self, client):
        response = client.get("/api/todos")
        assert response.status_code == 200
        assert response.json() == []

    def test_listar_contrataciones(self, client, contratacion_payload):
        crear_contratacion(client, contratacion_payload)
        response = client.get("/api/todos")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["codigo"] == contratacion_payload["codigo"]

    def test_filtrar_por_status_prefijo(self, client, contratacion_payload):
        contratacion_payload["estado"] = "Adjudicado - Contratado"
        crear_contratacion(client, contratacion_payload)

        response = client.get("/api/todos", params={"estado": "Adjudicado -"})
        assert response.status_code == 200
        assert len(response.json()) == 1

        response_sin_match = client.get("/api/todos", params={"estado": "Desierta"})
        assert response_sin_match.status_code == 200
        assert response_sin_match.json() == []

    def test_filtrar_por_palabra_clave(self, client, contratacion_payload):
        contratacion_payload["palabra_clave"] = "luminarias"
        crear_contratacion(client, contratacion_payload)

        otro_payload = {**contratacion_payload, "codigo": "SIE-002-2026", "palabra_clave": "camaras"}
        crear_contratacion(client, otro_payload)

        response = client.get("/api/todos", params={"palabra_clave": "lumin"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["palabra_clave"] == "luminarias"

        response_sin_match = client.get("/api/todos", params={"palabra_clave": "inexistente"})
        assert response_sin_match.status_code == 200
        assert response_sin_match.json() == []

    def test_filtrar_por_palabra_clave_insensible_a_tildes_y_mayusculas(
        self, client, contratacion_payload
    ):
        contratacion_payload["palabra_clave"] = "REPOTENCIACIÓN"
        crear_contratacion(client, contratacion_payload)

        response = client.get("/api/todos", params={"palabra_clave": "repotenciacion"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["palabra_clave"] == "REPOTENCIACIÓN"


class TestGetById:
    def test_obtener_contratacion_existente(self, client, contratacion_payload):
        creada = crear_contratacion(client, contratacion_payload)
        response = client.get(f"/api/todos/{creada['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == creada["id"]

    def test_obtener_contratacion_inexistente_devuelve_404(self, client):
        response = client.get("/api/todos/9999")
        assert response.status_code == 404
        assert "no encontrado" in response.json()["detail"]


class TestPatch:
    def test_actualizar_estado(self, client, contratacion_payload):
        creada = crear_contratacion(client, contratacion_payload)
        response = client.patch(
            f"/api/todos/{creada['id']}", json={"estado": "Finalizada"}
        )
        assert response.status_code == 200
        assert response.json()["estado"] == "Finalizada"
        assert response.json()["codigo"] == contratacion_payload["codigo"]

    def test_actualizar_contratacion_inexistente_devuelve_404(self, client):
        response = client.patch("/api/todos/9999", json={"estado": "Finalizada"})
        assert response.status_code == 404

    def test_actualizar_sin_campos_devuelve_400(self, client, contratacion_payload):
        creada = crear_contratacion(client, contratacion_payload)
        response = client.patch(f"/api/todos/{creada['id']}", json={})
        assert response.status_code == 400


class TestDelete:
    def test_eliminar_contratacion_existente(self, client, contratacion_payload):
        creada = crear_contratacion(client, contratacion_payload)
        response = client.delete(f"/api/todos/{creada['id']}")
        assert response.status_code == 204

        response_get = client.get(f"/api/todos/{creada['id']}")
        assert response_get.status_code == 404

    def test_eliminar_contratacion_inexistente_devuelve_404(self, client):
        response = client.delete("/api/todos/9999")
        assert response.status_code == 404


class TestDeleteTodas:
    def test_vaciar_base_de_datos(self, client, contratacion_payload):
        crear_contratacion(client, contratacion_payload)
        crear_contratacion(client, {**contratacion_payload, "codigo": "SIE-002-2026"})

        response = client.delete("/api/todos")
        assert response.status_code == 204

        response_lista = client.get("/api/todos")
        assert response_lista.json() == []

    def test_vaciar_base_de_datos_vacia_no_falla(self, client):
        response = client.delete("/api/todos")
        assert response.status_code == 204
