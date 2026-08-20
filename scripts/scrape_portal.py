"""Abre una ventana real de Chromium contra el buscador de procesos de
SERCOP para que el usuario resuelva el CAPTCHA y lance la busqueda EL MISMO
(este script no lee ni resuelve el captcha por ti: solo abre el navegador,
espera a que completes la busqueda manualmente y extrae TODAS las paginas
de resultados hacia la base de datos SQLite local).

Uso:
    .venv/Scripts/python.exe scripts/scrape_portal.py [--espera SEGUNDOS] [--palabra-clave TEXTO] [--sin-monto-adjudicado]

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
       no preserva). Por cada proceso con enlace, visita ademas su pagina
       de detalle -- con un pool acotado de pestanas trabajando en paralelo
       (ver MAX_PESTANAS_DETALLE_CONCURRENTES) -- para leer el "Monto de
       Adjudicacion ($)" real de la seccion "Informacion de Adjudicacion"
       -- un dato que no viene en la tabla de resultados -- con un pequeno
       retraso por pestana entre visitas para no sobrecargar el portal; si
       un proceso puntual falla (pagina caida, sin adjudicar todavia,
       estructura cambiada) queda con ese campo vacio, sin interrumpir el
       resto. `--sin-monto-adjudicado` permite saltarse esta fase por
       completo cuando no hace falta ese dato (mas rapido). Todo se guarda
       en la base de datos, y por cada pagina de resultados con datos se
       guarda tambien una captura de pantalla completa en
       `capturas/[palabra_clave]_[lote_id]_pag_[numero].png` (el lote_id
       identifica esta ejecucion, ver mas abajo).
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
import asyncio
import re
import sys
import unicodedata
from datetime import datetime
from io import StringIO
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import BrowserContext, Page, Route, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.import_csv import importar_dataframe, mapear_columnas, parsear_presupuesto  # noqa: E402

URL_BUSQUEDA = "https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/PC/buscarProceso.cpe"
ESPERA_POR_DEFECTO_S = 90  # tiempo maximo para completar el captcha y la busqueda
MAX_PAGINAS = 50
# Cuantas pestanas de detalle trabajan en paralelo dentro de
# _obtener_montos_adjudicados (ver esa funcion). Punto de partida
# razonable para no bombardear al portal SERCOP con una rafaga de
# peticiones simultaneas; subir o bajar segun que tan bien lo tolere.
MAX_PESTANAS_DETALLE_CONCURRENTES = 4
# Pequeno retraso, POR PESTANA del pool, entre visitas a paginas de detalle
# (Monto de Adjudicacion), para no sobrecargar el portal SERCOP con una
# rafaga de visitas seguidas. Con el pool, la tasa efectiva es de hasta
# MAX_PESTANAS_DETALLE_CONCURRENTES peticiones cada ~ESPERA_ENTRE_ADJUDICACIONES_S
# segundos (antes era 1 cada ese intervalo); si se sube la concurrencia y se
# quiere ser mas conservador, subir tambien este valor.
ESPERA_ENTRE_ADJUDICACIONES_S = 0.5
TIMEOUT_ADJUDICACION_MS = 20000
# Timeout corto y tolerante (no los 20s completos de TIMEOUT_ADJUDICACION_MS):
# la fila "Estado del Proceso" de la pagina general se arma via JS en el
# onload (activeTab(...)) DESPUES de que el HTML inicial ya llego -- sin
# esperarla, _extraer_motivo_estado casi siempre lee el DOM antes de que
# esa fila exista y devuelve None (confirmado con un volcado real: la fila
# completa, no solo el valor, tarda ~2s en aparecer). Si el timeout expira
# igual se sigue con motivo=None, mismo patron tolerante que ya usa
# _ir_a_resumen_de_contrato con su propio wait_for_selector.
TIMEOUT_MOTIVO_ESTADO_MS = 6000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DEBUG_DUMP_PATH = Path(__file__).resolve().parent.parent / "debug_sin_tabla.html"
DEBUG_ROUTE_LOG_PATH = Path(__file__).resolve().parent.parent / "debug_rutas_red.txt"
CAPTURAS_DIR = Path(__file__).resolve().parent.parent / "capturas"


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


async def _forzar_codificacion_windows1252(route: Route) -> None:
    """El portal declara `charset=utf-8` en sus paginas HTML, pero los bytes
    reales de la pagina de resultados no son utf-8 valido (son windows-1252
    o equivalente). Si se deja que Chromium decodifique segun lo declarado,
    los caracteres con tilde/ene quedan sustituidos por un caracter de
    reemplazo de forma IRREVERSIBLE (la informacion original ya no se puede
    recuperar despues). Por eso se intercepta cada respuesta de tipo
    "document"/"xhr"/"fetch" (los unicos que pueden traer el HTML/JSON de
    la tabla en este sitio; imagenes, CSS, fuentes y JS estatico no
    necesitan re-encoding y se dejan pasar de inmediato con
    `route.continue_()`, sin el `route.fetch()`+`route.fulfill()` extra que
    antes se hacia para TODO el trafico) y se le indica al navegador la
    codificacion real antes de que la parsee, sin tocar ni perder ningun
    byte del contenido. Se registra cada intento en DEBUG_ROUTE_LOG_PATH
    para poder diagnosticar si algo no se reescribe."""
    request = route.request
    if request.resource_type not in ("document", "xhr", "fetch"):
        await route.continue_()
        return

    entrada = f"{request.resource_type} {request.method} {request.url}"

    try:
        response = await route.fetch(max_redirects=0)
    except Exception as exc:
        _registrar_linea_debug(f"{entrada} | FETCH_ERROR: {exc}")
        try:
            await route.continue_()
        except Exception:
            pass
        return

    content_type = response.headers.get("content-type", "")
    entrada += f" | status={response.status} content-type={content_type!r}"

    try:
        if "text/html" in content_type.lower() or "text/plain" in content_type.lower():
            headers = {**response.headers, "content-type": "text/html; charset=windows-1252"}
            await route.fulfill(response=response, headers=headers)
            entrada += " | reescrito a windows-1252"
        else:
            await route.fulfill(response=response)
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


# Etiquetas que identifican el dato en las dos plantillas reales de
# resumen contractual que usa el portal (confirmado navegando paginas
# reales): "Monto de Adjudicacion ($)" en resumenContractual1.cpe,
# "Monto de Adjudicacion" (sin "($)") en resumenContractual.cpe. Ambas
# normalizan igual ("montodeadjudicacion", ver _normalizar), asi que un
# solo patron alcanza para las dos. "Valor Adjudicado" se agrega para el
# caso de Subasta Inversa Electronica descrito en la seccion "Ver
# resultados de negociacion" -- NO se pudo confirmar contra una pagina
# real (ningun proceso de Guayaquil quedo en esa fase especifica al
# momento de escribir esto), se agrega igual por las dudas pero con menos
# certeza que las otras dos.
ETIQUETAS_MONTO_ADJUDICADO = ("montodeadjudicacion", "valoradjudicado")


def _tabla_con_columna_monto_adjudicacion(tabla: pd.DataFrame) -> tuple[str, pd.DataFrame] | None:
    """Busca una columna que identifique el Monto de Adjudicacion (ver
    ETIQUETAS_MONTO_ADJUDICADO) en una tabla ya leida por `pd.read_html`,
    sea que pandas la haya reconocido como encabezado real (`tabla.columns`)
    o que -- verificado contra una pagina real de resumenContractual1.cpe:
    NINGUNA de sus tablas trae `<th>`, todas quedan con columnas enteras
    0,1,2,... y el encabezado real aparece como la PRIMERA FILA de datos --
    haya que promover la primera fila a encabezado, el mismo quirk que ya
    resuelve `_con_encabezado_valido` para la tabla de resultados de
    busqueda, aca generalizado a esta columna en particular. Este es el
    formato de tabla "una fila por adjudicatario" (resumenContractual1.cpe);
    ver _valor_monto_adjudicacion_en_celdas para el otro formato, de
    "etiqueta: valor" (resumenContractual.cpe). Devuelve
    (nombre_de_columna, tabla_con_encabezado_ya_promovido), o None si la
    columna no aparece de ninguna de las dos formas."""
    columnas_planas = _aplanar_columnas(tabla.columns)
    columna_monto = next(
        (c for c in columnas_planas if any(e in _normalizar(c) for e in ETIQUETAS_MONTO_ADJUDICADO)), None
    )
    if columna_monto is not None:
        tabla = tabla.copy()
        tabla.columns = columnas_planas
        return columna_monto, tabla

    if len(tabla) > 0:
        primera_fila = [str(v) for v in tabla.iloc[0].tolist()]
        columna_monto = next(
            (v for v in primera_fila if any(e in _normalizar(v) for e in ETIQUETAS_MONTO_ADJUDICADO)), None
        )
        if columna_monto is not None:
            tabla = tabla.iloc[1:].copy()
            tabla.columns = primera_fila
            return columna_monto, tabla.reset_index(drop=True)

    return None


def _valores_monto_adjudicacion_en_celdas(tabla: pd.DataFrame) -> list[float]:
    """Busca el Monto de Adjudicacion en el otro formato que usa el portal
    para la pagina de detalle: NO como columna de una tabla con una fila
    por adjudicatario, sino como una celda-etiqueta suelta (ej. "Monto de
    Adjudicacion") con el valor en dolares en una celda vecina de la MISMA
    fila (confirmado contra una pagina real de resumenContractual.cpe, sin
    el "1" -- el portal a veces arma toda la pagina como una unica tabla
    gigante de dos columnas "etiqueta: valor" en vez de tablas separadas
    por seccion). El HTML de origen suele repetir el mismo valor en varias
    celdas contiguas por como se combinan columnas (colspan) al leerlo con
    pandas, asi que alcanza con la primera celda de la fila, distinta de
    la etiqueta, que se pueda interpretar como numero."""
    valores: list[float] = []
    for _, fila in tabla.iterrows():
        valores_fila = list(fila)
        indice_etiqueta = next(
            (
                i
                for i, celda in enumerate(valores_fila)
                if isinstance(celda, str) and any(e in _normalizar(celda) for e in ETIQUETAS_MONTO_ADJUDICADO)
            ),
            None,
        )
        if indice_etiqueta is None:
            continue
        for i, celda in enumerate(valores_fila):
            if i == indice_etiqueta:
                continue
            numero = parsear_presupuesto(celda)
            if numero is not None:
                valores.append(numero)
                break
    return valores


def _extraer_monto_adjudicado(html: str) -> float | None:
    """Busca, entre todas las tablas de la pagina de detalle de un proceso
    (la pagina "Resumen del Contrato"/"Resumen Informacion Esencial del
    Contrato" -- ver _obtener_montos_adjudicados sobre como se llega ahi;
    el portal usa AL MENOS dos plantillas distintas para esa pagina segun
    el proceso: resumenContractual1.cpe y resumenContractual.cpe, ambas
    confirmadas contra paginas reales, con estructura de tabla diferente
    entre si -- ver _tabla_con_columna_monto_adjudicacion y
    _valores_monto_adjudicacion_en_celdas), el "Monto de Adjudicacion" real
    y devuelve la suma (un solo valor si hay un unico adjudicatario, la
    suma de todos si hay varios). Se identifica EXCLUSIVAMENTE por las
    etiquetas de ETIQUETAS_MONTO_ADJUDICADO, para no confundirlo con "Monto
    Contractual ($)" (tabla de "Informacion del Contrato", mas abajo en la
    misma pagina, con una forma muy parecida en la plantilla de tabla).
    Devuelve None si no aparece en ninguna tabla (proceso todavia sin
    adjudicar) o si el HTML no se puede interpretar -- nunca lanza, para
    que un solo proceso con la pagina caida o con la estructura cambiada
    no interrumpa el resto de la importacion (ver _obtener_montos_adjudicados).
    Ademas de `ValueError` (lo que lanza pd.read_html cuando no encuentra
    ninguna tabla), un HTML vacio o gravemente malformado puede hacer que
    el parser XML subyacente (lxml) lance su propio `XMLSyntaxError` -- por
    eso se captura `Exception` en general en vez de solo `ValueError`."""
    try:
        tablas = pd.read_html(StringIO(html))
    except Exception:
        return None

    for tabla in tablas:
        encontrada = _tabla_con_columna_monto_adjudicacion(tabla)
        if encontrada is not None:
            columna_monto, tabla_con_encabezado = encontrada
            valores = tabla_con_encabezado[columna_monto].map(parsear_presupuesto).dropna().tolist()
        else:
            valores = _valores_monto_adjudicacion_en_celdas(tabla)

        if valores:
            return float(sum(valores))

    return None


def _extraer_motivo_estado(html: str) -> str | None:
    """Extrae el texto completo de la celda "Estado del Proceso" de la
    pagina GENERAL de detalle de un proceso (informacionProcesoContratacion2.cpe,
    la misma pagina a la que ya se navega para llegar a "Resumen de
    Contrato"/"Resumen de Resultados PN" -- ver _obtener_montos_adjudicados).
    Para estados como "Desierta", "Cancelado" o "Suspendido" esa celda trae
    Razon, Fecha y Justificacion completas (confirmado por el usuario con
    captura del portal: para un proceso "Desierta" el portal explica
    textualmente el articulo de ley y el motivo), no solo la palabra del
    estado -- un dato que hoy se descarta porque solo se guarda la
    etiqueta corta (columna `estado`, que viene de la tabla de resultados
    de busqueda, no de esta pagina). Se captura para TODOS los procesos, no
    solo "Desierta": es gratis obtenerlo (la pagina ya se visita para leer
    el Monto de Adjudicacion) y sirve de base para
    scripts/explicar_estado_desierta.py. Devuelve el texto crudo tal cual
    aparece en el portal (celdas de la fila separadas por salto de linea),
    o None si no se encuentra la fila -- nunca lanza, mismo criterio de
    tolerancia a fallos que el resto de las funciones de extraccion de esta
    pagina."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None
    etiqueta = soup.find(string=re.compile(r"Estado del Proceso", re.IGNORECASE))
    if etiqueta is None:
        return None
    fila = etiqueta.find_parent("tr")
    if fila is None:
        return None
    # find_all(["th", "td"]), no solo "td": la fila real del portal es
    # <th>Estado del Proceso</th><td>valor</td> (etiqueta en <th>, no en
    # <td>) -- con solo "td" quedaba un unico elemento y `len < 2` hacia
    # devolver None aunque la fila estuviera completa. Backward-compatible
    # con el formato <td><td> (celdas[-1] sigue siendo el valor en ambos).
    celdas = fila.find_all(["th", "td"])
    if len(celdas) < 2:
        return None
    texto = celdas[-1].get_text(separator="\n", strip=True)
    return texto or None


async def _ir_a_resumen_de_contrato(pagina_detalle: Page) -> bool:
    """Desde la pagina general de un proceso (informacionProcesoContratacion2.cpe,
    la URL que ya se guarda en la columna `url`), navega hasta la pagina
    real de resumen contractual (resumenContractual1.cpe o
    resumenContractual.cpe, segun el proceso -- ver _extraer_monto_adjudicado)
    haciendo clic en el enlace "Resumen de Contrato" de la seccion "FASE
    CONTRACTUAL" -- confirmado navegando paginas reales: el "Monto de
    Adjudicacion" NO esta en la pagina general, solo ahi. Antes de buscar
    ese enlace, cierra el aviso de cookies si aparece (igual que ya hace
    main() en la pagina de busqueda, via el mismo boton "Aceptar") --
    mientras el aviso este abierto intercepta los clics y el de "Resumen
    de Contrato" fallaria. En vez de esperar a que la red quede inactiva
    (`wait_for_load_state("networkidle")`, lento en un sitio con trackers
    de fondo), espera puntualmente los selectores que de verdad hacen
    falta: primero que aparezca el enlace "Resumen de Contrato" (o el
    timeout, lo cual es normal en un proceso que todavia no llego a fase
    contractual -- ver mas abajo), y despues de hacer clic, que aparezca
    alguna tabla en la pagina de resumen contractual (ambas plantillas,
    resumenContractual1.cpe y resumenContractual.cpe, son tablas). Devuelve
    False (sin lanzar) si el enlace "Resumen de Contrato" no aparece dentro
    del timeout -- no hay adjudicacion/contrato registrado aun, asi que el
    enlace ni existe -- lo cual es un resultado normal, no un error."""
    try:
        await pagina_detalle.click("button:has-text('Aceptar')", timeout=3000)
    except Exception:
        pass

    try:
        await pagina_detalle.wait_for_selector("text=Resumen de Contrato", timeout=TIMEOUT_ADJUDICACION_MS)
    except PlaywrightTimeoutError:
        return False

    enlace_resumen = pagina_detalle.locator("text=Resumen de Contrato").first
    await enlace_resumen.click(timeout=10000)
    try:
        await pagina_detalle.wait_for_selector("table", timeout=TIMEOUT_ADJUDICACION_MS)
    except PlaywrightTimeoutError:
        pass
    return True


def _es_proceso_produccion_nacional(codigo: str) -> bool:
    """Los procesos VPN (Verificacion de Produccion Nacional) tienen un
    flujo de fases distinto al resto -- sin ningun paso de "Resumen de
    Contrato" (confirmado por el usuario con capturas del portal: su fase
    precontractual es Preguntas/Respuestas/Aclaraciones > Entrega de
    Propuesta > Apertura de ofertas > Calificacion de Participantes >
    Publicar resultado > Finalizada, sin fase contractual) -- identificable
    por el prefijo VPN de su codigo (ej. VPN-MIMG-2026-001). Por eso
    _ir_a_resumen_de_contrato siempre les devuelve False (no hay error,
    simplemente el enlace que busca no existe para este tipo de proceso) y
    quedan con monto_adjudicado en NULL aunque si esten adjudicados -- ver
    _ir_a_resumen_resultados_pn/_extraer_monto_desde_subtotal para el
    camino equivalente que si les aplica."""
    return codigo.strip().upper().startswith("VPN")


# El texto exacto del enlace "Resumen de Resultados PN" no se pudo
# confirmar contra una pagina real en vivo (portal con CAPTCHA, ver
# _ir_a_resumen_resultados_pn) -- se prueban varios candidatos en orden,
# mismo patron de respaldo que ya usa _extraer_palabra_clave, por si el
# portal varia mayusculas/espacios entre procesos.
_CANDIDATOS_ENLACE_RESUMEN_PN = [
    "text=Resumen de Resultados PN",
    "text=Resumen de Resultados",
    "a:has-text('Resumen de Resultados PN')",
    "a:has-text('Resultados PN')",
]


async def _ir_a_resumen_resultados_pn(pagina_worker: Page) -> bool:
    """Analogo a _ir_a_resumen_de_contrato, pero para procesos VPN (ver
    _es_proceso_produccion_nacional): en vez de "Resumen de Contrato", la
    seccion FASE PRECONTRACTUAL de estos procesos trae un enlace "Resumen
    de Resultados PN" que lleva a la pagina "Lista de Preseleccionados"
    (con un bloque "CERTIFICADO DE PRODUCCION NACIONAL"), cuya tabla
    "Detalle:" trae el monto adjudicado real en la columna SubTotal (ver
    _extraer_monto_desde_subtotal). Prueba los selectores candidatos de
    _CANDIDATOS_ENLACE_RESUMEN_PN en orden y usa el primero que aparezca.
    Devuelve False (sin lanzar) si ninguno aparece -- mismo criterio que
    _ir_a_resumen_de_contrato: no es un error, puede ser un proceso que
    todavia no llego a esa fase o cuyo enlace no matchea ninguno de los
    candidatos."""
    try:
        await pagina_worker.click("button:has-text('Aceptar')", timeout=3000)
    except Exception:
        pass

    for selector in _CANDIDATOS_ENLACE_RESUMEN_PN:
        enlace = pagina_worker.locator(selector).first
        try:
            if await enlace.count() == 0:
                continue
            await enlace.click(timeout=10000)
        except Exception:
            continue
        try:
            await pagina_worker.wait_for_selector("text=Detalle:", timeout=TIMEOUT_ADJUDICACION_MS)
        except PlaywrightTimeoutError:
            pass
        return True

    return False


def _tabla_con_columna_subtotal(tabla: pd.DataFrame) -> tuple[str, pd.DataFrame] | None:
    """Analoga a _tabla_con_columna_monto_adjudicacion pero para la columna
    "SubTotal" de la tabla "Detalle" de un proceso VPN (ver
    _extraer_monto_desde_subtotal): el mismo quirk del portal aplica aca --
    el encabezado real puede venir como fila normal (<td>, no <th>), asi
    que pandas la deja con columnas enteras 0,1,2,... y hay que promover la
    primera fila a encabezado cuando corresponda."""
    columnas_planas = _aplanar_columnas(tabla.columns)
    if any(_normalizar(c) == "subtotal" for c in columnas_planas):
        tabla = tabla.copy()
        tabla.columns = columnas_planas
        return "SubTotal", tabla

    if len(tabla) > 0:
        primera_fila = [str(v) for v in tabla.iloc[0].tolist()]
        if any(_normalizar(v) == "subtotal" for v in primera_fila):
            tabla = tabla.iloc[1:].copy()
            tabla.columns = primera_fila
            return "SubTotal", tabla.reset_index(drop=True)

    return None


def _extraer_monto_desde_subtotal(html: str) -> float | None:
    """Extrae el monto adjudicado de un proceso VPN (ver
    _es_proceso_produccion_nacional) sumando la columna "SubTotal" de la
    tabla "Detalle" en la pagina "Lista de Preseleccionados" (columnas
    Categoria | Descripcion | Cant. | Unidad Medida | Precio Ref.
    Unitarios | SubTotal -- confirmado por el usuario con captura del
    portal). Misma logica de "sumar todas las filas" que ya usa
    _extraer_monto_adjudicado para procesos con varios adjudicatarios.
    Se maneja separada de ETIQUETAS_MONTO_ADJUDICADO/_extraer_monto_adjudicado
    a proposito: "subtotal" es una etiqueta demasiado generica para
    mezclarla ahi -- podria matchear tablas no relacionadas en otras
    paginas -- por eso esta funcion solo se invoca cuando el codigo
    empieza con VPN."""
    try:
        tablas = pd.read_html(StringIO(html))
    except Exception:
        return None

    for tabla in tablas:
        encontrada = _tabla_con_columna_subtotal(tabla)
        if encontrada is None:
            continue
        columna_subtotal, tabla_con_encabezado = encontrada
        valores = tabla_con_encabezado[columna_subtotal].map(parsear_presupuesto).dropna().tolist()
        if valores:
            return float(sum(valores))

    return None


def _es_proceso_licitacion(codigo: str) -> bool:
    """Procesos de Licitacion (de Obras/LICO, de Servicios/LICS, de
    Bienes/LICB -- el prefijo comun "LIC" cubre las tres) no siempre tienen
    "Resumen de Contrato" aunque ya esten "Adjudicado - Registro de
    Contratos": ese enlace solo aparece una vez que la entidad registra el
    contrato, y hasta entonces el "Monto de Adjudicacion" real ya esta
    publicado en otra pagina -- ver _ir_a_resumen_resultados_licitacion/
    _extraer_monto_licitacion para la ruta de respaldo que si les aplica.
    Verificado navegando una pagina real (LICS-MIMG-2026-008); LICO/LICB
    comparten el mismo tipo de procedimiento "Licitacion" y la misma
    plantilla de pagina, pero conviene confirmarlos contra un proceso
    adjudicado real cuando aparezca uno."""
    return codigo.strip().upper().startswith("LIC")


# El enlace "Ver Resultados de Licitacion" no vive en la pestaña
# "Descripción" que carga por defecto (activeTab(1,...) del onload, ver
# TIMEOUT_MOTIVO_ESTADO_MS), sino dentro de la pestaña "Fechas" -- hay que
# abrirla primero (confirmado navegando una pagina real: buscar el enlace
# sin abrir esa pestaña no lo encuentra). Selector por texto, no por id de
# pestaña (#tab2 puede no ser estable entre distintos tipos de proceso).
_CANDIDATOS_TAB_FECHAS = ["a:has-text('Fechas')", "text=Fechas"]

# Mismo motivo que _CANDIDATOS_ENLACE_RESUMEN_PN: varios candidatos por si
# el portal varia acentos/mayusculas entre procesos.
_CANDIDATOS_ENLACE_RESULTADOS_LICITACION = [
    "text=Ver Resultados de Licitación",
    "text=Ver Resultados de Licitacion",
    "a:has-text('Resultados de Licitación')",
    "a:has-text('Resultados de Licitacion')",
]


async def _ir_a_resumen_resultados_licitacion(pagina_worker: Page) -> bool:
    """Analogo a _ir_a_resumen_resultados_pn, pero para procesos de
    Licitacion (ver _es_proceso_licitacion): abre la pestaña "Fechas" y
    despues el enlace "Ver Resultados de Licitación", que lleva a
    resumenAdjudicacion.cpe ("Resumen de Adjudicación a Proveedores"), cuya
    tabla "Bien/Obra/Servicio Adjudicados" trae el monto adjudicado real en
    la columna Subtotal (ver _extraer_monto_licitacion). Devuelve False (sin
    lanzar) si no se encuentra la pestaña o el enlace -- mismo criterio
    tolerante que el resto de las funciones de navegacion de esta pagina."""
    try:
        await pagina_worker.click("button:has-text('Aceptar')", timeout=3000)
    except Exception:
        pass

    for selector in _CANDIDATOS_TAB_FECHAS:
        tab = pagina_worker.locator(selector).first
        try:
            if await tab.count() == 0:
                continue
            await tab.click(timeout=10000)
        except Exception:
            continue
        break

    for selector in _CANDIDATOS_ENLACE_RESULTADOS_LICITACION:
        enlace = pagina_worker.locator(selector).first
        try:
            if await enlace.count() == 0:
                continue
            await enlace.click(timeout=10000)
        except Exception:
            continue
        try:
            await pagina_worker.wait_for_selector("table", timeout=TIMEOUT_ADJUDICACION_MS)
        except PlaywrightTimeoutError:
            pass
        return True

    return False


# Columnas (normalizadas via _normalizar) que solo aparecen en la tabla
# "Bien/Obra/Servicio Adjudicados" de resumenAdjudicacion.cpe, nunca en la
# tabla "Detalle: Bien/Obra/Servicio" (referencial, misma forma de tabla y
# tambien con columna Subtotal) -- confirmado contra una pagina real
# (LICS-MIMG-2026-008): la referencial trae "Precio Ref. Unitarios" y
# ninguno de estos tres; la de adjudicados siempre trae al menos uno.
_MARCADORES_TABLA_LICITACION_ADJUDICADA = {"razonadjudicacion", "cantidadadjudicada", "estado"}


def _tabla_resultados_licitacion_adjudicados(tabla: pd.DataFrame) -> tuple[str, pd.DataFrame] | None:
    """Analoga a _tabla_con_columna_subtotal, pero exige ADEMAS al menos uno
    de _MARCADORES_TABLA_LICITACION_ADJUDICADA para no confundir la tabla de
    adjudicados con la referencial (ambas traen columna Subtotal). A
    diferencia de _tabla_con_columna_subtotal, el nombre real de la columna
    Subtotal se toma tal cual aparece en la tabla (no se asume "SubTotal"
    literal): confirmado que el portal usa una capitalizacion distinta en
    cada una de estas dos tablas ("SubTotal" en la referencial, "Subtotal"
    en la de adjudicados), asi que forzar un literal fijo rompe el lookup
    de columna en una de las dos. Mismo quirk de encabezado-como-fila que
    _tabla_con_columna_subtotal."""
    columnas_planas = _aplanar_columnas(tabla.columns)
    columna_subtotal = next((c for c in columnas_planas if _normalizar(c) == "subtotal"), None)
    if columna_subtotal is not None and {_normalizar(c) for c in columnas_planas} & _MARCADORES_TABLA_LICITACION_ADJUDICADA:
        tabla = tabla.copy()
        tabla.columns = columnas_planas
        return columna_subtotal, tabla

    if len(tabla) > 0:
        primera_fila = [str(v) for v in tabla.iloc[0].tolist()]
        columna_subtotal = next((v for v in primera_fila if _normalizar(v) == "subtotal"), None)
        if columna_subtotal is not None and {_normalizar(v) for v in primera_fila} & _MARCADORES_TABLA_LICITACION_ADJUDICADA:
            tabla = tabla.iloc[1:].copy()
            tabla.columns = primera_fila
            return columna_subtotal, tabla.reset_index(drop=True)

    return None


def _extraer_monto_licitacion(html: str) -> float | None:
    """Extrae el monto adjudicado real de un proceso de Licitacion (ver
    _es_proceso_licitacion) desde resumenAdjudicacion.cpe, sumando la
    columna Subtotal de la tabla "Bien/Obra/Servicio Adjudicados" -- NUNCA
    la tabla "Detalle: Bien/Obra/Servicio" (referencial, igual al
    presupuesto: tomarla por error dejaria el "% de Ahorro" siempre en 0%).
    Ver _tabla_resultados_licitacion_adjudicados para como se distinguen.
    Devuelve None si no aparece esa tabla especifica en ninguna de las
    tablas de la pagina (mejor None que el valor referencial equivocado) o
    si el HTML no se puede interpretar -- nunca lanza, mismo criterio de
    tolerancia a fallos que _extraer_monto_adjudicado."""
    try:
        tablas = pd.read_html(StringIO(html))
    except Exception:
        return None

    for tabla in tablas:
        encontrada = _tabla_resultados_licitacion_adjudicados(tabla)
        if encontrada is None:
            continue
        columna_subtotal, tabla_con_encabezado = encontrada
        valores = tabla_con_encabezado[columna_subtotal].map(parsear_presupuesto).dropna().tolist()
        if valores:
            return float(sum(valores))

    return None


def _es_proceso_subasta_inversa(codigo: str) -> bool:
    """Procesos de Subasta Inversa Electronica: igual que Licitacion (ver
    _es_proceso_licitacion), el Monto de Adjudicacion real puede estar
    publicado en "Ver Resultados de Subasta" (ResumenPuja.cpe) antes de que
    exista "Resumen de Contrato" (tipico en "Adjudicado - Registro de
    Contratos", contrato aun sin registrar) -- ver
    _ir_a_resumen_resultados_subasta para la ruta de respaldo que les
    aplica. Para SIE ya en "Ejecución de Contrato" (con contrato
    registrado), la ruta existente "Resumen de Contrato" ya resuelve el
    valor sin necesidad de este respaldo -- confirmado contra una pagina
    real (SIE-MIMG-2026-021)."""
    return codigo.strip().upper().startswith("SIE")


# Un SIE puede exponer el enlace como "Ver Resultados de Subasta" (termino
# por puja) o como "Ver Resultados de Negociacion" (se resolvio por
# negociacion, ej. un solo oferente) -- AMBOS llevan a la MISMA pagina
# ResumenPuja.cpe con el mismo "Valor Adjudicado". Confirmado contra dos
# paginas reales: SIE-MIMG-2026-021 (Subasta, $80,000.00) y
# SIE-MIMG-2026-002 (Negociacion, $37,000.00) -- buscar solo "Subasta"
# dejaba a este segundo en NULL sin necesidad (mismo motivo de fondo que
# _CANDIDATOS_ENLACE_RESULTADOS_LICITACION: variantes de texto reales, no
# hipoteticas).
_CANDIDATOS_ENLACE_RESULTADOS_SUBASTA = [
    "text=Ver Resultados de Subasta",
    "text=Ver Resultados de Negociación",
    "text=Resultados de Subasta",
    "text=Resultados de Negociación",
    "a:has-text('Resultados de Subasta')",
    "a:has-text('Resultados de Negociación')",
]


async def _ir_a_resumen_resultados_subasta(pagina_worker: Page) -> bool:
    """Analogo a _ir_a_resumen_resultados_licitacion, pero para procesos de
    Subasta Inversa Electronica (ver _es_proceso_subasta_inversa): abre la
    misma pestaña "Fechas" (_CANDIDATOS_TAB_FECHAS, ya renderizada por JS --
    compartida con la ruta de Licitacion, confirmado que el enlace vive en
    el mismo lugar) y despues el enlace "Ver Resultados de Subasta" o "Ver
    Resultados de Negociacion" (ver _CANDIDATOS_ENLACE_RESULTADOS_SUBASTA
    sobre por que hay que probar ambos), que llevan a ResumenPuja.cpe. Esa
    pagina NO es accesible por URL directa "en frio" (redirige a "Ingreso
    al Sistema"/login) -- solo se alcanza navegando dentro de la sesion ya
    abierta por el goto() previo de la ficha general, exactamente como hace
    esta funcion (nunca por URL fija). El "Monto de Adjudicacion" real ahi
    se lee bajo la etiqueta "Valor Adjudicado" -- YA cubierta por
    ETIQUETAS_MONTO_ADJUDICADO -- asi que se reusa _extraer_monto_adjudicado
    sin extractor nuevo: confirmado contra dos paginas reales (subasta y
    negociacion) que el formato "etiqueta: valor en la misma fila"
    (_valores_monto_adjudicacion_en_celdas) ya resuelve el valor correcto
    en ambos casos. Devuelve False (sin lanzar) si no se encuentra la
    pestaña ni ningun enlace candidato."""
    try:
        await pagina_worker.click("button:has-text('Aceptar')", timeout=3000)
    except Exception:
        pass

    for selector in _CANDIDATOS_TAB_FECHAS:
        tab = pagina_worker.locator(selector).first
        try:
            if await tab.count() == 0:
                continue
            await tab.click(timeout=10000)
        except Exception:
            continue
        break

    for selector in _CANDIDATOS_ENLACE_RESULTADOS_SUBASTA:
        enlace = pagina_worker.locator(selector).first
        try:
            if await enlace.count() == 0:
                continue
            await enlace.click(timeout=10000)
        except Exception:
            continue
        try:
            await pagina_worker.wait_for_selector("table", timeout=TIMEOUT_ADJUDICACION_MS)
        except PlaywrightTimeoutError:
            pass
        return True

    return False


def _es_proceso_consultoria(codigo: str) -> bool:
    """Procesos de Consultoria -- Concurso Publico (prefijo CPC) y Lista
    Corta (prefijo LCC, misma pagina y misma columna, confirmado contra
    una pagina real: LCC-MIMG-2025-007). El valor adjudicado real puede
    estar publicado en "Ver Adjudicación Consultoría"
    (resumenAdjudicacionConsultoria.cpe) antes de que exista "Resumen de
    Contrato" -- ver _ir_a_adjudicacion_consultoria para la ruta de
    respaldo. A diferencia de las otras modalidades, el valor final NO es
    el ofertado ni el referencial sino el PRECIO NEGOCIADO (Concurso
    Publico y Lista Corta de Consultoria siempre terminan en una fase de
    negociacion) -- ver _extraer_monto_consultoria sobre por que se toma
    la columna "Precio Negociación" y nunca el "SubTotal" de la tabla
    referencial. Confirmado contra paginas reales (CPC-MIMG-2026-002,
    LCC-MIMG-2025-007). Si en el futuro aparece CDC (Contratacion Directa
    de Consultoria), agregar aca tras verificar contra un proceso real."""
    codigo_norm = codigo.strip().upper()
    return codigo_norm.startswith("CPC") or codigo_norm.startswith("LCC")


# Mismo motivo que _CANDIDATOS_ENLACE_RESULTADOS_LICITACION: candidatos por
# si el portal varia acentos/mayusculas entre procesos.
_CANDIDATOS_ENLACE_ADJUDICACION_CONSULTORIA = [
    "text=Ver Adjudicación Consultoría",
    "text=Adjudicación Consultoría",
    "a:has-text('Adjudicación Consultoría')",
    "a:has-text('Adjudicaci')",
]


async def _ir_a_adjudicacion_consultoria(pagina_worker: Page) -> bool:
    """Analogo a _ir_a_resumen_resultados_licitacion, pero para procesos de
    Consultoria (ver _es_proceso_consultoria): abre la misma pestaña
    "Fechas" (_CANDIDATOS_TAB_FECHAS, compartida con Licitacion/Subasta --
    confirmado que el enlace de Consultoria vive en el mismo lugar) y
    despues el enlace "Ver Adjudicación Consultoría", que lleva a
    resumenAdjudicacionConsultoria.cpe ("Adjudicar a Proveedores"). Devuelve
    False (sin lanzar) si no se encuentra la pestaña ni el enlace.

    El contenido de la pestaña "Fechas" se arma por JS/AJAX DESPUES de que
    el clic en la pestaña ya "termino" (Playwright considera el clic
    exitoso apenas el elemento es accionable, no espera a que su contenido
    termine de renderizarse) -- confirmado con un caso real
    (LCC-MIMG-2025-007): buscar el enlace inmediatamente despues del clic
    da count()==0 en todos los candidatos; esperando ~1.5s si aparece. Por
    eso la pausa corta y tolerante entre el clic en la pestaña y la
    busqueda del enlace, en vez de buscar de inmediato."""
    try:
        await pagina_worker.click("button:has-text('Aceptar')", timeout=3000)
    except Exception:
        pass

    for selector in _CANDIDATOS_TAB_FECHAS:
        tab = pagina_worker.locator(selector).first
        try:
            if await tab.count() == 0:
                continue
            await tab.click(timeout=10000)
        except Exception:
            continue
        break

    await pagina_worker.wait_for_timeout(1500)

    for selector in _CANDIDATOS_ENLACE_ADJUDICACION_CONSULTORIA:
        enlace = pagina_worker.locator(selector).first
        try:
            if await enlace.count() == 0:
                continue
            await enlace.click(timeout=10000)
        except Exception:
            continue
        try:
            await pagina_worker.wait_for_selector("table", timeout=TIMEOUT_ADJUDICACION_MS)
        except PlaywrightTimeoutError:
            pass
        return True

    return False


# Columnas (normalizadas via _normalizar) que solo aparecen en la tabla
# "Consultoría Adjudicados" de resumenAdjudicacionConsultoria.cpe, nunca en
# la tabla "Detalle: Consultoría" (referencial, con columna SubTotal) --
# confirmado contra una pagina real (CPC-MIMG-2026-002). Mismo criterio que
# _MARCADORES_TABLA_LICITACION_ADJUDICADA.
_MARCADORES_TABLA_CONSULTORIA_ADJUDICADA = {"razonadjudicacion", "estado"}


def _tabla_consultoria_adjudicados(tabla: pd.DataFrame) -> tuple[str, pd.DataFrame] | None:
    """Analoga a _tabla_resultados_licitacion_adjudicados, pero busca la
    columna "Precio Negociación" (normalizada: precionegociacion) en vez de
    Subtotal -- en Consultoria el valor adjudicado real es el PRECIO
    NEGOCIADO (regla explicita: el Concurso Publico de Consultoria siempre
    termina en negociacion), nunca el SubTotal de la tabla referencial (que
    en Consultoria tambien existe, con la misma forma de tabla, y es igual
    al presupuesto). Exige ADEMAS al menos uno de
    _MARCADORES_TABLA_CONSULTORIA_ADJUDICADA para no confundirla con
    ninguna otra tabla que pudiera tener una columna de precio parecida.
    Mismo quirk de encabezado-como-fila que las demas tablas de esta
    pagina."""
    columnas_planas = _aplanar_columnas(tabla.columns)
    columna_precio = next((c for c in columnas_planas if _normalizar(c) == "precionegociacion"), None)
    if columna_precio is not None and {_normalizar(c) for c in columnas_planas} & _MARCADORES_TABLA_CONSULTORIA_ADJUDICADA:
        tabla = tabla.copy()
        tabla.columns = columnas_planas
        return columna_precio, tabla

    if len(tabla) > 0:
        primera_fila = [str(v) for v in tabla.iloc[0].tolist()]
        columna_precio = next((v for v in primera_fila if _normalizar(v) == "precionegociacion"), None)
        if columna_precio is not None and {_normalizar(v) for v in primera_fila} & _MARCADORES_TABLA_CONSULTORIA_ADJUDICADA:
            tabla = tabla.iloc[1:].copy()
            tabla.columns = primera_fila
            return columna_precio, tabla.reset_index(drop=True)

    return None


def _extraer_monto_consultoria(html: str) -> float | None:
    """Extrae el monto adjudicado real de un proceso de Consultoria (ver
    _es_proceso_consultoria) desde resumenAdjudicacionConsultoria.cpe,
    sumando la columna "Precio Negociación" de la tabla "Consultoría
    Adjudicados" -- NUNCA el "SubTotal" de la tabla "Detalle: Consultoría"
    (referencial, igual al presupuesto: tomarla por error dejaria el "% de
    Ahorro" siempre en 0%, mismo riesgo que en Licitacion). Ver
    _tabla_consultoria_adjudicados para como se distinguen. Devuelve None
    si no aparece esa tabla especifica (mejor None que el valor referencial
    equivocado) o si el HTML no se puede interpretar -- nunca lanza."""
    try:
        tablas = pd.read_html(StringIO(html))
    except Exception:
        return None

    for tabla in tablas:
        encontrada = _tabla_consultoria_adjudicados(tabla)
        if encontrada is None:
            continue
        columna_precio, tabla_con_encabezado = encontrada
        valores = tabla_con_encabezado[columna_precio].map(parsear_presupuesto).dropna().tolist()
        if valores:
            return float(sum(valores))

    return None


# Mismo motivo que _CANDIDATOS_ENLACE_ADJUDICACION_CONSULTORIA.
_CANDIDATOS_ENLACE_EVALUACION_FINAL_CONSULTORIA = [
    "text=Ver evaluación final",
    "text=evaluación final",
    "a:has-text('evaluaci')",
]


async def _ir_a_evaluacion_final_consultoria(pagina_worker: Page) -> bool:
    """Analoga a _ir_a_adjudicacion_consultoria, pero hacia "Ver evaluación
    final" (resumenCalificacionFinalConsultoria.cpe) -- ruta de RESPALDO
    para Consultoria (ver _extraer_valor_oferta_mas_baja), solo quando
    _ir_a_adjudicacion_consultoria/_extraer_monto_consultoria no dieron
    "Precio Negociación" (proceso sin negociacion registrada todavia).
    Misma pausa tolerante tras el clic en "Fechas" que
    _ir_a_adjudicacion_consultoria (ver esa funcion sobre por que hace
    falta). Devuelve False (sin lanzar) si no se encuentra la pestaña ni
    el enlace."""
    try:
        await pagina_worker.click("button:has-text('Aceptar')", timeout=3000)
    except Exception:
        pass

    for selector in _CANDIDATOS_TAB_FECHAS:
        tab = pagina_worker.locator(selector).first
        try:
            if await tab.count() == 0:
                continue
            await tab.click(timeout=10000)
        except Exception:
            continue
        break

    await pagina_worker.wait_for_timeout(1500)

    for selector in _CANDIDATOS_ENLACE_EVALUACION_FINAL_CONSULTORIA:
        enlace = pagina_worker.locator(selector).first
        try:
            if await enlace.count() == 0:
                continue
            await enlace.click(timeout=10000)
        except Exception:
            continue
        try:
            await pagina_worker.wait_for_selector("table", timeout=TIMEOUT_ADJUDICACION_MS)
        except PlaywrightTimeoutError:
            pass
        return True

    return False


_ETIQUETA_OFERTA_MAS_BAJA_NORMALIZADA = "valordelaofertamasbaja"


def _extraer_valor_oferta_mas_baja(html: str) -> float | None:
    """Fallback de _extraer_monto_consultoria: extrae "VALOR DE LA OFERTA
    MÁS BAJA" de resumenCalificacionFinalConsultoria.cpe -- la oferta
    ANTES de negociar, distinta del "Precio Negociación" final (para
    LCC-MIMG-2025-007, 82591.46 vs. 82013.52 -- confirmado que NO son el
    mismo valor). Solo se usa cuando no existe "Precio Negociación"
    todavia (proceso sin fase de negociacion registrada), nunca como
    fuente primaria. Fila real: `<tr><td>VALOR DE LA OFERTA MÁS
    BAJA</td><td>82591.46</td></tr>` -- mismo patron etiqueta+valor en la
    misma fila que _valores_monto_adjudicacion_en_celdas, aca simplificado
    a un solo valor esperado (no hay que sumar varias filas). Devuelve
    None si no aparece la etiqueta o el HTML no se puede interpretar --
    nunca lanza."""
    try:
        tablas = pd.read_html(StringIO(html))
    except Exception:
        return None

    for tabla in tablas:
        for _, fila in tabla.iterrows():
            valores_fila = list(fila)
            indice_etiqueta = next(
                (
                    i
                    for i, celda in enumerate(valores_fila)
                    if isinstance(celda, str) and _normalizar(celda) == _ETIQUETA_OFERTA_MAS_BAJA_NORMALIZADA
                ),
                None,
            )
            if indice_etiqueta is None:
                continue
            for i, celda in enumerate(valores_fila):
                if i == indice_etiqueta:
                    continue
                numero = parsear_presupuesto(celda)
                if numero is not None:
                    return numero

    return None


async def _obtener_montos_adjudicados(
    context: BrowserContext, mapa_urls: dict[str, str]
) -> tuple[dict[str, float | None], dict[str, str | None]]:
    """Visita la pagina de detalle de cada proceso (el mismo enlace que ya
    se guarda en la columna `url`) y de ahi navega hasta el resumen
    contractual real (ver _ir_a_resumen_de_contrato) para leer el "Monto de
    Adjudicacion" -- un dato que NO aparece ni en la tabla de resultados de
    busqueda ni en la pagina general del proceso, solo en su resumen
    contractual. Los procesos VPN (Verificacion de Produccion Nacional,
    ver _es_proceso_produccion_nacional) toman un camino distinto dentro
    del worker -- via _ir_a_resumen_resultados_pn/_extraer_monto_desde_subtotal
    -- porque no tienen fase contractual ni el enlace "Resumen de Contrato".
    De paso, apenas se llega a la pagina general (ANTES de navegar hacia
    cualquiera de esos dos resumenes, que llevan a otra pagina), tambien se
    captura el texto completo de "Estado del Proceso" (ver
    _extraer_motivo_estado) -- gratis, sin peticion extra, porque esta
    pagina ya se visita igual.

    Antes esto se hacia SECUENCIALMENTE, una pestana, un proceso a la vez;
    con 60-150+ procesos por busqueda y timeouts de hasta
    TIMEOUT_ADJUDICACION_MS, esa era la fase mas lenta del script con
    diferencia. Ahora se reparte el trabajo entre un pool acotado de
    MAX_PESTANAS_DETALLE_CONCURRENTES pestanas (todas del mismo `context`
    que ya comparte la ventana con `page` -- nunca se abren ventanas
    nuevas), cada una sacando trabajo de una cola compartida
    (`asyncio.Queue`) hasta vaciarla. La API sync de Playwright NO es seguro
    usarla desde threads distintos; por eso la concurrencia real se logra
    con la API async (`playwright.async_api`) y `asyncio`, no con
    `ThreadPoolExecutor`. El contador de progreso (`completados`) se
    actualiza sin lock porque el event loop de asyncio es de un solo hilo
    -- no hay dos corutinas ejecutando Python al mismo tiempo, solo
    intercaladas en los puntos `await`.

    Un error en UN proceso puntual (pagina caida, timeout, estructura
    cambiada) se registra en consola -- que queda en el log de la
    importacion, ver render_pagina_importacion_sercop en app_ui.py -- y NO
    interrumpe el resto: ese proceso queda con monto_adjudicado en
    None/NULL en vez de propagar la excepcion. Un proceso que todavia no
    llego a fase contractual tambien queda en None, sin loguear nada --
    ver _ir_a_resumen_de_contrato -- porque no es un error, es el estado
    esperado para un proceso que aun no se adjudica.

    Devuelve (montos, motivos): dos dicts {codigo: valor}, para no forzar a
    los callers que solo necesitan uno de los dos (ej. tests) a lidiar con
    el otro."""
    if not mapa_urls:
        return {}, {}

    montos: dict[str, float | None] = {}
    motivos: dict[str, str | None] = {}
    cola: asyncio.Queue = asyncio.Queue()
    for item in mapa_urls.items():
        cola.put_nowait(item)

    total = len(mapa_urls)
    completados = 0  # event loop de un solo hilo -> no hace falta lock

    async def worker(pagina_worker: Page) -> None:
        nonlocal completados
        while not cola.empty():
            try:
                codigo, url = cola.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await pagina_worker.goto(url, timeout=TIMEOUT_ADJUDICACION_MS)
                try:
                    await pagina_worker.wait_for_selector("text=Estado del Proceso", timeout=TIMEOUT_MOTIVO_ESTADO_MS)
                except PlaywrightTimeoutError:
                    pass
                motivos[codigo] = _extraer_motivo_estado(await pagina_worker.content())
                if _es_proceso_produccion_nacional(codigo):
                    if await _ir_a_resumen_resultados_pn(pagina_worker):
                        montos[codigo] = _extraer_monto_desde_subtotal(await pagina_worker.content())
                    else:
                        montos[codigo] = None
                elif _es_proceso_licitacion(codigo):
                    monto = None
                    if await _ir_a_resumen_de_contrato(pagina_worker):
                        monto = _extraer_monto_adjudicado(await pagina_worker.content())
                    if monto is None:
                        # Intento 2 (respaldo): "Resumen de Contrato" no
                        # existe todavia (tipico en "Adjudicado - Registro
                        # de Contratos", contrato aun sin registrar) o no
                        # trajo valor -- se vuelve a la ficha general por
                        # si el intento 1 navego a otra pagina, y se prueba
                        # la ruta de resultados de Licitacion.
                        await pagina_worker.goto(url, timeout=TIMEOUT_ADJUDICACION_MS)
                        if await _ir_a_resumen_resultados_licitacion(pagina_worker):
                            monto = _extraer_monto_licitacion(await pagina_worker.content())
                    montos[codigo] = monto
                elif _es_proceso_subasta_inversa(codigo):
                    monto = None
                    if await _ir_a_resumen_de_contrato(pagina_worker):
                        monto = _extraer_monto_adjudicado(await pagina_worker.content())
                    if monto is None:
                        # Intento 2 (respaldo): mismo criterio que Licitacion
                        # -- "Resumen de Contrato" no existe todavia (tipico
                        # en "Adjudicado - Registro de Contratos") o no trajo
                        # valor -- se vuelve a la ficha general por si el
                        # intento 1 navego a otra pagina, y se prueba la
                        # ruta de resultados de Subasta.
                        await pagina_worker.goto(url, timeout=TIMEOUT_ADJUDICACION_MS)
                        if await _ir_a_resumen_resultados_subasta(pagina_worker):
                            monto = _extraer_monto_adjudicado(await pagina_worker.content())
                    montos[codigo] = monto
                elif _es_proceso_consultoria(codigo):
                    monto = None
                    if await _ir_a_resumen_de_contrato(pagina_worker):
                        monto = _extraer_monto_adjudicado(await pagina_worker.content())
                    if monto is None:
                        # Intento 2 (respaldo): mismo criterio que Licitacion/
                        # Subasta -- se vuelve a la ficha general por si el
                        # intento 1 navego a otra pagina, y se prueba la ruta
                        # de Adjudicación Consultoría (precio negociado).
                        await pagina_worker.goto(url, timeout=TIMEOUT_ADJUDICACION_MS)
                        if await _ir_a_adjudicacion_consultoria(pagina_worker):
                            monto = _extraer_monto_consultoria(await pagina_worker.content())
                    if monto is None:
                        # Intento 3 (respaldo del respaldo): "Precio
                        # Negociación" todavia no existe (sin fase de
                        # negociacion registrada) -- se prueba la "VALOR DE
                        # LA OFERTA MÁS BAJA" de "Ver evaluación final".
                        # NUNCA el valor referencial.
                        await pagina_worker.goto(url, timeout=TIMEOUT_ADJUDICACION_MS)
                        if await _ir_a_evaluacion_final_consultoria(pagina_worker):
                            monto = _extraer_valor_oferta_mas_baja(await pagina_worker.content())
                    montos[codigo] = monto
                elif await _ir_a_resumen_de_contrato(pagina_worker):
                    montos[codigo] = _extraer_monto_adjudicado(await pagina_worker.content())
                else:
                    montos[codigo] = None
            except Exception as exc:
                print(f"  Monto de Adjudicacion de {codigo}: no se pudo obtener ({exc}).")
                montos[codigo] = None
                motivos.setdefault(codigo, None)
            completados += 1
            if completados % 5 == 0 or completados == total:
                print(f"  Monto de Adjudicacion: {completados}/{total} procesados...")
            await asyncio.sleep(ESPERA_ENTRE_ADJUDICACIONES_S)

    paginas_worker = [
        await context.new_page() for _ in range(min(MAX_PESTANAS_DETALLE_CONCURRENTES, total))
    ]
    try:
        await asyncio.gather(*(worker(p) for p in paginas_worker))
    finally:
        for p in paginas_worker:
            try:
                await p.close()
            except Exception:
                pass
    return montos, motivos


async def _esperar_resultados(page: Page, espera_s: int) -> None:
    """Espera activamente (a diferencia de un `time.sleep` fijo) a que el
    contenedor de resultados del portal (`div#divProcesos`) tenga contenido,
    hasta un maximo de `espera_s` segundos. Como el portal arma la tabla de
    resultados dinamicamente en el navegador (no hay una unica respuesta de
    red reconocible como "la tabla"), esta es la forma confiable de saber
    que la busqueda ya cargo, sin depender de adivinar cuanto tarda el
    usuario en resolver el captcha y hacer clic en Buscar. Ya usa polling
    activo via `wait_for_function` en vez de `networkidle`, asi que no
    necesito el cambio de Cambio 2 -- se deja igual."""
    try:
        await page.wait_for_function(
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


async def _extraer_palabra_clave(page: Page) -> str | None:
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
    # Todo el cuerpo va envuelto en un try/except de PlaywrightError (clase
    # base de la que hereda TargetClosedError): si el usuario cierra la
    # ventana de Chromium manualmente mientras el script todavia esta
    # leyendo el formulario, cualquier llamada aca (`.count()`,
    # `.input_value()`) puede lanzar esa excepcion -- sin este bloque, el
    # traceback crudo llegaba directo al log de la UI (ver
    # render_pagina_importacion_sercop en app_ui.py).
    try:
        for selector in candidatos_selector:
            loc = page.locator(selector).first
            if await loc.count() == 0:
                continue
            try:
                valor = await loc.input_value(timeout=2000)
            except PlaywrightError:
                continue
            if valor and valor.strip():
                return valor.strip()

        etiqueta = page.locator("text=Palabras claves").first
        if await etiqueta.count() > 0:
            input_cercano = etiqueta.locator(
                "xpath=ancestor::tr[1]//input[@type='text' or not(@type)]"
            ).first
            if await input_cercano.count() > 0:
                valor = await input_cercano.input_value(timeout=2000)
                if valor and valor.strip():
                    return valor.strip()
    except PlaywrightError:
        print("  No se pudo leer la palabra clave: la ventana del navegador se cerro antes de tiempo.")
        return None

    return None


async def _intentar_siguiente_pagina(page: Page) -> bool:
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
        if await loc.count() > 0 and await loc.is_visible():
            try:
                await loc.click()
                await page.wait_for_load_state("networkidle", timeout=30000)
                return True
            except Exception:
                return False
    return False


def _slug_palabra_clave(palabra_clave: str | None) -> str:
    """Convierte la palabra clave en un slug seguro para nombre de archivo
    (minusculas, sin acentos, solo alfanumericos y guion bajo). Si no hay
    palabra clave, devuelve un valor de respaldo en vez de dejar el nombre
    del archivo con un "None" literal."""
    if not palabra_clave:
        return "sin_palabra_clave"
    sin_acentos = unicodedata.normalize("NFKD", palabra_clave)
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sin_acentos.lower()).strip("_")
    return slug or "sin_palabra_clave"


def _slug_lote_id(lote_id: str | None) -> str:
    """Convierte el lote_id (timestamp ISO, ej. "2026-07-28T11:07:02") en un
    valor seguro para nombre de archivo: los ":" no son validos en nombres
    de archivo de Windows, asi que se reemplazan por "-". Si no hay
    lote_id, devuelve un valor de respaldo en vez de dejar el nombre del
    archivo con un "None" literal."""
    if not lote_id:
        return "sin_lote"
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(lote_id))


def _nombre_captura(palabra_clave: str | None, lote_id: str | None, numero_pagina: int) -> str:
    """Arma el nombre de archivo [palabra_clave]_[lote_id]_pag_[numero].png,
    ej. "repotenciacion_2026-07-28T11-07-02_pag_1.png". Se usa el lote_id
    (unico por ejecucion, con precision de segundos) en vez de solo la
    fecha del dia: dos ejecuciones de la misma palabra clave el mismo dia
    ya no se sobrescriben las capturas entre si."""
    return f"{_slug_palabra_clave(palabra_clave)}_{_slug_lote_id(lote_id)}_pag_{numero_pagina}.png"


async def _capturar_pantalla_pagina(
    page: Page, palabra_clave: str | None, lote_id: str | None, numero_pagina: int
) -> Path:
    """Guarda una captura de pantalla completa (full_page=True, sin cortes)
    de la pagina de resultados actual, con nombre secuencial por pagina."""
    CAPTURAS_DIR.mkdir(parents=True, exist_ok=True)
    ruta = CAPTURAS_DIR / _nombre_captura(palabra_clave, lote_id, numero_pagina)
    await page.screenshot(path=str(ruta), full_page=True)
    return ruta


async def _procesar_busqueda(
    page: Page,
    context: BrowserContext,
    palabra_clave: str | None = None,
    lote_id: str | None = None,
    sin_monto_adjudicado: bool = False,
) -> tuple[int, int, int]:
    """Extrae e importa todas las paginas de resultados disponibles tras la
    busqueda ya realizada por el usuario. Si se indica `palabra_clave`, se
    asigna a todos los registros importados en esta ejecucion. Si se indica
    `lote_id`, se asigna igual a todos los registros importados en esta
    ejecucion, para poder reconstruir mas tarde (ver
    scripts/report_generator.py) que filas pertenecen a esta misma busqueda,
    sin depender de adivinar por saltos en el id. `context` es el
    BrowserContext compartido (ver main()): se le pasa directo a
    _obtener_montos_adjudicados, que abre ahi su propio pool de pestanas de
    detalle por cada pagina de resultados, sin interferir con `page`, que
    sigue paginando los resultados de busqueda. Si `sin_monto_adjudicado`
    es True, se sigue extrayendo y guardando la columna `url` de cada
    proceso, pero se omite por completo la visita a las paginas de detalle
    (mas rapido, sin el campo Monto de Adjudicacion NI motivo_estado_raw --
    ver _obtener_montos_adjudicados, ambos se capturan en la misma visita).
    Devuelve (importados,
    con_error, paginas)."""
    importados_total, con_error_total, paginas = 0, 0, 0
    try:
        while paginas < MAX_PAGINAS:
            html = await page.content()
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
                if not sin_monto_adjudicado:
                    montos_adjudicados, motivos_estado = await _obtener_montos_adjudicados(context, mapa_urls)
                    df["monto_adjudicado"] = df["codigo"].astype(str).str.strip().map(montos_adjudicados)
                    df["motivo_estado_raw"] = df["codigo"].astype(str).str.strip().map(motivos_estado)

            importados, con_error = importar_dataframe(df, palabra_clave=palabra_clave, lote_id=lote_id)
            importados_total += importados
            con_error_total += con_error
            paginas += 1

            ruta_captura = await _capturar_pantalla_pagina(page, palabra_clave, lote_id, paginas)
            print(
                f"  Pagina {paginas}: {importados} importados, {con_error} con error. "
                f"Captura: {ruta_captura}"
            )

            if not await _intentar_siguiente_pagina(page):
                break
            await asyncio.sleep(1)
    except PlaywrightError:
        # Si el usuario cierra la ventana de Chromium a mitad de la
        # extraccion, se corta el bucle y se devuelve lo ya importado hasta
        # ese punto en vez de dejar subir un traceback crudo al log de la UI.
        print(
            "  La ventana del navegador se cerro antes de terminar de extraer "
            f"todas las paginas. Se guardo lo recolectado hasta la pagina {paginas}."
        )

    return importados_total, con_error_total, paginas


async def main() -> None:
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
    parser.add_argument(
        "--sin-monto-adjudicado",
        action="store_true",
        help="Omite la visita al detalle de cada proceso (mas rapido, sin el campo Monto de Adjudicacion).",
    )
    args = parser.parse_args()

    # Un lote_id por ejecucion (no por pagina): identifica de forma
    # confiable todas las filas insertadas por esta busqueda, para poder
    # reconstruir despues los bloques de busqueda en los reportes (ver
    # scripts/report_generator.py) sin depender de adivinar por saltos en
    # el id.
    lote_id = datetime.now().isoformat(timespec="seconds")

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
    if args.sin_monto_adjudicado:
        print("Se omitira la visita al detalle de cada proceso (sin Monto de Adjudicacion).")

    async with async_playwright() as p:
        # `--start-maximized` + `no_viewport=True` para que la ventana de
        # Chromium aparezca maximizada y al frente en vez del tamano fijo
        # (1280x720) que Playwright impone por defecto. Un unico
        # `browser.new_context(...)` para `page` (el listado) y para el
        # pool de pestanas de detalle que abre _obtener_montos_adjudicados:
        # `browser.new_page()` crea un contexto nuevo -- y por lo tanto una
        # ventana de Chromium nueva -- por cada llamada, que era la causa
        # de que se abrieran varias ventanas en vez de una sola con varias
        # pestanas.
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        context = await browser.new_context(user_agent=USER_AGENT, no_viewport=True)
        page = await context.new_page()
        await page.route("**/*", _forzar_codificacion_windows1252)
        await page.goto(URL_BUSQUEDA, timeout=60000)

        try:
            await page.click("button:has-text('Aceptar')", timeout=5000)
        except Exception:
            pass

        print(f"\nEsperando hasta {args.espera} segundos a que completes la busqueda...")
        await _esperar_resultados(page, args.espera)

        palabra_clave = args.palabra_clave or await _extraer_palabra_clave(page)
        if palabra_clave:
            print(f"Palabra clave detectada: {palabra_clave!r} (se guardara en cada proceso).")
        else:
            print("No se detecto ninguna palabra clave en el formulario; se guardara vacia.")

        importados, con_error, paginas = await _procesar_busqueda(
            page,
            context,
            palabra_clave=palabra_clave,
            lote_id=lote_id,
            sin_monto_adjudicado=args.sin_monto_adjudicado,
        )

        print(
            f"\nBusqueda completa: {importados} registro(s) insertado(s) en "
            f"{paginas} pagina(s) de resultados, {con_error} omitido(s) por "
            "error de validacion.\n"
            "Para buscar otro periodo o palabra clave, ejecuta el script de nuevo."
        )
        try:
            await browser.close()
        except PlaywrightError:
            # Ya estaba cerrado (el usuario cerro la ventana manualmente):
            # no hay nada que cerrar, no es un error a propagar.
            pass


if __name__ == "__main__":
    asyncio.run(main())
