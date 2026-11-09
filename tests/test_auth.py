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

    def test_get_ahora_requiere_api_key(self, client_sin_header):
        # Antes los GET eran abiertos; ahora tambien exigen la clave (ver TestLecturaProtegida).
        response = client_sin_header.get("/api/todos")
        assert response.status_code in (401, 403)


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

    def test_get_tambien_se_rechaza_sin_api_key_configurada(self, client_sin_configurar):
        response = client_sin_configurar.get("/api/todos")
        assert response.status_code in (401, 403)


class TestDocumentacionEnProduccion:
    """/docs, /redoc y /openapi.json no se publican en produccion."""

    def test_en_produccion_se_desactivan(self, monkeypatch):
        from src import main

        monkeypatch.setenv("APP_ENV", "production")
        assert main._opciones_documentacion() == {"docs_url": None, "redoc_url": None, "openapi_url": None}

    def test_en_cloud_run_se_desactivan(self, monkeypatch):
        from src import main

        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("K_SERVICE", "sercop")
        assert main._opciones_documentacion()["openapi_url"] is None

    def test_en_desarrollo_siguen_activas(self, monkeypatch):
        from src import main

        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)
        assert main._opciones_documentacion() == {}

    def test_una_app_creada_en_produccion_no_sirve_openapi(self, monkeypatch):
        import importlib

        from fastapi.testclient import TestClient

        from src import main

        monkeypatch.setenv("APP_ENV", "production")
        recargado = importlib.reload(main)
        try:
            with TestClient(recargado.app) as c:
                assert c.get("/openapi.json").status_code == 404
                assert c.get("/docs").status_code == 404
        finally:
            monkeypatch.delenv("APP_ENV", raising=False)
            importlib.reload(main)


class TestLecturaProtegida:
    """Los GET tambien exigen API key (los borradores contienen datos personales)."""

    RUTAS_GET = ["/api/todos", "/api/todos/1", "/api/borradores", "/api/borradores/1"]

    @pytest.mark.parametrize("ruta", RUTAS_GET)
    def test_sin_clave_es_401(self, client_sin_header, ruta):
        assert client_sin_header.get(ruta).status_code in (401, 403)

    @pytest.mark.parametrize("ruta", RUTAS_GET)
    def test_clave_incorrecta_es_401(self, client_sin_header, ruta):
        assert client_sin_header.get(ruta, headers={"X-API-Key": "incorrecta"}).status_code in (401, 403)

    @pytest.mark.parametrize("ruta", RUTAS_GET)
    def test_servidor_sin_clave_configurada_rechaza(self, client_sin_configurar, ruta):
        assert client_sin_configurar.get(ruta, headers={"X-API-Key": "cualquiera"}).status_code in (401, 403)

    def test_clave_correcta_lista_con_200(self, client_sin_header):
        cabecera = {"X-API-Key": API_KEY_PRUEBA}
        assert client_sin_header.get("/api/todos", headers=cabecera).status_code == 200
        assert client_sin_header.get("/api/borradores", headers=cabecera).status_code == 200

    def test_clave_correcta_en_recurso_inexistente_es_404_no_401(self, client_sin_header):
        cabecera = {"X-API-Key": API_KEY_PRUEBA}
        assert client_sin_header.get("/api/todos/999", headers=cabecera).status_code == 404
        assert client_sin_header.get("/api/borradores/999", headers=cabecera).status_code == 404

    def test_el_401_no_revela_datos(self, client_sin_header):
        respuesta = client_sin_header.get("/api/todos")
        assert respuesta.json() == {"detail": "API key invalida o faltante (header X-API-Key)"}


class TestLaUIMandaLaClave:
    """services/sercop.api_request agrega X-API-Key en cada llamada (incluidos los GET)."""

    def test_api_request_envia_x_api_key_en_get(self, monkeypatch):
        from services import sercop

        capturado = {}

        class Respuesta:
            status_code = 200

            def json(self):
                return []

        def falso_request(metodo, url, timeout=None, **kwargs):
            capturado.update(metodo=metodo, url=url, headers=kwargs.get("headers", {}))
            return Respuesta()

        monkeypatch.setenv("API_KEY", "clave-de-la-ui")
        monkeypatch.setattr(sercop.requests, "request", falso_request)
        sercop.api_request("GET", "/api/borradores")
        assert capturado["metodo"] == "GET" and capturado["headers"]["X-API-Key"] == "clave-de-la-ui"

    def test_la_ui_de_punta_a_punta_lee_con_la_clave(self, client_sin_header, monkeypatch):
        """Integracion: services.sercop contra la API real (TestClient) con la clave del entorno."""
        from services import sercop

        def request_via_testclient(metodo, url, timeout=None, **kwargs):
            ruta = url.replace(sercop.API_URL, "")
            return client_sin_header.request(metodo, ruta, headers=kwargs.get("headers"), params=kwargs.get("params"))

        monkeypatch.setenv("API_KEY", API_KEY_PRUEBA)
        monkeypatch.setattr(sercop.requests, "request", request_via_testclient)
        respuesta = sercop.api_request("GET", "/api/todos")
        assert respuesta.status_code == 200
        monkeypatch.delenv("API_KEY")
        assert sercop.api_request("GET", "/api/todos").status_code in (401, 403)
