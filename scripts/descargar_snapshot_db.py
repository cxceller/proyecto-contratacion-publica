"""Descarga el snapshot de la base de datos SQLite desde Cloud Storage a
/tmp/sercop.db al arrancar el contenedor en Cloud Run (invocado por
start.sh antes de levantar uvicorn) -- usa el token del service account
adjunto via el metadata server de GCP (equivalente a Application Default
Credentials dentro de Cloud Run), sin agregar la libreria
google-cloud-storage: evita ~14 dependencias nuevas y un bump mayor de
protobuf/requests que esa libreria arrastra (ver CLAUDE.md, seccion
Deployment).

No hace nada si /tmp/sercop.db ya existe (la instancia ya arranco antes y
conserva los cambios hechos en vivo; un cold start siempre repone el
snapshot). Sale con codigo distinto de 0 y un mensaje claro si algo falla
-- start.sh aborta el arranque del contenedor en ese caso, en vez de
seguir con una base vacia en silencio."""
import base64
import hashlib
import os
import re
import sys
import urllib.parse

import requests

DESTINO = "/tmp/sercop.db"
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/token"
)


def _obtener_token() -> str:
    response = requests.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=10)
    response.raise_for_status()
    return response.json()["access_token"]


PATRON_BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}$")


def _md5_base64(contenido: bytes) -> str:
    # MD5 solo como checksum de integridad: es el que publica GCS en
    # `md5Hash` del objeto (no se usa con fines de seguridad/autenticacion).
    return base64.b64encode(hashlib.md5(contenido, usedforsecurity=False).digest()).decode()


def main() -> None:
    if os.path.exists(DESTINO):
        print(f"{DESTINO} ya existe, no se vuelve a descargar.")
        return

    bucket = os.environ.get("SERCOP_DB_BUCKET")
    objeto = os.environ.get("SERCOP_DB_OBJECT", "contrataciones.db")
    if not bucket:
        sys.exit("SERCOP_DB_BUCKET no esta configurado; no se puede descargar el snapshot.")
    if not PATRON_BUCKET.match(bucket):
        sys.exit("SERCOP_DB_BUCKET tiene un formato invalido; no se descarga el snapshot.")

    try:
        token = _obtener_token()
        cabeceras = {"Authorization": f"Bearer {token}"}
        base = (
            "https://storage.googleapis.com/storage/v1/b/"
            f"{urllib.parse.quote(bucket, safe='')}/o/{urllib.parse.quote(objeto, safe='')}"
        )
        # Metadatos primero: traen el MD5 esperado del objeto.
        meta = requests.get(base, headers=cabeceras, timeout=30)
        meta.raise_for_status()
        md5_esperado = meta.json().get("md5Hash")
        response = requests.get(f"{base}?alt=media", headers=cabeceras, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        sys.exit(f"No se pudo descargar el snapshot gs://{bucket}/{objeto}: {type(exc).__name__}")

    # Integridad: si el contenido no coincide con el checksum publicado por
    # GCS (corrupto o alterado en transito), se aborta -- nunca se deja una BD
    # dudosa en su lugar.
    if not md5_esperado or _md5_base64(response.content) != md5_esperado:
        sys.exit("El snapshot descargado no coincide con el checksum de Cloud Storage; se aborta.")

    temporal = DESTINO + ".descarga"
    descriptor = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as f:
        f.write(response.content)
    os.replace(temporal, DESTINO)  # atomico: nunca queda una BD a medio escribir
    print(f"Snapshot descargado y verificado: gs://{bucket}/{objeto} -> {DESTINO}")


if __name__ == "__main__":
    main()
