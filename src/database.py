"""Conexion a SQLite (sqlite3 estandar) e inicializacion de esquema."""
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "contrataciones.db")


def _normalizar_para_busqueda(texto: str | None) -> str:
    """Minusculas + sin acentos/diacriticos. SQLite (sin extensiones ICU)
    solo hace plegado de mayusculas/minusculas para el rango ASCII: `LIKE`
    y `UPPER`/`LOWER` nativos NO igualan 'ó' con 'o', asi que una busqueda
    de "repotenciacion" nunca encuentra "REPOTENCIACIÓN" sin este paso.
    Se registra como funcion SQL (ver `get_connection`) para poder seguir
    filtrando en SQL puro en vez de traer todas las filas y filtrar en
    Python."""
    if texto is None:
        return ""
    sin_acentos = unicodedata.normalize("NFKD", str(texto))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return sin_acentos.lower()


def get_connection() -> sqlite3.Connection:
    # timeout=10: si otra conexion (API, Streamlit, scripts de scraping/
    # importacion) tiene una escritura en curso, espera hasta 10s por el
    # lock en vez de fallar de inmediato con "database is locked".
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL permite que lecturas y escrituras concurrentes no se bloqueen
    # entre si (varias conexiones leyendo mientras otra escribe), a
    # diferencia del modo por defecto ("rollback journal").
    conn.execute("PRAGMA journal_mode = WAL")
    conn.create_function("normalizar", 1, _normalizar_para_busqueda)
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
                url TEXT,
                lote_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Migracion para bases de datos creadas antes de que existieran estas
        # columnas: CREATE TABLE IF NOT EXISTS no las agrega a tablas ya
        # existentes, asi que se agregan aparte si hace falta.
        columnas = _columnas_existentes(conn)
        if "palabra_clave" not in columnas:
            conn.execute("ALTER TABLE contrataciones ADD COLUMN palabra_clave TEXT")
        if "url" not in columnas:
            conn.execute("ALTER TABLE contrataciones ADD COLUMN url TEXT")
        if "lote_id" not in columnas:
            # Identifica todas las filas insertadas durante una misma
            # ejecucion de scrape_portal.py/import_csv.py (un "lote" o
            # busqueda), para poder reconstruir bloques de busqueda de forma
            # confiable (ver scripts/report_generator.py) en vez de adivinar
            # por saltos en el id.
            conn.execute("ALTER TABLE contrataciones ADD COLUMN lote_id TEXT")

        # estado, fecha_publicacion y palabra_clave son las columnas que
        # mas se usan para filtrar (dashboard, endpoint de reportes,
        # busqueda en la UI) y no tenian ningun indice.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_contrataciones_estado ON contrataciones(estado)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contrataciones_fecha_publicacion "
            "ON contrataciones(fecha_publicacion)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contrataciones_palabra_clave ON contrataciones(palabra_clave)"
        )
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
                 palabra_clave, url, lote_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                data.get("url"),
                data.get("lote_id"),
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
        # normalizar(): insensible a mayusculas/minusculas Y a tildes (ver
        # `_normalizar_para_busqueda`), no solo al rango ASCII que cubre el
        # LIKE nativo de SQLite.
        query += " AND normalizar(palabra_clave) LIKE normalizar(?)"
        params.append(f"%{palabra_clave}%")

    query += " ORDER BY id DESC"

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_contrataciones_para_reporte(
    palabras_clave: list[str],
    fecha_inicio: str,
    fecha_fin: str,
    lote_id: str | None = None,
) -> list[dict[str, Any]]:
    """Trae los procesos que coinciden con alguna de `palabras_clave`
    (comparacion por substring, insensible a mayusculas/minusculas Y A
    TILDES -- ver `_normalizar_para_busqueda` -- para tolerar variaciones
    del dato crudo del portal) dentro del rango `fecha_inicio`/`fecha_fin`,
    opcionalmente acotado a un `lote_id` (una ejecucion de scraping/
    importacion puntual). `fecha_inicio`/`fecha_fin` deben venir en
    formato ISO `YYYY-MM-DD` (asi los serializa `date.isoformat()` en
    `src/api_reportes.py`, y asi se guarda `fecha_publicacion` en la
    tabla -- ver `scripts/import_csv.py::parsear_fecha`); se envuelven
    igual en `date(...)` de SQLite para que la comparacion `BETWEEN` no
    dependa de que ambos lados traigan exactamente el mismo formato de
    texto (p.ej. si algun valor trajera una hora pegada).
    Pensada para alimentar `scripts/report_generator.py::generar_reporte`."""
    if not palabras_clave:
        return []

    condiciones_palabra = " OR ".join("normalizar(palabra_clave) LIKE normalizar(?)" for _ in palabras_clave)
    query = (
        f"SELECT * FROM contrataciones WHERE ({condiciones_palabra}) "
        "AND date(fecha_publicacion) BETWEEN date(?) AND date(?)"
    )
    params: list[Any] = [f"%{p}%" for p in palabras_clave]
    params.extend([fecha_inicio, fecha_fin])

    if lote_id:
        query += " AND lote_id = ?"
        params.append(lote_id)

    query += " ORDER BY id"

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
