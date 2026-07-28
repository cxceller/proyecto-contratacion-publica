"""Tests del endpoint de generacion de reportes (pytest + httpx TestClient)."""
import sys
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import database  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App con una base de datos SQLite temporal y aislada por test."""
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))

    from src.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def contratacion_payload():
    return {
        "codigo": "SIE-001-2026",
        "entidad_contratante": "GAD Municipal de Quito",
        "objeto_proceso": "Adquisicion de luminarias LED de prueba",
        "estado": "Adjudicada",
        "provincia_canton": "Pichincha / Quito",
        "presupuesto_referencial": 15000.50,
        "fecha_publicacion": "2026-03-15",
        # Palabra clave sin coincidencia en capturas/ real, para que el test
        # no dependa de que existan archivos en esa carpeta.
        "palabra_clave": "clave-de-prueba-inexistente",
    }


def crear_contratacion(client, payload):
    response = client.post("/api/todos", json=payload)
    assert response.status_code == 201
    return response.json()


class TestGenerarReporte:
    def test_genera_reporte_valido(self, client, contratacion_payload):
        crear_contratacion(client, contratacion_payload)

        response = client.post(
            "/api/generar-reporte",
            json={
                "palabras_clave": ["clave-de-prueba-inexistente"],
                "fecha_inicio": "2026-01-01",
                "fecha_fin": "2026-12-31",
            },
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert "reporte_contrataciones.docx" in response.headers["content-disposition"]

        documento = Document(BytesIO(response.content))
        texto_completo = "\n".join(p.text for p in documento.paragraphs)
        assert "clave-de-prueba-inexistente" in texto_completo
        assert "EXISTEN 1 PROCESOS" in texto_completo
        assert len(documento.tables) == 1
        assert len(documento.tables[0].rows) == 2  # encabezado + 1 fila de datos

    def test_filtra_por_lote_id(self, client, contratacion_payload):
        crear_contratacion(client, {**contratacion_payload, "lote_id": "lote-A"})
        crear_contratacion(
            client, {**contratacion_payload, "codigo": "SIE-002-2026", "lote_id": "lote-B"}
        )

        response = client.post(
            "/api/generar-reporte",
            json={
                "palabras_clave": ["clave-de-prueba-inexistente"],
                "fecha_inicio": "2026-01-01",
                "fecha_fin": "2026-12-31",
                "lote_id": "lote-A",
            },
        )

        assert response.status_code == 200
        documento = Document(BytesIO(response.content))
        texto_completo = "\n".join(p.text for p in documento.paragraphs)
        assert "EXISTEN 1 PROCESOS" in texto_completo

    def test_busqueda_insensible_a_tildes_y_mayusculas(self, client, contratacion_payload):
        """SQLite LIKE (sin extensiones ICU) solo pliega mayusculas/
        minusculas en el rango ASCII: 'REPOTENCIACIÓN' con tilde no
        coincidia con una busqueda de 'repotenciacion' sin tilde. Este test
        reproduce exactamente ese caso (dato guardado con tilde y
        mayusculas, busqueda en minusculas y sin tilde)."""
        crear_contratacion(
            client,
            {**contratacion_payload, "codigo": "SIE-003-2026", "palabra_clave": "REPOTENCIACIÓN"},
        )

        response = client.post(
            "/api/generar-reporte",
            json={
                "palabras_clave": ["repotenciacion"],
                "fecha_inicio": "2026-01-01",
                "fecha_fin": "2026-12-31",
            },
        )

        assert response.status_code == 200
        documento = Document(BytesIO(response.content))
        texto_completo = "\n".join(p.text for p in documento.paragraphs)
        assert "EXISTEN 1 PROCESOS" in texto_completo

    def test_sin_resultados_devuelve_404(self, client):
        response = client.post(
            "/api/generar-reporte",
            json={
                "palabras_clave": ["palabra-que-no-existe-en-ningun-proceso"],
                "fecha_inicio": "2026-01-01",
                "fecha_fin": "2026-12-31",
            },
        )
        assert response.status_code == 404

    def test_sin_palabras_clave_devuelve_422(self, client):
        response = client.post(
            "/api/generar-reporte",
            json={
                "palabras_clave": [],
                "fecha_inicio": "2026-01-01",
                "fecha_fin": "2026-12-31",
            },
        )
        assert response.status_code == 422
