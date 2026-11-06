"""Descarga del snapshot (scripts/descargar_snapshot_db.py): verifica el
checksum de GCS y aborta si no coincide; sin tocar red ni /tmp reales."""
import base64
import hashlib

import pytest

from scripts import descargar_snapshot_db as dsn


class _Resp:
    def __init__(self, contenido=b"", json_=None):
        self.content, self._json = contenido, json_ or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


def _md5(b):
    return base64.b64encode(hashlib.md5(b, usedforsecurity=False).digest()).decode()


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(dsn, "DESTINO", str(tmp_path / "sercop.db"))
    monkeypatch.setenv("SERCOP_DB_BUCKET", "mi-bucket")
    monkeypatch.setattr(dsn, "_obtener_token", lambda: "tok")
    return tmp_path


def _simular(monkeypatch, contenido, md5):
    def fake_get(url, **kw):
        return _Resp(contenido) if url.endswith("alt=media") else _Resp(json_={"md5Hash": md5})

    monkeypatch.setattr(dsn.requests, "get", fake_get)


def test_checksum_correcto_escribe_el_archivo(entorno, monkeypatch):
    datos = b"SQLite format 3\x00 contenido"
    _simular(monkeypatch, datos, _md5(datos))
    dsn.main()
    assert (entorno / "sercop.db").read_bytes() == datos
    assert not (entorno / "sercop.db.descarga").exists()


def test_checksum_distinto_aborta_y_no_deja_archivo(entorno, monkeypatch):
    _simular(monkeypatch, b"alterado", _md5(b"original"))
    with pytest.raises(SystemExit):
        dsn.main()
    assert not (entorno / "sercop.db").exists()


def test_sin_checksum_en_metadatos_aborta(entorno, monkeypatch):
    _simular(monkeypatch, b"x", None)
    with pytest.raises(SystemExit):
        dsn.main()


@pytest.mark.parametrize("bucket", ["../etc", "UPPER", "a/b", "x?alt=media", "a b"])
def test_bucket_con_formato_invalido_aborta(entorno, monkeypatch, bucket):
    monkeypatch.setenv("SERCOP_DB_BUCKET", bucket)
    with pytest.raises(SystemExit):
        dsn.main()
