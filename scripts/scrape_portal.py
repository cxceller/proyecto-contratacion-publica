"""Abre una ventana real de Chromium contra el buscador de procesos de
SERCOP para que el usuario resuelva el CAPTCHA y lance la busqueda EL MISMO
(este script no lee ni resuelve el captcha por ti: solo abre el navegador,
espera a que completes la busqueda manualmente y extrae TODAS las paginas
de resultados hacia la base de datos SQLite local).

Uso:
    .venv/Scripts/python.exe scripts/scrape_portal.py [--espera SEGUNDOS]

Flujo:
    1. Se abre una ventana de Chromium en la pagina de busqueda del SERCOP.
    2. Completas los filtros que quieras (rango de fechas, palabra clave,
       entidad, etc.), LEES el codigo del CAPTCHA en la imagen, lo escribes
       en el campo junto a la imagen, y presionas el boton "Buscar" del
       propio sitio.
    3. El script espera --espera segundos (1 minuto por defecto) para que
       cargue la busqueda, y luego extrae TODAS las paginas de resultados
       (el portal pagina los resultados, ej. "Procesos del 1 al 20 de 169":
       el script hace clic en "Siguiente" hasta la ultima pagina) guardando
       cada una en la base de datos.
    4. Al terminar cierra el navegador e imprime cuantos procesos guardo.
       Si no encontro ninguna tabla reconocible, guarda el HTML de la
       pagina en un archivo de depuracion para poder revisarlo.

Para buscar otro periodo (el portal solo permite un rango de 6 meses antes
y 15 dias despues de la fecha de publicacion) o otra palabra clave, vuelve
a ejecutar el script.

Nota: el script hace una unica busqueda por ejecucion y no pregunta si
quieres continuar, porque la terminal desde la que se lanza normalmente
pierde la entrada estandar interactiva cuando el proceso tarda mas de
~2 minutos (lo que ya ocurre solo con la espera por defecto), y cualquier
pregunta por teclado fallaria con EOFError.
"""
import argparse
import re
import sys
import time
import unicodedata
from io import StringIO
from pathlib import Path

import pandas as pd
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.import_csv import mapear_columnas, importar_dataframe  # noqa: E402

URL_BUSQUEDA = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/"
    "buscarProceso.cpe?sg=1"
)
ESPERA_POR_DEFECTO_S = 60  # 1 minuto para completar el captcha y la busqueda
MAX_PAGINAS = 50
DEBUG_DUMP_PATH = Path(__file__).resolve().parent.parent / "debug_sin_tabla.html"


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", str(texto))
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", sin_acentos.lower())


def _aplanar_columnas(columnas: pd.Index) -> list[str]:
    """Convierte encabezados de una sola fila o de varias filas (MultiIndex,
    frecuente cuando la tabla HTML tiene celdas de encabezado combinadas) en
    una lista plana de strings."""
    if isinstance(columnas, pd.MultiIndex):
        return [
            " ".join(
                str(nivel)
                for nivel in tupla
                if str(nivel) and not str(nivel).lower().startswith("unnamed")
            )
            for tupla in columnas
        ]
    return [str(c) for c in columnas]


CLAVES_ENCABEZADO_ESPERADAS = {"codigo", "entidadcontratante", "objetodelproceso"}


def _con_encabezado_valido(tabla: pd.DataFrame) -> pd.DataFrame | None:
    """Si la tabla ya trae los encabezados esperados en sus columnas, la
    devuelve con columnas planas. Si no (el portal de SERCOP dibuja el
    encabezado como una fila normal de la tabla, con <td> en vez de <th>,
    por lo que pandas la interpreta como fila de datos), promueve la
    primera fila a encabezado cuando coincide con lo esperado."""
    columnas_planas = _aplanar_columnas(tabla.columns)
    if CLAVES_ENCABEZADO_ESPERADAS & {_normalizar(c) for c in columnas_planas}:
        tabla = tabla.copy()
        tabla.columns = columnas_planas
        return tabla

    if len(tabla) > 0:
        primera_fila = [str(v) for v in tabla.iloc[0].tolist()]
        if CLAVES_ENCABEZADO_ESPERADAS & {_normalizar(v) for v in primera_fila}:
            tabla = tabla.iloc[1:].copy()
            tabla.columns = primera_fila
            return tabla.reset_index(drop=True)

    return None


def _decodificar_html(datos: bytes) -> str:
    """El portal de SERCOP declara charset=utf-8 pero algunas paginas (las
    de resultados) en realidad no vienen en utf-8 valido; si se usa el DOM
    ya decodificado por Chromium (`page.content()`) los caracteres invalidos
    quedan sustituidos por `?` de forma irreversible. Por eso se decodifican
    los bytes crudos de la respuesta HTTP aqui mismo, con un fallback a
    windows-1252 cuando utf-8 estricto falla."""
    try:
        return datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos.decode("windows-1252", errors="replace")


def _registrar_captura_html(page: Page) -> dict[str, bytes]:
    """Registra un listener que guarda los bytes crudos del ultimo
    documento HTML principal recibido en la pagina (busqueda inicial,
    resultados, cada pagina de paginacion), para decodificarlos nosotros
    mismos en vez de depender de `page.content()`."""
    captura: dict[str, bytes] = {}

    def _al_recibir_respuesta(response):
        try:
            if response.frame == page.main_frame and response.status == 200:
                captura["bytes"] = response.body()
        except Exception:
            pass

    page.on("response", _al_recibir_respuesta)
    return captura


def _html_actual(page: Page, captura: dict[str, bytes]) -> str:
    datos = captura.get("bytes")
    return _decodificar_html(datos) if datos else page.content()


def _extraer_tabla_resultados(html: str) -> pd.DataFrame | None:
    """Busca, entre todas las tablas de la pagina, la que tiene encabezados
    de procesos de contratacion (Codigo, Entidad Contratante, ...)."""
    try:
        tablas = pd.read_html(StringIO(html))
    except ValueError:
        return None

    for tabla in tablas:
        encontrada = _con_encabezado_valido(tabla)
        if encontrada is not None:
            return encontrada
    return None


def _intentar_siguiente_pagina(page: Page) -> bool:
    """Busca un enlace/boton de 'Siguiente' en la paginacion y hace clic.
    Devuelve True si avanzo de pagina, False si no encontro mas paginas."""
    candidatos = [
        "a:has-text('Siguiente')",
        "a:has-text('>')",
        "a[title='Siguiente']",
        "img[alt='Siguiente']",
    ]
    for selector in candidatos:
        loc = page.locator(selector).first
        if loc.count() > 0 and loc.is_visible():
            try:
                loc.click()
                page.wait_for_load_state("networkidle", timeout=30000)
                return True
            except Exception:
                return False
    return False


def _procesar_busqueda(page: Page, captura: dict[str, bytes]) -> tuple[int, int, int]:
    """Extrae e importa todas las paginas de resultados disponibles tras la
    busqueda ya realizada por el usuario. Devuelve
    (importados, con_error, paginas)."""
    importados_total, con_error_total, paginas = 0, 0, 0
    while paginas < MAX_PAGINAS:
        html = _html_actual(page, captura)
        tabla = _extraer_tabla_resultados(html)
        if tabla is None:
            if paginas == 0:
                DEBUG_DUMP_PATH.write_text(html, encoding="utf-8")
                print(
                    "  No se encontro una tabla de resultados reconocible. "
                    f"Se guardo el HTML de la pagina en {DEBUG_DUMP_PATH} para revisarlo."
                )
            break

        df = mapear_columnas(tabla)
        importados, con_error = importar_dataframe(df)
        importados_total += importados
        con_error_total += con_error
        paginas += 1
        print(f"  Pagina {paginas}: {importados} importados, {con_error} con error.")

        if not _intentar_siguiente_pagina(page):
            break
        time.sleep(1)

    return importados_total, con_error_total, paginas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--espera",
        type=int,
        default=ESPERA_POR_DEFECTO_S,
        help=(
            "Segundos de espera para completar el CAPTCHA y la busqueda "
            f"antes de extraer la tabla. Por defecto {ESPERA_POR_DEFECTO_S}."
        ),
    )
    args = parser.parse_args()

    print(f"Abriendo Chromium en: {URL_BUSQUEDA}")
    print(
        "Completa los filtros que quieras (recuerda: el portal solo permite "
        "un rango de 6 meses antes y 15 dias despues de la fecha de "
        "publicacion), LEE el codigo del CAPTCHA en la imagen, escribelo en "
        "el cuadro de texto de al lado y presiona el boton 'Buscar' del "
        "propio sitio.\n"
        "Este script NO lee ni resuelve el captcha por ti; solo espera "
        f"{args.espera} segundos y luego importa todas las paginas de resultados."
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        captura = _registrar_captura_html(page)
        page.goto(URL_BUSQUEDA, timeout=60000)

        try:
            page.click("button:has-text('Aceptar')", timeout=5000)
        except Exception:
            pass

        print(f"\nEsperando {args.espera} segundos para que completes la busqueda...")
        time.sleep(args.espera)

        importados, con_error, paginas = _procesar_busqueda(page, captura)

        print(
            f"\nBusqueda completa: {importados} registro(s) insertado(s) en "
            f"{paginas} pagina(s) de resultados, {con_error} omitido(s) por "
            "error de validacion.\n"
            "Para buscar otro periodo o palabra clave, ejecuta el script de nuevo."
        )
        browser.close()


if __name__ == "__main__":
    main()
