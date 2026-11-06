"""Respaldos del reset completo en Cloud Storage (solo Cloud Run).

En Cloud Run el sistema de archivos del contenedor es efimero: un respaldo
guardado solo en disco se pierde al reciclarse la instancia. Por eso, cuando
corre ahi (variable K_SERVICE), `src/reset.py` SUBE el respaldo al mismo bucket
de respaldos (SERCOP_BACKUP_BUCKET; si no esta definida, por compatibilidad se usa
SERCOP_DB_BUCKET, el del snapshot) bajo `respaldos/<AAAAMMDD_HHMMSS>/...` ANTES de
borrar nada, y aborta si la subida falla o su checksum no coincide
(fail-closed). En local no se usa.

Sin la libreria google-cloud-storage (ver CLAUDE.md, seccion Deployment): solo
`requests` contra la API JSON de GCS, con el token de la cuenta de servicio del
metadata server (o `GCS_ACCESS_TOKEN`, util para restaurar desde un equipo
local: `gcloud auth print-access-token`).

Permisos que necesita la cuenta de servicio sobre el bucket: crear, leer y
listar objetos (por ejemplo roles/storage.objectAdmin, o objectCreator +
objectViewer).

`ClienteGCS` es la unica clase que habla HTTP; las pruebas la reemplazan por un
cliente en memoria con la misma interfaz (subir / listar_respaldos / listar /
descargar)."""
import base64
import hashlib
import os
import re
import urllib.parse
from pathlib import Path

import requests

from src.logging_config import obtener_logger

logger = obtener_logger(__name__)

PREFIJO_POR_DEFECTO = "respaldos/"
PATRON_BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}$")
PATRON_PREFIJO = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
PATRON_NOMBRE_RESPALDO = re.compile(r"^\d{8}_\d{6}$")
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
API = "https://storage.googleapis.com"
TIMEOUT_S = 120


class RespaldoRemotoError(RuntimeError):
    """No se pudo subir/leer el respaldo en Cloud Storage. Mensaje generico y
    seguro de mostrar; el detalle va al log."""


def en_cloud_run() -> bool:
    return bool(os.environ.get("K_SERVICE"))


def _md5_base64(contenido: bytes) -> str:
    # MD5 solo como checksum de integridad (es el que publica GCS en `md5Hash`).
    return base64.b64encode(hashlib.md5(contenido, usedforsecurity=False).digest()).decode()


def _obtener_token() -> str:
    token = os.environ.get("GCS_ACCESS_TOKEN")
    if token:
        return token
    respuesta = requests.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=10)
    respuesta.raise_for_status()
    return respuesta.json()["access_token"]


def _prefijo() -> str:
    prefijo = os.environ.get("SERCOP_RESPALDOS_PREFIX", PREFIJO_POR_DEFECTO).strip()
    if not PATRON_PREFIJO.match(prefijo) or ".." in prefijo or prefijo.startswith("/"):
        raise RespaldoRemotoError("SERCOP_RESPALDOS_PREFIX tiene un formato invalido.")
    return prefijo if prefijo.endswith("/") else prefijo + "/"


class ClienteGCS:
    """Cliente minimo de la API JSON de Cloud Storage para un bucket."""

    def __init__(self, bucket: str, prefijo: str = PREFIJO_POR_DEFECTO) -> None:
        if not PATRON_BUCKET.match(bucket or ""):
            raise RespaldoRemotoError(
                "El bucket de respaldos (SERCOP_BACKUP_BUCKET) no esta configurado o tiene un formato invalido."
            )
        self.bucket = bucket
        self.prefijo = prefijo
        self._token: str | None = None

    def _cabeceras(self) -> dict:
        if self._token is None:
            self._token = _obtener_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _objeto(self, nombre: str) -> str:
        return urllib.parse.quote(nombre, safe="")

    def subir(self, nombre: str, contenido: bytes) -> str:
        """Sube `contenido` como `nombre` y devuelve el md5 (base64) que GCS
        calculo del objeto recibido."""
        url = f"{API}/upload/storage/v1/b/{urllib.parse.quote(self.bucket, safe='')}/o"
        respuesta = requests.post(
            url,
            params={"uploadType": "media", "name": nombre},
            data=contenido,
            headers={**self._cabeceras(), "Content-Type": "application/octet-stream"},
            timeout=TIMEOUT_S,
        )
        respuesta.raise_for_status()
        return respuesta.json().get("md5Hash", "")

    def listar(self, prefijo: str, delimitador: str | None = None) -> dict:
        """Lista objetos bajo `prefijo` (todas las paginas). Devuelve
        {"items": [{name, md5Hash, size}], "prefixes": [..]}."""
        items: list[dict] = []
        prefijos: list[str] = []
        token_pagina = None
        while True:
            params = {"prefix": prefijo}
            if delimitador:
                params["delimiter"] = delimitador
            if token_pagina:
                params["pageToken"] = token_pagina
            respuesta = requests.get(
                f"{API}/storage/v1/b/{urllib.parse.quote(self.bucket, safe='')}/o",
                params=params,
                headers=self._cabeceras(),
                timeout=60,
            )
            respuesta.raise_for_status()
            cuerpo = respuesta.json()
            items.extend(cuerpo.get("items", []))
            prefijos.extend(cuerpo.get("prefixes", []))
            token_pagina = cuerpo.get("nextPageToken")
            if not token_pagina:
                return {"items": items, "prefixes": prefijos}

    def listar_respaldos(self) -> list[str]:
        """Nombres (AAAAMMDD_HHMMSS) de los respaldos que hay en el bucket."""
        prefijos = self.listar(self.prefijo, delimitador="/")["prefixes"]
        nombres = [p[len(self.prefijo):].strip("/") for p in prefijos]
        return sorted(n for n in nombres if PATRON_NOMBRE_RESPALDO.match(n))

    def descargar(self, nombre: str) -> bytes:
        respuesta = requests.get(
            f"{API}/storage/v1/b/{urllib.parse.quote(self.bucket, safe='')}/o/{self._objeto(nombre)}",
            params={"alt": "media"},
            headers=self._cabeceras(),
            timeout=TIMEOUT_S,
        )
        respuesta.raise_for_status()
        return respuesta.content


def bucket_de_respaldos() -> str:
    """Bucket donde se guardan los respaldos: SERCOP_BACKUP_BUCKET (recomendado: un bucket SEPARADO del
    snapshot, con retencion) y, si no esta definida o esta vacia, SERCOP_DB_BUCKET por compatibilidad."""
    return (os.environ.get("SERCOP_BACKUP_BUCKET") or "").strip() or (os.environ.get("SERCOP_DB_BUCKET") or "").strip()


def crear_cliente() -> ClienteGCS:
    return ClienteGCS(bucket_de_respaldos(), _prefijo())


def subir_respaldo(carpeta: Path, nombre: str, cliente=None) -> str:
    """Sube TODO el contenido de `carpeta` a `<prefijo><nombre>/` y verifica el
    checksum de cada objeto. Devuelve el prefijo remoto. Cualquier fallo se
    convierte en RespaldoRemotoError (el reset debe abortar antes de borrar)."""
    if not PATRON_NOMBRE_RESPALDO.match(nombre):
        raise RespaldoRemotoError("Nombre de respaldo invalido.")
    try:
        cliente = cliente or crear_cliente()
        archivos = sorted(p for p in carpeta.rglob("*") if p.is_file())
        if not any(p.name == "contrataciones.db" for p in archivos):
            raise RespaldoRemotoError("El respaldo local no contiene contrataciones.db.")
        for archivo in archivos:
            contenido = archivo.read_bytes()
            remoto = f"{cliente.prefijo}{nombre}/{archivo.relative_to(carpeta).as_posix()}"
            md5_remoto = cliente.subir(remoto, contenido)
            if md5_remoto != _md5_base64(contenido):
                raise RespaldoRemotoError("El checksum del objeto subido no coincide.")
    except RespaldoRemotoError:
        raise
    except (requests.RequestException, OSError, KeyError, ValueError) as exc:
        logger.error("Fallo la subida del respaldo a Cloud Storage: %s", type(exc).__name__)
        raise RespaldoRemotoError("No se pudo subir el respaldo a Cloud Storage.") from exc
    logger.info("Respaldo %s subido a Cloud Storage (%s archivo(s))", nombre, len(archivos))
    return f"{cliente.prefijo}{nombre}"


def listar_respaldos(cliente=None) -> list[str]:
    try:
        return (cliente or crear_cliente()).listar_respaldos()
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.error("Fallo el listado de respaldos en Cloud Storage: %s", type(exc).__name__)
        raise RespaldoRemotoError("No se pudo listar los respaldos en Cloud Storage.") from exc


def descargar_respaldo(nombre: str, destino: Path, cliente=None) -> Path:
    """Baja `<prefijo><nombre>/*` a la carpeta local `destino` (verificando el
    checksum publicado por GCS) y la devuelve."""
    if not PATRON_NOMBRE_RESPALDO.match(nombre):
        raise RespaldoRemotoError("Nombre de respaldo invalido.")
    try:
        cliente = cliente or crear_cliente()
        prefijo = f"{cliente.prefijo}{nombre}/"
        objetos = cliente.listar(prefijo)["items"]
        if not objetos:
            raise RespaldoRemotoError("No existe ese respaldo en Cloud Storage.")
        destino.mkdir(parents=True, exist_ok=True)
        base = destino.resolve()
        for objeto in objetos:
            relativo = objeto["name"][len(prefijo):]
            ruta = (destino / relativo).resolve()
            if not relativo or base not in ruta.parents:  # anti path traversal
                raise RespaldoRemotoError("El respaldo remoto contiene una ruta invalida.")
            contenido = cliente.descargar(objeto["name"])
            if objeto.get("md5Hash") and objeto["md5Hash"] != _md5_base64(contenido):
                raise RespaldoRemotoError("El checksum del objeto descargado no coincide.")
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(contenido)
    except RespaldoRemotoError:
        raise
    except (requests.RequestException, OSError, KeyError, ValueError) as exc:
        logger.error("Fallo la descarga del respaldo desde Cloud Storage: %s", type(exc).__name__)
        raise RespaldoRemotoError("No se pudo descargar el respaldo desde Cloud Storage.") from exc
    return destino
