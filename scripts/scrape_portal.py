"""Abre una ventana real de Chromium contra el buscador de procesos de
SERCOP para que el usuario resuelva el CAPTCHA y lance la busqueda EL MISMO
(este script no lee ni resuelve el captcha por ti: solo abre el navegador,
espera a que completes la busqueda manualmente y extrae TODAS las paginas
de resultados hacia la base de datos SQLite local).

Uso:
    .venv/Scripts/python.exe scripts/scrape_portal.py [--espera SEGUNDOS] [--palabra-clave TEXTO]

Flujo:
    1. Se abre una ventana de Chromium en la pagina de busqueda del SERCOP.
    2. Completas los filtros que quieras (rango de fechas, palabra clave,
       entidad, etc.), LEES el codigo del CAPTCHA en la imagen, lo escribes
       en el campo junto a la imagen, y presionas el boton "Buscar" del
       propio sitio.
    3. El script espera (hasta --espera segundos como maximo, pero continua
       en cuanto detecta resultados) a que aparezca contenido en la tabla
       de resultados. Antes de extraer, lee automaticamente lo que
       escribiste en el campo "Palabras claves" del formulario (sin que
       tengas que pasarlo por linea de comandos) y lo guarda en cada
       proceso importado; `--palabra-clave` sigue disponible para forzar
       un valor especifico si la lectura automatica no encuentra nada.
    4. Extrae TODAS las paginas de resultados disponibles (el portal pagina
       los resultados, ej. "Procesos del 1 al 20 de 169": el script hace
       clic en "Siguiente" hasta la ultima pagina), incluyendo el enlace
       directo de cada proceso (el `href` del codigo, que `pd.read_html`
       no preserva), y guarda todo en la base de datos.
    5. Al terminar cierra el navegador e imprime cuantos procesos guardo.
       Si no encontro ninguna tabla reconocible, guarda el HTML de la
       pagina en un archivo de depuracion para poder revisarlo.

Para buscar otro periodo (el portal solo permite un rango de 6 meses antes
y 15 dias despues de la fecha de publicacion) o otra palabra clave, vuelve
a ejecutar el script.

Nota: el script hace una unica busqueda por ejecucion y no pregunta si
quieres continuar, porque la terminal desde la que se lanza normalmente
pierde la entrada estandar interactiva cuando el proceso tarda mas de
~2 minutos, y cualquier pregunta por teclado fallaria con EOFError.
"""
import argparse
import re
import sys
import time
import unicodedata
from io import StringIO
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import Page, Route, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.import_csv import mapear_columnas, importar_dataframe  # noqa: E402

URL_BUSQUEDA = (
    "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/"
    "buscarProceso.cpe?sg=1"
)
ESPERA_POR_DEFECTO_S = 90  # tiempo maximo para completar el captcha y la busqueda
MAX_PAGINAS = 50
DEBUG_DUMP_PATH = Path(__file__).resolve().parent.parent / "debug_sin_tabla.html"
DEBUG_ROUTE_LOG_PATH = Path(__file__).resolve().parent.parent / "debug_rutas_red.txt"


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


def _forzar_codificacion_windows1252(route: Route) -> None:
    """El portal declara `charset=utf-8` en sus paginas HTML, pero los bytes
    reales de la pagina de resultados no son utf-8 valido (son windows-1252
    o equivalente). Si se deja que Chromium decodifique segun lo declarado,
    los caracteres con tilde/ene quedan sustituidos por un caracter de
    reemplazo de forma IRREVERSIBLE (la informacion original ya no se puede
    recuperar despues). Por eso se intercepta cada respuesta (de cualquier
    tipo, no solo "document"/"xhr"/"fetch": no hay certeza de como clasifica
    Playwright la llamada que arma la tabla en este sitio) y se le indica al
    navegador la codificacion real antes de que la parsee, sin tocar ni
    perder ningun byte del contenido. Se registra cada intento en
    DEBUG_ROUTE_LOG_PATH para poder diagnosticar si algo no se reescribe."""
    request = route.request
    entrada = f"{request.resource_type} {request.method} {request.url}"

    try:
        response = route.fetch()
    except Exception as exc:
        _registrar_linea_debug(f"{entrada} | FETCH_ERROR: {exc}")
        try:
            route.continue_()
        except Exception:
            pass
        return

    content_type = response.headers.get("content-type", "")
    entrada += f" | status={response.status} content-type={content_type!r}"

    try:
        if "text/html" in content_type.lower() or "text/plain" in content_type.lower():
            headers = {**response.headers, "content-type": "text/html; charset=windows-1252"}
            route.fulfill(response=response, headers=headers)
            entrada += " | reescrito a windows-1252"
        else:
            route.fulfill(response=response)
    except Exception as exc:
        entrada += f" | FULFILL_ERROR: {exc}"

    _registrar_linea_debug(entrada)


def _registrar_linea_debug(linea: str) -> None:
    with open(DEBUG_ROUTE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


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


def _extraer_mapa_codigo_a_url(html: str, url_base: str) -> dict[str, str]:
    """Arma un mapa {codigo: url} con el enlace directo de cada proceso en
    el portal, leyendo el `href` del enlace de la columna Codigo.

    `pd.read_html` (usado en `_extraer_tabla_resultados`) solo trae el
    texto de las celdas, no atributos HTML como `href`, asi que este enlace
    se extrae aparte con BeautifulSoup sobre el mismo HTML. Se identifica
    la tabla de resultados por la fila de encabezado `tr.filaTitulo` (la
    misma marca que usa el portal, vista en el HTML real). El emparejamiento
    con el DataFrame se hace por el texto del codigo (no por posicion), asi
    no depende de que ambos parsers procesen las filas en el mismo orden."""
    soup = BeautifulSoup(html, "html.parser")
    fila_titulo = soup.find("tr", class_="filaTitulo")
    if fila_titulo is None:
        return {}
    tabla = fila_titulo.find_parent("table")
    if tabla is None:
        return {}

    mapa: dict[str, str] = {}
    for fila in tabla.find_all("tr"):
        clases = fila.get("class") or []
        if fila is fila_titulo or "filaTitulo" in clases:
            continue
        primera_celda = fila.find("td")
        if primera_celda is None:
            continue
        enlace = primera_celda.find("a")
        href = enlace.get("href") if enlace else None
        if not href:
            continue
        codigo_texto = primera_celda.get_text(strip=True)
        if codigo_texto:
            mapa[codigo_texto] = urljoin(url_base, href)
    return mapa


def _esperar_resultados(page: Page, espera_s: int) -> None:
    """Espera activamente (a diferencia de un `time.sleep` fijo) a que el
    contenedor de resultados del portal (`div#divProcesos`) tenga contenido,
    hasta un maximo de `espera_s` segundos. Como el portal arma la tabla de
    resultados dinamicamente en el navegador (no hay una unica respuesta de
    red reconocible como "la tabla"), esta es la forma confiable de saber
    que la busqueda ya cargo, sin depender de adivinar cuanto tarda el
    usuario en resolver el captcha y hacer clic en Buscar."""
    try:
        page.wait_for_function(
            "() => {"
            "  const el = document.getElementById('divProcesos');"
            "  return !!el && el.textContent.trim().length > 0;"
            "}",
            timeout=espera_s * 1000,
        )
    except Exception:
        print(
            f"  No se detecto contenido en los resultados tras {espera_s} "
            "segundos; se intentara extraer de todos modos."
        )


def _extraer_palabra_clave(page: Page) -> str | None:
    """Lee automaticamente lo que el usuario escribio en el campo "Palabras
    claves" del formulario de busqueda del portal, para no depender de que
    se indique por linea de comandos. El campo real (visto en el HTML del
    formulario) es `#txtPalabrasClaves`; por si el sitio lo cambia de id,
    se intenta primero por selectores parciales y, como ultimo respaldo, se
    busca el input ubicado junto al texto "Palabras claves" en la fila del
    formulario."""
    candidatos_selector = [
        "#txtPalabrasClaves",
        "input[name*='alabra' i]",
        "input[id*='alabra' i]",
    ]
    for selector in candidatos_selector:
        loc = page.locator(selector).first
        if loc.count() == 0:
            continue
        try:
            valor = loc.input_value(timeout=2000)
        except Exception:
            continue
        if valor and valor.strip():
            return valor.strip()

    try:
        etiqueta = page.locator("text=Palabras claves").first
        if etiqueta.count() > 0:
            input_cercano = etiqueta.locator(
                "xpath=ancestor::tr[1]//input[@type='text' or not(@type)]"
            ).first
            if input_cercano.count() > 0:
                valor = input_cercano.input_value(timeout=2000)
                if valor and valor.strip():
                    return valor.strip()
    except Exception:
        pass

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


def _procesar_busqueda(page: Page, palabra_clave: str | None = None) -> tuple[int, int, int]:
    """Extrae e importa todas las paginas de resultados disponibles tras la
    busqueda ya realizada por el usuario. Si se indica `palabra_clave`, se
    asigna a todos los registros importados en esta ejecucion. Devuelve
    (importados, con_error, paginas)."""
    importados_total, con_error_total, paginas = 0, 0, 0
    while paginas < MAX_PAGINAS:
        html = page.content()
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
        if len(df) == 0:
            # Algunas paginaciones del portal dejan el enlace "Siguiente"
            # clickeable aun sin mas datos, mostrando una tabla vacia (solo
            # encabezado). Sin este corte, el bucle seguiria "avanzando"
            # sobre paginas vacias hasta MAX_PAGINAS.
            break

        mapa_urls = _extraer_mapa_codigo_a_url(html, page.url)
        if mapa_urls:
            df["url"] = df["codigo"].astype(str).str.strip().map(mapa_urls)

        importados, con_error = importar_dataframe(df, palabra_clave=palabra_clave)
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
            "Segundos maximos a esperar a que aparezcan resultados (el "
            "script continua antes si los detecta). "
            f"Por defecto {ESPERA_POR_DEFECTO_S}."
        ),
    )
    parser.add_argument(
        "--palabra-clave",
        type=str,
        default=None,
        help=(
            "Fuerza la palabra clave a registrar en los procesos importados, "
            "en vez de leerla automaticamente del campo 'Palabras claves' "
            "del formulario (uso normal: no hace falta pasarla)."
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
        "Este script NO lee ni resuelve el captcha por ti; espera hasta "
        f"{args.espera} segundos a que aparezcan resultados y luego importa "
        "todas las paginas."
    )
    if args.palabra_clave:
        print(f"Se forzara la palabra clave {args.palabra_clave!r} en cada proceso importado.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.route("**/*", _forzar_codificacion_windows1252)
        page.goto(URL_BUSQUEDA, timeout=60000)

        try:
            page.click("button:has-text('Aceptar')", timeout=5000)
        except Exception:
            pass

        print(f"\nEsperando hasta {args.espera} segundos a que completes la busqueda...")
        _esperar_resultados(page, args.espera)

        palabra_clave = args.palabra_clave or _extraer_palabra_clave(page)
        if palabra_clave:
            print(f"Palabra clave detectada: {palabra_clave!r} (se guardara en cada proceso).")
        else:
            print("No se detecto ninguna palabra clave en el formulario; se guardara vacia.")

        importados, con_error, paginas = _procesar_busqueda(page, palabra_clave=palabra_clave)

        print(
            f"\nBusqueda completa: {importados} registro(s) insertado(s) en "
            f"{paginas} pagina(s) de resultados, {con_error} omitido(s) por "
            "error de validacion.\n"
            "Para buscar otro periodo o palabra clave, ejecuta el script de nuevo."
        )
        browser.close()


if __name__ == "__main__":
    main()
