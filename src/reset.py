"""Reset completo de todo lo derivado de una importación: la Zona de
peligro de Configuración (app_ui.py::render_vaciar_base_datos) llama a
`ejecutar_reset_completo` a través de `POST /api/reset-completo` (ver
src/main.py) en vez de solo `DELETE /api/todos`, que únicamente vaciaba
`contrataciones`.

`borradores_contratacion` (borradores de "Especificaciones Técnicas",
redactados a mano por el usuario) NUNCA se toca aquí a propósito: no es
un dato derivado de la importación de procesos, es contenido propio del
usuario -- ver CLAUDE.md.

Orden de operaciones, para nunca dejar la base de datos a medias:
1. Respaldo (no destructivo).
2. Borrar archivos generados (salidas/reportes/*.docx, salidas/capturas/*.png
   y, si se pidió, capturas/*.png) -- si alguno está bloqueado (p.ej. un
   .docx abierto en Word), se corta ACÁ con ArchivoBloqueadoError, antes
   de tocar la base de datos.
3. Recién al final, borrar `contrataciones` (database.delete_all_contrataciones,
   ya es un único DELETE + commit -- no hay tablas hijas que respetar, ver
   CLAUDE.md sobre el esquema real).
"""
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from src import database, respaldo_gcs
from src.respaldo_gcs import RespaldoRemotoError  # noqa: F401 -- re-exportado para src/main.py

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DIRECTORIO_CAPTURAS = RAIZ_PROYECTO / "capturas"
DIRECTORIO_SALIDAS_REPORTES = RAIZ_PROYECTO / "salidas" / "reportes"
DIRECTORIO_SALIDAS_CAPTURAS = RAIZ_PROYECTO / "salidas" / "capturas"


def _directorio_respaldos_por_defecto() -> Path:
    """En Cloud Run /app es de solo lectura para appuser: el respaldo local va a
    /tmp (efimero; por eso ademas se sube a Cloud Storage, ver
    src/respaldo_gcs.py). En local, respaldos/ junto al proyecto."""
    if respaldo_gcs.en_cloud_run():
        return Path(os.environ.get("RESPALDOS_DIR", "/tmp/respaldos"))
    return RAIZ_PROYECTO / "respaldos"


DIRECTORIO_RESPALDOS = _directorio_respaldos_por_defecto()


class ArchivoBloqueadoError(RuntimeError):
    """Un archivo generado por Reportes (normalmente un .docx en
    salidas/reportes/) esta abierto/bloqueado por otro programa (Word) y
    `Path.unlink()` lanzo PermissionError. La base de datos NO se toca
    cuando esto pasa -- ver el orden de operaciones en el docstring del
    modulo."""


def _respaldar(marca_tiempo: str) -> Path:
    """Copia data/contrataciones.db (via la API de backup de sqlite3, que
    a diferencia de un shutil.copy2 a secas SI refleja cambios todavia
    solo en el -wal -- ver PRAGMA journal_mode=WAL en database.get_connection)
    y cualquier .docx ya generado en salidas/reportes/, a
    respaldos/<marca_tiempo>/. No destructivo: corre SIEMPRE antes de
    borrar nada, incluso si un paso posterior aborta por archivo
    bloqueado."""
    destino = DIRECTORIO_RESPALDOS / marca_tiempo
    destino.mkdir(parents=True, exist_ok=True)

    if Path(database.DB_PATH).exists():
        origen = sqlite3.connect(database.DB_PATH)
        try:
            copia = sqlite3.connect(str(destino / "contrataciones.db"))
            try:
                origen.backup(copia)
            finally:
                copia.close()
        finally:
            origen.close()

    if DIRECTORIO_SALIDAS_REPORTES.exists():
        archivos_reportes = list(DIRECTORIO_SALIDAS_REPORTES.glob("*.docx"))
        if archivos_reportes:
            destino_reportes = destino / "reportes"
            destino_reportes.mkdir(parents=True, exist_ok=True)
            for archivo in archivos_reportes:
                shutil.copy2(archivo, destino_reportes / archivo.name)

    return destino


def _borrar_archivos(directorio: Path, patron: str) -> int:
    if not directorio.exists():
        return 0
    cantidad = 0
    for archivo in sorted(directorio.glob(patron)):
        if not archivo.is_file():
            continue
        try:
            archivo.unlink()
        except PermissionError as exc:
            raise ArchivoBloqueadoError(
                f"No se pudo borrar '{archivo.name}': el archivo está abierto en otro "
                "programa. Cierra Reporte_SERCOP.docx en Word y vuelve a intentar."
            ) from exc
        cantidad += 1
    return cantidad


def _ruta_para_mostrar(ruta: Path) -> str:
    """Ruta relativa a la raiz del proyecto (ej. "respaldos/20260101_120000");
    si cae fuera de ella, solo el nombre de la carpeta. Nunca la ruta absoluta."""
    try:
        return ruta.relative_to(RAIZ_PROYECTO).as_posix()
    except ValueError:
        return ruta.name


def ejecutar_reset_completo(borrar_capturas: bool = False) -> dict:
    marca_tiempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    respaldo_dir = _respaldar(marca_tiempo)

    # Cloud Run: el disco es efimero, asi que el respaldo se sube a Cloud
    # Storage ANTES de borrar nada. Si la subida falla (o el checksum no
    # coincide) se propaga RespaldoRemotoError y NO se toca ningun dato
    # (fail-closed). En local no aplica.
    respaldo_remoto = None
    if respaldo_gcs.en_cloud_run():
        respaldo_remoto = respaldo_gcs.subir_respaldo(respaldo_dir, marca_tiempo)

    # Archivos primero (pueden fallar por PermissionError si Word tiene un
    # .docx abierto): si algo falla aca, se propaga antes de tocar la BD.
    reportes_eliminados = _borrar_archivos(DIRECTORIO_SALIDAS_REPORTES, "*.docx")
    _borrar_archivos(DIRECTORIO_SALIDAS_CAPTURAS, "*.png")

    capturas_eliminadas = 0
    if borrar_capturas:
        capturas_eliminadas = _borrar_archivos(DIRECTORIO_CAPTURAS, "*.png")

    procesos_eliminados = database.delete_all_contrataciones()

    return {
        "procesos_eliminados": procesos_eliminados,
        "reportes_eliminados": reportes_eliminados,
        "capturas_eliminadas": capturas_eliminadas,
        # Ruta relativa a la raiz del proyecto: no se expone la ruta absoluta local.
        "respaldo_dir": _ruta_para_mostrar(respaldo_dir),
        # Prefijo del objeto en el bucket (sin nombre del bucket); None en local.
        "respaldo_remoto": respaldo_remoto,
    }
