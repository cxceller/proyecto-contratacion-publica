"""Restauracion de un respaldo creado por el reset completo (src/reset.py).

Cada reset deja `respaldos/<AAAAMMDD_HHMMSS>/` con `contrataciones.db` (copia
consistente via la API de backup de sqlite3, incluye lo que aun estaba solo en
el -wal) y, si existian, `reportes/*.docx`.

Restaurar REEMPLAZA el contenido de la base de datos actual por el del
respaldo (todas las tablas, borradores incluidos: los borradores creados
DESPUES del respaldo se pierden). Por eso, antes de tocar nada se guarda una
copia de seguridad de la base actual en `respaldos/pre_restauracion_<ts>/`.

Uso desde la terminal: scripts/restaurar_respaldo.py (sin --confirmar solo
muestra que haria, no modifica nada).
"""
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from src import database, reset, respaldo_gcs
from src.logging_config import obtener_logger

logger = obtener_logger(__name__)


class RespaldoInvalidoError(ValueError):
    """La carpeta de respaldo no existe, esta fuera de respaldos/ o su base de
    datos esta corrupta."""


def resolver_respaldo(nombre_o_ruta: str) -> Path:
    """Devuelve la carpeta de respaldo ya validada: debe estar DENTRO de
    respaldos/ (anti path traversal) y contener contrataciones.db."""
    base = reset.DIRECTORIO_RESPALDOS.resolve()
    candidato = Path(nombre_o_ruta)
    if not candidato.is_absolute():
        # acepta "20260101_120000" o "respaldos/20260101_120000"
        candidato = base / candidato.name if candidato.parent in (Path("."), Path("respaldos")) else candidato
    candidato = candidato.resolve()
    if candidato.parent != base:
        raise RespaldoInvalidoError("El respaldo debe ser una carpeta directamente dentro de respaldos/.")
    if not (candidato / "contrataciones.db").is_file():
        raise RespaldoInvalidoError("El respaldo no contiene contrataciones.db.")
    return candidato


# Nombres de tabla que _contar puede interpolar en el SQL (no admite parametros): lista blanca explicita.
TABLAS_CONTABLES = frozenset({"contrataciones", "borradores_contratacion"})


def _contar(ruta_db: Path, tabla: str) -> int:
    if tabla not in TABLAS_CONTABLES:
        raise ValueError(f"Tabla no permitida: {tabla!r}")
    conn = sqlite3.connect(f"file:{ruta_db.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]  # noqa: S608 -- validada contra TABLAS_CONTABLES
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def verificar_integridad(ruta_db: Path) -> None:
    conn = sqlite3.connect(f"file:{ruta_db.as_posix()}?mode=ro", uri=True)
    try:
        resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise RespaldoInvalidoError("La base de datos del respaldo no se puede leer.") from exc
    finally:
        conn.close()
    if resultado != "ok":
        raise RespaldoInvalidoError("La base de datos del respaldo no pasa PRAGMA integrity_check.")


def restaurar(
    nombre_o_ruta: str,
    confirmar: bool = False,
    sobrescribir_reportes: bool = False,
    origen: str = "local",
    cliente=None,
) -> dict:
    """Restaura `nombre_o_ruta`. Con confirmar=False solo describe el plan.

    `origen="gcs"`: primero BAJA el respaldo del bucket (verificando checksums)
    a una carpeta de trabajo dentro de respaldos/ y restaura desde ahi; `cliente`
    es el cliente de Cloud Storage (inyectable en pruebas)."""
    if origen not in ("local", "gcs"):
        raise RespaldoInvalidoError("origen debe ser 'local' o 'gcs'.")
    if origen == "gcs":
        nombre = Path(nombre_o_ruta).name
        marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        descargado = respaldo_gcs.descargar_respaldo(
            nombre, reset.DIRECTORIO_RESPALDOS / f"gcs_{nombre}_{marca}", cliente=cliente
        )
        nombre_o_ruta = descargado.name
    carpeta = resolver_respaldo(nombre_o_ruta)
    db_respaldo = carpeta / "contrataciones.db"
    verificar_integridad(db_respaldo)

    reportes = sorted((carpeta / "reportes").glob("*.docx")) if (carpeta / "reportes").is_dir() else []
    plan = {
        "origen": origen,
        "respaldo": carpeta.name,
        "contrataciones_en_respaldo": _contar(db_respaldo, "contrataciones"),
        "borradores_en_respaldo": _contar(db_respaldo, "borradores_contratacion"),
        "reportes_en_respaldo": len(reportes),
        "aplicado": False,
    }
    if not confirmar:
        return plan

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    seguridad = None
    db_actual = Path(database.DB_PATH)
    if db_actual.exists():
        seguridad = reset.DIRECTORIO_RESPALDOS / f"pre_restauracion_{marca}"
        seguridad.mkdir(parents=True, exist_ok=True)
        origen = sqlite3.connect(str(db_actual))
        try:
            copia = sqlite3.connect(str(seguridad / "contrataciones.db"))
            try:
                origen.backup(copia)
            finally:
                copia.close()
        finally:
            origen.close()

    # El respaldo es la ORIGEN y la base viva el DESTINO: la API de backup
    # copia pagina por pagina y deja la base viva consistente (WAL incluido).
    fuente = sqlite3.connect(f"file:{db_respaldo.as_posix()}?mode=ro", uri=True)
    try:
        destino = sqlite3.connect(str(db_actual), timeout=10)
        try:
            fuente.backup(destino)
        finally:
            destino.close()
    finally:
        fuente.close()

    reportes_restaurados = 0
    if reportes:
        reset.DIRECTORIO_SALIDAS_REPORTES.mkdir(parents=True, exist_ok=True)
        for archivo in reportes:
            destino_reporte = reset.DIRECTORIO_SALIDAS_REPORTES / archivo.name
            if destino_reporte.exists() and not sobrescribir_reportes:
                continue
            shutil.copy2(archivo, destino_reporte)
            reportes_restaurados += 1

    plan.update(
        aplicado=True,
        copia_de_seguridad_previa=seguridad.name if seguridad else None,
        reportes_restaurados=reportes_restaurados,
    )
    logger.info(
        "AUDITORIA accion=restaurar_respaldo usuario=cli resultado=ok respaldo=%s contrataciones=%s",
        carpeta.name,
        plan["contrataciones_en_respaldo"],
    )
    return plan
