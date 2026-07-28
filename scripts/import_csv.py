"""Importa procesos de contratacion desde un CSV/Excel exportado manualmente
del portal de Compras Publicas (SERCOP) hacia la base de datos SQLite local.

El portal (https://www.compraspublicas.gob.ec/...) exige resolver un CAPTCHA
para buscar procesos, por lo que la carga de datos reales no se automatiza:
el usuario realiza la busqueda en el portal, exporta el resultado (CSV/Excel)
y este script lo transforma al esquema de la tabla `contrataciones`.

Uso:
    .venv/Scripts/python.exe scripts/import_csv.py ruta/al/archivo.csv
    .venv/Scripts/python.exe scripts/import_csv.py ruta/al/archivo.xlsx
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import database  # noqa: E402
from src.models import ContratacionCreate  # noqa: E402

# Encabezados esperados del portal -> nombre de campo interno.
# Las claves ya estan normalizadas (sin acentos, minusculas, solo alfanumericos).
COLUMN_MAP = {
    "codigo": "codigo",
    "entidadcontratante": "entidad_contratante",
    "objetodelproceso": "objeto_proceso",
    "objeto": "objeto_proceso",
    "estadodelproceso": "estado",
    "estado": "estado",
    "provinciacanton": "provincia_canton",
    "provincia": "provincia_canton",
    "presupuestoreferencialtotalsiniva": "presupuesto_referencial",
    "presupuestoreferencial": "presupuesto_referencial",
    "fechadepublicacion": "fecha_publicacion",
    "fechapublicacion": "fecha_publicacion",
}


def normalizar_encabezado(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(texto))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", sin_acentos.lower())


def parsear_presupuesto(valor) -> float | None:
    """Convierte un valor de presupuesto (con simbolo de moneda, separador
    de miles y/o decimales en formato latino o anglosajon, espacios extra,
    etc.) a float. Cuando aparecen coma y punto a la vez, se asume que el
    ultimo de los dos (el mas a la derecha) es el separador decimal (asi
    se reconocen tanto "15,000.50" como "15.000,50"). Cuando solo aparece
    uno de los dos y tiene exactamente 3 digitos despues (o se repite mas
    de una vez), se asume que es un separador de miles sin parte decimal
    (p.ej. "250.000" o "1.234.567"), porque los montos de este portal no
    manejan mas de 2 decimales."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip()
    if texto == "" or texto.lower() == "nan":
        return None
    texto = re.sub(r"[^0-9,.\-]", "", texto)
    if texto in ("", "-"):
        return None

    tiene_coma = "," in texto
    tiene_punto = "." in texto

    if tiene_coma and tiene_punto:
        separador_decimal = "," if texto.rfind(",") > texto.rfind(".") else "."
        separador_miles = "." if separador_decimal == "," else ","
        texto = texto.replace(separador_miles, "").replace(separador_decimal, ".")
    elif tiene_coma or tiene_punto:
        separador = "," if tiene_coma else "."
        digitos_despues = len(texto) - texto.rfind(separador) - 1
        if texto.count(separador) > 1 or digitos_despues == 3:
            texto = texto.replace(separador, "")
        else:
            texto = texto.replace(separador, ".")

    try:
        return float(texto)
    except ValueError:
        return None


def parsear_fecha(valor) -> str | None:
    """Convierte un valor de fecha a ISO (YYYY-MM-DD). Las fechas que ya
    vienen en formato ISO (YYYY-MM-DD..., como las que trae la tabla de
    resultados del portal, p.ej. "2025-03-11 11:00:00") se parsean sin
    `dayfirst`: con `dayfirst=True` pandas interpreta mal ese formato y
    puede intercambiar mes y dia (2025-03-11 se convertiria en 3 de
    noviembre en vez de 11 de marzo). El resto de formatos (dd/mm/aaaa,
    dd-mm-aaaa, etc., como los de una exportacion manual) si necesitan
    `dayfirst=True` para no confundir dia y mes."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip()
    if texto == "" or texto.lower() == "nan":
        return None

    if re.match(r"^\d{4}-\d{2}-\d{2}", texto):
        fecha = pd.to_datetime(texto, errors="coerce")
    else:
        fecha = pd.to_datetime(texto, dayfirst=True, errors="coerce")

    if pd.isna(fecha):
        return None
    return fecha.date().isoformat()


def cargar_archivo(ruta: Path) -> pd.DataFrame:
    if ruta.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(ruta, dtype=str)
    return pd.read_csv(ruta, dtype=str, sep=None, engine="python")


def mapear_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """Renombra las columnas de un DataFrame crudo (encabezados del portal)
    a los nombres de campo internos, descartando las que no se reconocen
    (p.ej. la columna "Opciones", que solo trae botones de la UI)."""
    df = df.copy()
    df.columns = [COLUMN_MAP.get(normalizar_encabezado(col), None) for col in df.columns]
    return df.loc[:, [c for c in df.columns if c is not None]]


def importar_dataframe(
    df: pd.DataFrame, palabra_clave: str | None = None, lote_id: str | None = None
) -> tuple[int, int]:
    """Valida e inserta en SQLite las filas de un DataFrame ya mapeado a
    los nombres de campo internos (codigo, entidad_contratante, ...).
    Si se indica `palabra_clave`, se asigna a todas las filas importadas
    (para registrar con que busqueda del portal se obtuvieron). Si se indica
    `lote_id`, se asigna igual a todas las filas de esta llamada, para poder
    reconstruir mas tarde que filas pertenecen a una misma ejecucion de
    scraping/importacion (ver scripts/report_generator.py).
    Devuelve (registros_importados, registros_con_error)."""
    faltantes = {"codigo", "entidad_contratante", "objeto_proceso", "estado"} - set(df.columns)
    if faltantes:
        print(f"ERROR: faltan columnas requeridas: {faltantes}")
        return 0, 0

    database.init_db()

    importados, con_error = 0, 0
    for i, fila in df.iterrows():
        datos = {
            "codigo": str(fila.get("codigo", "")).strip(),
            "entidad_contratante": str(fila.get("entidad_contratante", "")).strip(),
            "objeto_proceso": str(fila.get("objeto_proceso", "")).strip(),
            "estado": str(fila.get("estado", "")).strip(),
            "provincia_canton": (
                str(fila["provincia_canton"]).strip()
                if "provincia_canton" in df.columns and pd.notna(fila.get("provincia_canton"))
                else None
            ),
            "presupuesto_referencial": (
                parsear_presupuesto(fila.get("presupuesto_referencial"))
                if "presupuesto_referencial" in df.columns
                else None
            ),
            "fecha_publicacion": (
                parsear_fecha(fila.get("fecha_publicacion"))
                if "fecha_publicacion" in df.columns
                else None
            ),
            "palabra_clave": palabra_clave,
            "url": (
                str(fila["url"]).strip()
                if "url" in df.columns and pd.notna(fila.get("url"))
                else None
            ),
            "lote_id": lote_id,
        }

        try:
            validado = ContratacionCreate(**datos)
        except ValidationError as exc:
            con_error += 1
            print(f"Fila {i + 2}: omitida ({exc.error_count()} error(es) de validacion)")
            continue

        data = validado.model_dump()
        if data.get("fecha_publicacion") is not None:
            data["fecha_publicacion"] = data["fecha_publicacion"].isoformat()
        database.insert_contratacion(data)
        importados += 1

    return importados, con_error


def importar(ruta: Path, palabra_clave: str | None = None) -> None:
    df = mapear_columnas(cargar_archivo(ruta))
    importados, con_error = importar_dataframe(df, palabra_clave=palabra_clave)
    print(f"\nImportacion completa: {importados} registro(s) insertado(s), {con_error} omitido(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archivo", type=Path, help="Ruta al CSV/Excel exportado del portal")
    parser.add_argument(
        "--palabra-clave",
        type=str,
        default=None,
        help="Palabra clave usada en la busqueda del portal, para registrarla en cada fila importada.",
    )
    args = parser.parse_args()

    if not args.archivo.exists():
        print(f"ERROR: no existe el archivo {args.archivo}")
        sys.exit(1)

    importar(args.archivo, palabra_clave=args.palabra_clave)
