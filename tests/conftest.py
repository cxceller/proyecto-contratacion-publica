"""Fixtures compartidas por toda la suite.

src/auth.py es fail-closed: sin una API_KEY configurada del lado del
servidor, TODOS los endpoints POST/PATCH/DELETE responden 401. El fixture
`client` de aca abajo configura una API_KEY de prueba y la manda
automaticamente en el header X-API-Key de cada request, para que los tests
de logica de negocio (no de autenticacion en si) no tengan que preocuparse
por eso. tests/test_auth.py arma sus propios clientes locales (sin este
header por defecto) para poder probar los casos de header ausente/
incorrecto/API_KEY sin configurar.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import auth, database  # noqa: E402

API_KEY_PRUEBA = "clave-secreta-de-prueba"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App con una base de datos SQLite temporal y una API_KEY de prueba
    activada; el header X-API-Key correcto se manda automaticamente en
    todas las requests de este cliente."""
    db_file = tmp_path / "test_contrataciones.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))
    monkeypatch.setattr(auth, "API_KEY", API_KEY_PRUEBA)

    from src.main import app

    with TestClient(app, headers={"X-API-Key": API_KEY_PRUEBA}) as test_client:
        yield test_client
