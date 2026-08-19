"""Lectura genérica de archivos tabulares (.xlsx/.csv/.txt) subidos por el
usuario, compartida entre los distintos importadores híbridos del proyecto
(`scripts/importador_parametros.py`, `scripts/importador_items.py`): decodifica
texto probando varios encodings, detecta el separador, y arma una matriz
cruda de celdas de texto sin interpretar significado -- insumo tanto de los
parsers determinísticos como de los normalizadores vía LLM de cada
importador.

Se usa `csv.reader` (no `pd.read_csv`) para .csv/.txt: los archivos reales
de estos flujos traen filas de largo distinto (ej. líneas de continuación
con menos campos que una fila completa), y `pd.read_csv` revienta con
"Error tokenizing data. Expected N fields, saw M" ante eso -- `csv.reader`
no exige un largo uniforme."""
import csv
import io

import pandas as pd


def celda_a_texto(valor) -> str:
    """Normaliza una celda (de pandas o de csv.reader) a texto: NaN/None a
    "", floats enteros sin ".0", BOM y espacios recortados."""
    if valor is None:
        return ""
    if isinstance(valor, float):
        if pd.isna(valor):
            return ""
        if valor.is_integer():
            return str(int(valor))
        return str(valor)
    return str(valor).lstrip("﻿").strip()


def decodificar_texto(contenido: bytes) -> str:
    """Prueba UTF-8 con BOM, UTF-8 sin BOM, y Latin-1 como fallback."""
    for codificacion in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return contenido.decode("utf-8", errors="ignore")


def detectar_separador(nombre_archivo: str, texto: str) -> str:
    """Tab para .txt; para .csv se intenta detectar ";" o "," automáticamente
    con csv.Sniffer, con ";" como respaldo (separador que usa Excel en
    configuración regional Ecuador/es-ES, donde "," está reservado como
    separador decimal)."""
    if nombre_archivo.endswith(".txt"):
        return "\t"
    muestra = "\n".join(texto.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(muestra, delimiters=";,").delimiter
    except csv.Error:
        return ";"


def leer_matriz_cruda(nombre_archivo: str, contenido: bytes) -> list[list[str]]:
    """Lee el archivo completo (.xlsx/.csv/.txt) como una matriz cruda de
    celdas de texto, preservando el orden y SIN descartar celdas vacías.
    Lanza ValueError (genérico -- cada importador lo envuelve en su propia
    excepción específica) si el archivo no se puede leer."""
    nombre = (nombre_archivo or "").lower()
    if nombre.endswith(".xlsx"):
        try:
            df = pd.read_excel(io.BytesIO(contenido), header=None)
        except Exception as exc:
            raise ValueError(f"No se pudo leer el archivo: {exc}") from exc
        return [[celda_a_texto(celda) for celda in fila] for fila in df.itertuples(index=False, name=None)]

    texto = decodificar_texto(contenido)
    separador = detectar_separador(nombre, texto)
    try:
        filas = list(csv.reader(io.StringIO(texto), delimiter=separador))
    except csv.Error as exc:
        raise ValueError(f"No se pudo leer el archivo: {exc}") from exc
    return [[celda_a_texto(celda) for celda in fila] for fila in filas]
