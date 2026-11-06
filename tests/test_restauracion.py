"""Restauracion de respaldos del reset: ciclo reset -> restaurar con los datos
identicos, copia previa de seguridad, y rechazo de rutas peligrosas."""
import hashlib
import sqlite3
from pathlib import Path

import pytest

from src import database, reset
from src.restauracion import RespaldoInvalidoError, restaurar


def _huella_tabla(ruta_db, tabla):
    conn = sqlite3.connect(str(ruta_db))
    try:
        filas = conn.execute(f"SELECT * FROM {tabla} ORDER BY id").fetchall()
    finally:
        conn.close()
    return len(filas), hashlib.sha256(repr(filas).encode()).hexdigest()


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "vivo.db"))
    monkeypatch.setattr(reset, "DIRECTORIO_CAPTURAS", tmp_path / "capturas")
    monkeypatch.setattr(reset, "DIRECTORIO_SALIDAS_REPORTES", tmp_path / "salidas" / "reportes")
    monkeypatch.setattr(reset, "DIRECTORIO_SALIDAS_CAPTURAS", tmp_path / "salidas" / "capturas")
    monkeypatch.setattr(reset, "DIRECTORIO_RESPALDOS", tmp_path / "respaldos")
    monkeypatch.setattr(reset, "RAIZ_PROYECTO", tmp_path)
    database.init_db()
    for i in range(4):
        database.insert_contratacion(
            {"codigo": f"R-{i}", "entidad_contratante": "E", "objeto_proceso": "o", "estado": "Desierta",
             "provincia_canton": None, "presupuesto_referencial": 1.0 * i, "fecha_publicacion": "2025-01-01",
             "palabra_clave": "k", "url": None, "lote_id": None, "monto_adjudicado": None,
             "motivo_estado_raw": None, "explicacion_estado": None})
    database.insert_borrador("borrador previo", "{}")
    (tmp_path / "salidas" / "reportes").mkdir(parents=True)
    (tmp_path / "salidas" / "reportes" / "r1.docx").write_bytes(b"docx-uno")
    return tmp_path


def test_ciclo_reset_y_restauracion_deja_los_datos_identicos(entorno):
    antes_c = _huella_tabla(database.DB_PATH, "contrataciones")
    antes_b = _huella_tabla(database.DB_PATH, "borradores_contratacion")
    hash_docx = hashlib.sha256(b"docx-uno").hexdigest()

    resumen = reset.ejecutar_reset_completo()
    assert resumen["procesos_eliminados"] == 4 and not (entorno / "salidas" / "reportes" / "r1.docx").exists()
    assert _huella_tabla(database.DB_PATH, "contrataciones")[0] == 0

    plan = restaurar(Path(resumen["respaldo_dir"]).name, confirmar=True)
    assert plan["aplicado"] and plan["contrataciones_en_respaldo"] == 4 and plan["reportes_restaurados"] == 1
    assert _huella_tabla(database.DB_PATH, "contrataciones") == antes_c
    assert _huella_tabla(database.DB_PATH, "borradores_contratacion") == antes_b
    restaurado = (entorno / "salidas" / "reportes" / "r1.docx").read_bytes()
    assert hashlib.sha256(restaurado).hexdigest() == hash_docx


def test_sin_confirmar_no_modifica_nada(entorno):
    resumen = reset.ejecutar_reset_completo()
    plan = restaurar(Path(resumen["respaldo_dir"]).name)
    assert not plan["aplicado"]
    assert _huella_tabla(database.DB_PATH, "contrataciones")[0] == 0
    assert not list((entorno / "respaldos").glob("pre_restauracion_*"))


def test_guarda_copia_de_seguridad_de_la_bd_actual(entorno):
    resumen = reset.ejecutar_reset_completo()
    database.insert_contratacion(
        {"codigo": "NUEVO", "entidad_contratante": "E", "objeto_proceso": "o", "estado": "x",
         "provincia_canton": None, "presupuesto_referencial": 1.0, "fecha_publicacion": "2025-02-02",
         "palabra_clave": "k", "url": None, "lote_id": None, "monto_adjudicado": None,
         "motivo_estado_raw": None, "explicacion_estado": None})
    plan = restaurar(Path(resumen["respaldo_dir"]).name, confirmar=True)
    previa = entorno / "respaldos" / plan["copia_de_seguridad_previa"] / "contrataciones.db"
    assert _huella_tabla(previa, "contrataciones")[0] == 1  # lo que habia ANTES de restaurar


def test_no_pisa_reportes_existentes_salvo_que_se_pida(entorno):
    resumen = reset.ejecutar_reset_completo()
    (entorno / "salidas" / "reportes").mkdir(parents=True, exist_ok=True)
    (entorno / "salidas" / "reportes" / "r1.docx").write_bytes(b"version-nueva")
    restaurar(Path(resumen["respaldo_dir"]).name, confirmar=True)
    assert (entorno / "salidas" / "reportes" / "r1.docx").read_bytes() == b"version-nueva"
    restaurar(Path(resumen["respaldo_dir"]).name, confirmar=True, sobrescribir_reportes=True)
    assert (entorno / "salidas" / "reportes" / "r1.docx").read_bytes() == b"docx-uno"


@pytest.mark.parametrize("malo", ["../fuera", "..", "/etc", "C:/Windows", "no_existe", ""])
def test_rutas_peligrosas_o_inexistentes_se_rechazan(entorno, malo):
    with pytest.raises(RespaldoInvalidoError):
        restaurar(malo, confirmar=True)


def test_respaldo_corrupto_se_rechaza_y_no_toca_la_bd(entorno):
    carpeta = entorno / "respaldos" / "20250101_000000"
    carpeta.mkdir(parents=True)
    (carpeta / "contrataciones.db").write_bytes(b"esto no es sqlite" * 100)
    with pytest.raises(RespaldoInvalidoError):
        restaurar("20250101_000000", confirmar=True)
    assert _huella_tabla(database.DB_PATH, "contrataciones")[0] == 4
