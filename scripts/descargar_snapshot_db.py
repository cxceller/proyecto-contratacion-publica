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
import os
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


def main() -> None:
    if os.path.exists(DESTINO):
        print(f"{DESTINO} ya existe, no se vuelve a descargar.")
        return

    bucket = os.environ.get("SERCOP_DB_BUCKET")
    objeto = os.environ.get("SERCOP_DB_OBJECT", "contrataciones.db")
    if not bucket:
        sys.exit("SERCOP_DB_BUCKET no esta configurado; no se puede descargar el snapshot.")

    try:
        token = _obtener_token()
        objeto_codificado = urllib.parse.quote(objeto, safe="")
        url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{objeto_codificado}?alt=media"
        response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        sys.exit(f"No se pudo descargar el snapshot gs://{bucket}/{objeto}: {exc}")

    with open(DESTINO, "wb") as f:
        f.write(response.content)
    print(f"Snapshot descargado: gs://{bucket}/{objeto} -> {DESTINO}")


if __name__ == "__main__":
    main()
