"""Agrupa las capturas de pantalla (.png) por ejecucion de scraping (lote)
y las asigna al bloque semestral que les corresponda, para el reporte
Word armado por scripts/reportes_generator.py.

Las capturas las genera scripts/scrape_portal.py en CAPTURAS_DIR (mismo
directorio que ese script usa para guardarlas). Este modulo solo LEE esa
carpeta, nunca escribe ni borra nada en ella (ver CLAUDE.local.md: la
carpeta capturas/ es "entorno de produccion local").

IMPORTANTE -- los patrones de nombre de archivo (PATRON_CAPTURA_NUEVO/
PATRON_CAPTURA_LEGADO) y los slugs (`_slug_palabra_clave`/`_slug_lote_id`)
deben coincidir EXACTAMENTE con scripts/scrape_portal.py::_slug_palabra_clave/
_slug_lote_id, que es quien decide como se llaman esos archivos.
"""
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

CAPTURAS_DIR = Path(__file__).resolve().parent.parent / "capturas"

MESES_POR_SEMESTRE = 6

PATRON_CAPTURA_NUEVO = re.compile(
    r"^(?P<slug>.+)_(?P<lote_slug>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})_pag_(?P<pagina>\d+)\.png$"
)
PATRON_CAPTURA_LEGADO = re.compile(
    r"^(?P<slug>.+)_(?P<dia>\d{2})-(?P<mes>[a-zA-Z]+)-(?P<anio>\d{4})_pag_(?P<pagina>\d+)\.png$"
)

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}


class CapturasNoDisponiblesError(RuntimeError):
    """CAPTURAS_DIR no existe (todavia no se corrio ninguna importacion)."""


def verificar_capturas_dir_disponible() -> None:
    if not CAPTURAS_DIR.exists():
        raise CapturasNoDisponiblesError(
            f"No se encontro la carpeta de capturas en: {CAPTURAS_DIR}"
        )


def _slug_palabra_clave(palabra_clave: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(palabra_clave or ""))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sin_acentos.lower()).strip("_")
    return slug or "sin_palabra_clave"


def _slug_lote_id(lote_id) -> str | None:
    if lote_id is None or (isinstance(lote_id, float) and pd.isna(lote_id)):
        return None
    texto = str(lote_id).strip()
    if not texto:
        return None
    return re.sub(r"[^A-Za-z0-9_-]", "-", texto)


def lotes_de_capturas(capturas_dir: Path, palabra_clave: str) -> list[tuple[str, list[Path]]]:
    """Agrupa las capturas de `capturas_dir` que pertenecen a
    `palabra_clave` por ejecucion de scraping, en orden cronologico.
    Devuelve pares (clave_de_orden, imagenes)."""
    slug = _slug_palabra_clave(palabra_clave)
    if not capturas_dir.exists():
        return []

    imagenes_por_clave: dict = {}
    orden_por_clave: dict = {}

    for archivo in capturas_dir.iterdir():
        coincidencia = PATRON_CAPTURA_NUEVO.match(archivo.name)
        if coincidencia and coincidencia.group("slug") == slug:
            clave = coincidencia.group("lote_slug")
            orden_por_clave[clave] = clave
            imagenes_por_clave.setdefault(clave, []).append(
                (int(coincidencia.group("pagina")), archivo)
            )
            continue

        coincidencia = PATRON_CAPTURA_LEGADO.match(archivo.name)
        if coincidencia and coincidencia.group("slug") == slug:
            mes_num = MESES_ES.get(coincidencia.group("mes").lower())
            if mes_num is None:
                continue
            fecha = pd.Timestamp(
                year=int(coincidencia.group("anio")), month=mes_num, day=int(coincidencia.group("dia"))
            ).date()
            clave = f"{fecha.isoformat()}T00-00-00"
            orden_por_clave[clave] = clave
            imagenes_por_clave.setdefault(clave, []).append(
                (int(coincidencia.group("pagina")), archivo)
            )

    lotes = []
    for clave in sorted(imagenes_por_clave, key=lambda c: orden_por_clave[c]):
        paginas_ordenadas = sorted(imagenes_por_clave[clave], key=lambda t: t[0])
        lotes.append((clave, [ruta for _, ruta in paginas_ordenadas]))
    return lotes


def asignar_lotes_a_semestres(
    df_palabra: pd.DataFrame,
    lotes: list[tuple[str, list[Path]]],
    semestres: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> list[list[Path]]:
    """Asigna cada lote de capturas al semestre que le corresponde por
    FECHA REAL (mediana de fecha_publicacion de las filas con ese
    lote_id), no por posicion."""
    resultado: list[list[Path]] = [[] for _ in semestres]
    if not semestres:
        return resultado

    lote_slug_por_fila = (
        df_palabra["lote_id"].map(_slug_lote_id)
        if "lote_id" in df_palabra.columns
        else pd.Series(dtype=object)
    )

    for clave_orden, imagenes in lotes:
        ancla = None
        if not lote_slug_por_fila.empty:
            filas_lote = df_palabra[lote_slug_por_fila == clave_orden]
            fechas_lote = pd.to_datetime(filas_lote.get("fecha_publicacion"), errors="coerce").dropna()
            if not fechas_lote.empty:
                ancla = fechas_lote.median()
        if ancla is None:
            ancla = pd.to_datetime(clave_orden.split("T")[0], errors="coerce")

        indice = len(semestres) - 1
        if not pd.isna(ancla):
            for i, (inicio, fin) in enumerate(semestres):
                if inicio <= ancla <= fin:
                    indice = i
                    break
        resultado[indice].extend(imagenes)

    return resultado


def rangos_semestrales(fecha_inicio_global, fecha_fin_global) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Divide [fecha_inicio_global, fecha_fin_global] en bloques
    consecutivos de MESES_POR_SEMESTRE (6) meses calendario."""
    inicio = pd.to_datetime(fecha_inicio_global)
    fin = pd.to_datetime(fecha_fin_global)
    if pd.isna(inicio) or pd.isna(fin) or inicio >= fin:
        return [(inicio, fin)]

    bloques = []
    cursor = inicio
    while cursor < fin:
        fin_bloque = cursor + pd.DateOffset(months=MESES_POR_SEMESTRE)
        if fin_bloque > fin:
            fin_bloque = fin
        bloques.append((cursor, fin_bloque))
        cursor = fin_bloque
    return bloques


def opciones_lote_id(registros: list[dict]) -> dict[str, str]:
    """Etiqueta legible -> lote_id real, para el selectbox de "Lote de
    carga especifico" en ui/reportes.py."""
    from datetime import datetime

    info_por_lote: dict[str, dict] = {}
    for registro in registros:
        lote = registro.get("lote_id")
        if not lote:
            continue
        info = info_por_lote.setdefault(lote, {"palabra_clave": registro.get("palabra_clave") or "", "n": 0})
        info["n"] += 1

    opciones = {}
    for lote in sorted(info_por_lote, reverse=True):
        info = info_por_lote[lote]
        try:
            fecha_legible = datetime.fromisoformat(lote).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            fecha_legible = lote
        palabra_clave = info["palabra_clave"] or "sin palabra clave"
        etiqueta = f"{fecha_legible} — {palabra_clave} ({info['n']} procesos)"
        opciones[etiqueta] = lote
    return opciones


# --- Division de capturas demasiado altas para una pagina -------------------
#
# Las capturas de scrape_portal.py son full-page screenshots de la tabla de
# resultados del portal: pueden salir de 12" a 24" de alto una vez
# insertadas a 6" de ancho, muy por encima del alto util de una pagina
# carta con margenes (~9"). Sin dividirlas, Word simplemente recorta la
# parte de la imagen que no entra en la pagina -- se pierde contenido de
# la tabla sin ningun aviso.

SOLAPE_PARTES_PX = 40  # solape entre partes consecutivas, para no perder filas en el corte
VENTANA_BUSQUEDA_CORTE_PX = 60  # cuanto se busca hacia atras un corte "limpio" antes del limite de pagina
DESVIACION_FILA_BLANCA_MAX = 8.0  # desviacion estandar de gris por debajo de la cual una fila se considera "en blanco"


def _buscar_mejor_corte(imagen_gris: np.ndarray, corte_ideal: int, ventana_px: int, limite_inferior: int) -> int:
    """Busca, entre `limite_inferior` y `corte_ideal`, la fila de pixeles
    mas uniforme (menor desviacion estandar de gris -- una fila de texto
    tiene pixeles muy dispares, un espacio en blanco entre filas de la
    tabla es casi todo del mismo tono) para cortar justo despues de ella
    en vez de partir el corte exactamente en `corte_ideal`, que podria
    caer sobre una fila de texto de la tabla.

    Solo mira HACIA ATRAS desde `corte_ideal` (nunca mas alla): el valor
    que devuelve es siempre <= `corte_ideal`, que es el limite que
    garantiza que la parte resultante no exceda el alto util de la
    pagina -- ver dividir_imagen_si_no_cabe."""
    inicio_ventana = max(limite_inferior, corte_ideal - ventana_px)
    if inicio_ventana >= corte_ideal:
        return corte_ideal

    mejor_fila = corte_ideal
    mejor_desviacion = float("inf")
    for y in range(corte_ideal - 1, inicio_ventana - 1, -1):
        desviacion = float(imagen_gris[y].std())
        if desviacion < mejor_desviacion:
            mejor_desviacion = desviacion
            mejor_fila = y + 1  # cortar DESPUES de la fila uniforme y
        if desviacion <= DESVIACION_FILA_BLANCA_MAX:
            break  # ya es suficientemente uniforme, no hace falta seguir buscando mas atras
    return mejor_fila


def dividir_imagen_si_no_cabe(
    ruta_imagen: Path,
    ancho_insercion: int,
    alto_util: int,
    directorio_salida: Path,
) -> list[Path]:
    """Si `ruta_imagen`, insertada a un ancho de `ancho_insercion` EMU,
    renderizaria mas alto que `alto_util` EMU (ambos son enteros en EMU,
    la unidad interna de python-docx -- `docx.shared.Emu`/`Inches`/`Cm`
    son subclases de `int`), la divide verticalmente en tantas partes
    como haga falta para que cada una quepa en una pagina, con un
    pequeno solape (`SOLAPE_PARTES_PX`) entre partes consecutivas para no
    perder filas de la tabla en el corte. Cada corte interno se ajusta
    (ver `_buscar_mejor_corte`) a la fila mas parecida a un espacio en
    blanco que encuentre cerca, para no partir una fila de texto por la
    mitad.

    Las partes se guardan en `directorio_salida` -- NUNCA en la carpeta
    de origen de `ruta_imagen` (capturas/ es de solo lectura, ver
    CAPTURAS_DIR arriba).

    Si la imagen ya cabe en una pagina, devuelve `[ruta_imagen]` sin
    tocar el archivo original ni crear `directorio_salida`."""
    with Image.open(ruta_imagen) as imagen:
        ancho_px, alto_px = imagen.size
        alto_renderizado = int(ancho_insercion * alto_px / ancho_px)
        if alto_renderizado <= alto_util:
            return [ruta_imagen]

        alto_util_px = max(1, int(alto_util * ancho_px / ancho_insercion))

        imagen_gris = np.asarray(imagen.convert("L"))
        rangos: list[tuple[int, int]] = []
        cursor = 0
        while cursor < alto_px:
            fin_ideal = min(cursor + alto_util_px, alto_px)
            if fin_ideal < alto_px:
                fin = _buscar_mejor_corte(imagen_gris, fin_ideal, VENTANA_BUSQUEDA_CORTE_PX, cursor + 1)
            else:
                fin = fin_ideal
            rangos.append((cursor, fin))
            if fin >= alto_px:
                break
            # Solapar SOLAPE_PARTES_PX con la parte anterior, pero siempre
            # avanzar al menos 1px (evita loop infinito si alto_util_px
            # fuera tan chico que el solape "coma" toda la parte).
            cursor = max(fin - SOLAPE_PARTES_PX, cursor + 1)

        directorio_salida.mkdir(parents=True, exist_ok=True)
        total = len(rangos)
        partes = []
        for indice, (inicio, fin) in enumerate(rangos, start=1):
            recorte = imagen.crop((0, inicio, ancho_px, fin))
            ruta_parte = directorio_salida / f"{ruta_imagen.stem}_parte{indice}de{total}.png"
            recorte.save(ruta_parte)
            partes.append(ruta_parte)
        return partes
