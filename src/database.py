"""Conexion a SQLite (sqlite3 estandar) e inicializacion de esquema."""
import logging
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
                monto_adjudicado REAL,
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
        if "monto_adjudicado" not in columnas:
            # "Monto de Adjudicación ($)" real, leido de la seccion
            # "Informacion de Adjudicacion" de la pagina de detalle de cada
            # proceso (campo `url`) durante el scraping -- NO viene en la
            # tabla de resultados de busqueda, por eso se completa aparte
            # (ver scripts/scrape_portal.py::_obtener_montos_adjudicados),
            # a diferencia de presupuesto_referencial que si viene ahi.
            conn.execute("ALTER TABLE contrataciones ADD COLUMN monto_adjudicado REAL")
        if "motivo_estado_raw" not in columnas:
            # Texto completo de la celda "Estado del Proceso" de la pagina
            # general de detalle (Razon, Fecha y Justificacion -- para
            # estados como Desierta/Cancelado/Suspendido trae mucho mas que
            # la sola etiqueta del estado). Se captura para TODOS los
            # procesos donde la pagina de detalle ya se visita (gratis, sin
            # peticion extra -- ver scripts/scrape_portal.py::_extraer_motivo_estado),
            # no solo Desierta: sirve de base para explicacion_estado (ver
            # abajo) y para otros estados en el futuro.
            conn.execute("ALTER TABLE contrataciones ADD COLUMN motivo_estado_raw TEXT")
        if "explicacion_estado" not in columnas:
            # Explicacion en lenguaje simple de motivo_estado_raw, generada
            # por un LLM (ver scripts/explicar_estado_desierta.py) -- hoy
            # solo se completa para procesos "Desierta". NULL hasta que el
            # script de enriquecimiento la complete; distingue "todavia no
            # se genero" (NULL) de "se genero y esta vacia" (no deberia
            # pasar, pero NULL es la señal correcta de pendiente en
            # cualquier caso).
            conn.execute("ALTER TABLE contrataciones ADD COLUMN explicacion_estado TEXT")

        # Un mismo `codigo` de proceso reaparece en cada busqueda que se
        # solape con una anterior (el portal solo permite buscar 6 meses
        # atras / 15 dias adelante desde la fecha de publicacion, asi que
        # los procesos "vivos" reaparecen en cada corrida nueva de
        # scrape_portal.py/import_csv.py). Sin esta restriccion, cada
        # corrida insertaba una fila nueva en vez de actualizar la
        # existente -- ver upsert_contratacion, que es quien realmente
        # depende de este indice para el ON CONFLICT(codigo). En una base
        # con datos previos a este cambio, esto puede fallar si todavia
        # quedan `codigo` duplicados sin limpiar (hay que deduplicar antes
        # de que esto se ejecute; no se hace aca automaticamente para no
        # borrar filas de produccion sin que alguien lo revise primero).
        #
        # Blindado en try/except: si una BD legada TODAVIA tiene `codigo`
        # duplicados, este CREATE lanza sqlite3.IntegrityError -- sin este
        # try/except, como init_db corre en el lifespan de FastAPI, eso
        # tumba el arranque completo de la API con un traceback opaco en
        # vez de dejar el problema (dedupe manual pendiente) documentado
        # en el log y seguir sirviendo el resto de la app.
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_contrataciones_codigo_unico ON contrataciones(codigo)"
            )
        except sqlite3.IntegrityError:
            duplicados = conn.execute(
                "SELECT codigo, COUNT(*) AS cantidad FROM contrataciones GROUP BY codigo HAVING cantidad > 1"
            ).fetchall()
            logger.error(
                "No se pudo crear idx_contrataciones_codigo_unico: hay codigo(s) duplicado(s) "
                "en la base (%s). Dedupliquelos manualmente; hasta entonces, upsert_contratacion "
                "(que depende de este indice para su ON CONFLICT) puede insertar filas repetidas "
                "en vez de actualizar la existente.",
                [row["codigo"] for row in duplicados],
            )

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

        # Borradores de Especificaciones Técnicas ("Formularios y Registro" en app_ui.py):
        # antes esos formularios solo vivian en st.session_state y se
        # perdian al cerrar el navegador/reiniciar Streamlit. datos_json
        # guarda TODO el estado persistente del formulario (campos
        # simples, items, especificaciones tecnicas, etc.) ya serializado
        # a JSON puro por app_ui.py -- esta tabla no interpreta ese
        # contenido, solo lo guarda y lo devuelve tal cual.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS borradores_contratacion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_contratacion TEXT NOT NULL,
                datos_json TEXT NOT NULL,
                fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_borradores_fecha_actualizacion "
            "ON borradores_contratacion(fecha_actualizacion)"
        )
        conn.commit()
    finally:
        conn.close()


def insert_contratacion(data: dict[str, Any]) -> int:
    """INSERT simple, sin resolver conflictos de `codigo` -- para la
    creacion manual via API (POST /api/todos, ver src/main.py), donde un
    `codigo` repetido es un error del usuario que se le debe reportar (409),
    no algo que se deba fusionar en silencio con una fila existente. Para
    la importacion masiva desde el portal (scrape_portal.py/import_csv.py,
    donde SI es normal y esperado volver a encontrar el mismo `codigo` en
    corridas que se solapan) usar upsert_contratacion en su lugar."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO contrataciones
                (codigo, entidad_contratante, objeto_proceso, estado,
                 provincia_canton, presupuesto_referencial, fecha_publicacion,
                 palabra_clave, url, lote_id, monto_adjudicado, motivo_estado_raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                data.get("monto_adjudicado"),
                data.get("motivo_estado_raw"),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def upsert_contratacion(data: dict[str, Any], conn: sqlite3.Connection | None = None) -> int:
    """INSERT o, si ya existe una fila con el mismo `codigo`
    (idx_contrataciones_codigo_unico, ver init_db), UPDATE de esa fila en
    vez de insertar una copia nueva. Usado por importar_dataframe (scripts/
    import_csv.py), compartido por scrape_portal.py y la importacion
    manual de CSV/Excel: es normal volver a encontrar el mismo `codigo` en
    corridas que se solapan (el portal solo permite buscar 6 meses atras /
    15 dias adelante desde la fecha de publicacion), y un proceso real
    cambia de estado con el tiempo (p.ej. de "Entrega de Propuesta" a
    "Adjudicado"), asi que lo correcto es reflejar ese cambio en la misma
    fila, no acumular copias.

    `codigo`, `fecha_publicacion` y `created_at` NO se tocan en el UPDATE:
    son datos que no deberian cambiar entre corridas para el mismo proceso.
    `monto_adjudicado` y `motivo_estado_raw` usan COALESCE(nuevo, existente)
    para no borrar un valor ya conocido si una corrida posterior no llega a
    visitar la pagina de detalle (p.ej. corrida con --sin-monto-adjudicado,
    ver scripts/scrape_portal.py, que se salta esa pagina por completo) --
    el resto de los campos si se pisan con el valor nuevo, porque reflejan
    el estado mas reciente del proceso. `explicacion_estado` NO se toca
    aca a proposito -- no es parte de lo que trae el scraper, la completa
    aparte scripts/explicar_estado_desierta.py via update_contratacion, y
    un re-scrape no deberia borrarla.

    `conn` (opcional): reutiliza una conexion ya abierta en vez de abrir y
    cerrar una nueva -- pensado para scripts/import_csv.py::importar_dataframe,
    que en otro caso pagaba una conexion (connect + PRAGMAs + close) POR
    FILA del lote a importar (cientos por corrida). Sin `conn`, se comporta
    exactamente igual que antes (abre y cierra su propia conexion), asi que
    los demas callers (API, tests) no cambian.
    Devuelve el `id` de la fila (nueva o la ya existente que se actualizo)."""
    conn_propia = conn is None
    if conn is None:
        conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO contrataciones
                (codigo, entidad_contratante, objeto_proceso, estado,
                 provincia_canton, presupuesto_referencial, fecha_publicacion,
                 palabra_clave, url, lote_id, monto_adjudicado, motivo_estado_raw)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(codigo) DO UPDATE SET
                entidad_contratante = excluded.entidad_contratante,
                objeto_proceso = excluded.objeto_proceso,
                estado = excluded.estado,
                provincia_canton = excluded.provincia_canton,
                presupuesto_referencial = excluded.presupuesto_referencial,
                palabra_clave = excluded.palabra_clave,
                url = excluded.url,
                lote_id = excluded.lote_id,
                monto_adjudicado = COALESCE(excluded.monto_adjudicado, monto_adjudicado),
                motivo_estado_raw = COALESCE(excluded.motivo_estado_raw, motivo_estado_raw)
            RETURNING id
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
                data.get("monto_adjudicado"),
                data.get("motivo_estado_raw"),
            ),
        )
        contratacion_id = cursor.fetchone()["id"]
        conn.commit()
        return contratacion_id
    finally:
        if conn_propia:
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


def insert_borrador(nombre_contratacion: str, datos_json: str) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO borradores_contratacion (nombre_contratacion, datos_json, fecha_actualizacion)
            VALUES (?, ?, datetime('now'))
            """,
            (nombre_contratacion, datos_json),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_borrador(borrador_id: int, nombre_contratacion: str, datos_json: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE borradores_contratacion
            SET nombre_contratacion = ?, datos_json = ?, fecha_actualizacion = datetime('now')
            WHERE id = ?
            """,
            (nombre_contratacion, datos_json, borrador_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_all_borradores() -> list[dict[str, Any]]:
    """Solo id/nombre/fecha (sin datos_json): alcanza para listar el
    selectbox de borradores guardados sin traer el JSON completo de cada
    uno en cada rerun de Streamlit."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, nombre_contratacion, fecha_actualizacion FROM borradores_contratacion "
            "ORDER BY fecha_actualizacion DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_borrador_by_id(borrador_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM borradores_contratacion WHERE id = ?", (borrador_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_borrador(borrador_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM borradores_contratacion WHERE id = ?", (borrador_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
