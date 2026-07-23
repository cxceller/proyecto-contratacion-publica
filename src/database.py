"""Conexion a SQLite (sqlite3 estandar) e inicializacion de esquema."""
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "contrataciones.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columnas_existentes(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(contrataciones)").fetchall()}


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contrataciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL,
                entidad_contratante TEXT NOT NULL,
                objeto_proceso TEXT NOT NULL,
                estado TEXT NOT NULL,
                provincia_canton TEXT,
                presupuesto_referencial REAL,
                fecha_publicacion TEXT,
                palabra_clave TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Migracion para bases de datos creadas antes de que existiera esta
        # columna: CREATE TABLE IF NOT EXISTS no la agrega a tablas ya
        # existentes, asi que se agrega aparte si hace falta.
        if "palabra_clave" not in _columnas_existentes(conn):
            conn.execute("ALTER TABLE contrataciones ADD COLUMN palabra_clave TEXT")
        conn.commit()
    finally:
        conn.close()


def insert_contratacion(data: dict[str, Any]) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO contrataciones
                (codigo, entidad_contratante, objeto_proceso, estado,
                 provincia_canton, presupuesto_referencial, fecha_publicacion,
                 palabra_clave)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["codigo"],
                data["entidad_contratante"],
                data["objeto_proceso"],
                data["estado"],
                data.get("provincia_canton"),
                data.get("presupuesto_referencial"),
                data.get("fecha_publicacion"),
                data.get("palabra_clave"),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_all_contrataciones(
    status: str | None = None,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    palabra_clave: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM contrataciones WHERE 1=1"
    params: list[Any] = []

    if status:
        # Los valores de estado en el portal vienen truncados
        # (p.ej. "Adjudicado -", "Terminado U"), por lo que se
        # filtra por prefijo en lugar de igualdad exacta.
        query += " AND estado LIKE ?"
        params.append(f"{status}%")
    if fecha_inicio:
        query += " AND fecha_publicacion >= ?"
        params.append(fecha_inicio)
    if fecha_fin:
        query += " AND fecha_publicacion <= ?"
        params.append(fecha_fin)
    if palabra_clave:
        query += " AND palabra_clave LIKE ?"
        params.append(f"%{palabra_clave}%")

    query += " ORDER BY id DESC"

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_contratacion_by_id(contratacion_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM contrataciones WHERE id = ?", (contratacion_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_contratacion(contratacion_id: int, fields: dict[str, Any]) -> bool:
    if not fields:
        return get_contratacion_by_id(contratacion_id) is not None

    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [contratacion_id]

    conn = get_connection()
    try:
        cursor = conn.execute(
            f"UPDATE contrataciones SET {columns} WHERE id = ?", values
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_contratacion(contratacion_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM contrataciones WHERE id = ?", (contratacion_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_all_contrataciones() -> int:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM contrataciones")
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
