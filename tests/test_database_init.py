"""Tests de robustez de init_db (src/database.py) ante datos legados: un
`codigo` duplicado no debe tumbar el arranque de la API. init_db corre en
el lifespan de FastAPI (ver src/main.py); antes de este blindaje, un
CREATE UNIQUE INDEX sobre una base con codigo(s) repetidos lanzaba
sqlite3.IntegrityError sin capturar, y la API no levantaba."""
from src import database


def test_init_db_no_revienta_con_codigos_duplicados(tmp_path, monkeypatch, caplog):
    db_file = tmp_path / "legacy.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))

    database.init_db()  # crea esquema + indice unico, base vacia

    # Simula una base legada: el indice unico no existe (se dropea) y hay
    # dos filas con el mismo codigo -- exactamente el escenario que antes
    # tumbaba el CREATE UNIQUE INDEX de la segunda llamada a init_db.
    conn = database.get_connection()
    conn.execute("DROP INDEX IF EXISTS idx_contrataciones_codigo_unico")
    for _ in range(2):
        conn.execute(
            "INSERT INTO contrataciones (codigo, entidad_contratante, objeto_proceso, estado) "
            "VALUES ('DUP-001', 'Entidad', 'Objeto', 'Desierta')"
        )
    conn.commit()
    conn.close()

    with caplog.at_level("ERROR"):
        database.init_db()  # NO debe lanzar sqlite3.IntegrityError

    assert "DUP-001" in caplog.text
    registros = database.get_all_contrataciones()
    assert sum(1 for r in registros if r["codigo"] == "DUP-001") == 2


def test_init_db_crea_el_indice_unico_sin_duplicados(tmp_path, monkeypatch):
    """Caso normal (sin datos legados): el indice se crea sin problema y
    una segunda llamada a init_db (idempotente) tampoco falla."""
    db_file = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_file))

    database.init_db()
    database.init_db()

    conn = database.get_connection()
    indices = {row["name"] for row in conn.execute("PRAGMA index_list(contrataciones)").fetchall()}
    conn.close()
    assert "idx_contrataciones_codigo_unico" in indices
