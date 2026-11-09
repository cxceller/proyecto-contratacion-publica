"""Completa `monto_adjudicado` para procesos en estado "Adjudicada" o
"Finalizada" que todavia no lo tienen, leyendo el PDF "Resolucion de
Adjudicacion" del portal SERCOP -- caso que scripts/actualizar_montos_adjudicados.py
NO cubre: ese script lee el "Monto de Adjudicacion" de la pagina HTML
"Resumen de Contrato", que solo existe una vez que el contrato ya se
registro formalmente; un proceso "Adjudicada" (adjudicado, contrato
todavia sin registrar) no tiene esa pagina todavia (confirmado navegando
en vivo los 5 procesos "Adjudicada" de Municipalidad de Guayaquil: ninguno
tiene el enlace "Resumen de Contrato"), pero SI tiene ya la Resolucion de
Adjudicacion publicada (enlace "Ver Resultados de Publicacion" en la
pagina general del proceso), que declara el monto en su punto resolutivo
("ADJUDICAR el contrato... por un monto de USD$ ... (MONTO EN LETRAS)").

Idempotente: solo selecciona filas con `monto_adjudicado` vacio/0/None
(ver `_procesos_pendientes`) -- correr dos veces no vuelve a tocar una fila
ya completada. Dry-run por defecto: sin `--apply`, solo imprime lo que
haria y genera los CSV de reporte, sin escribir en la base.

Uso:
    .venv/Scripts/python.exe scripts/completar_montos_resolucion_pdf.py
    .venv/Scripts/python.exe scripts/completar_montos_resolucion_pdf.py --apply
    .venv/Scripts/python.exe scripts/completar_montos_resolucion_pdf.py --entidad "Municipalidad de Guayaquil" --apply
"""
import argparse
import asyncio
import csv
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # PyMuPDF -- ya en requirements.txt (usado por otros scripts), evita sumar pdfplumber
from playwright.async_api import BrowserContext, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from scripts.scrape_portal import USER_AGENT  # noqa: E402
from scripts.url_segura import url_portal_valida  # noqa: E402
from src import database  # noqa: E402

RAIZ_REPO = Path(__file__).resolve().parent.parent
RUTA_EXTRAIDOS = RAIZ_REPO / "montos_extraidos.csv"
RUTA_FALLIDOS = RAIZ_REPO / "montos_fallidos.csv"

# Solo estos dos -- ver el docstring del modulo sobre por que
# actualizar_montos_adjudicados.py no los cubre.
_ESTADOS_OBJETIVO = {"adjudicada", "finalizada"}

_INTENTOS_MAX = 3
_PAUSA_ENTRE_PROCESOS_S = 3
_UMBRAL_TEXTO_ESCANEADO = 200  # menos caracteres que esto en todo el PDF => probablemente escaneado

# (?:USD\$|USD|US\$|\$)?: "USD\$" DEBE ir antes que "USD" en la alternancia
# -- el portal escribe "USD$" pegado (sin espacio) en sus resoluciones
# reales (confirmado en PE-MIMG-2025-1); con "USD" primero, esa alternativa
# matchea y deja un "$" suelto sin consumir, y el resto del patron falla.
# [\d.,´'']+: ademas de "." y "," (miles/decimales), el portal usa "´"
# (acento agudo) o una comilla tipografica como separador de millones
# (ej. "2´390.123,53", confirmado en el mismo documento real) -- sin
# incluirlos aca, el grupo capturado corta en el primer digito antes del
# separador.
PATRONES_MONTO = [
    r"por\s+un\s+monto\s+de\s*(?:USD\$|USD|US\$|\$)?\s*([\d.,´'’]+)",
    r"por\s+la\s+cantidad\s+de\s*(?:USD\$|USD|US\$|\$)?\s*([\d.,´'’]+)",
    r"por\s+un\s+valor\s+de\s*(?:USD\$|USD|US\$|\$)?\s*([\d.,´'’]+)",
]

_PATRON_MONTO_LETRAS = re.compile(r"\(([^()]*?D[OÓ]LARES[^()]*)\)", re.IGNORECASE)
_PATRON_CENTAVOS = re.compile(r"CON\s+(\d{1,2})\s*/\s*100", re.IGNORECASE)

_UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiun": 21, "veintiuno": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
_DECENAS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}
_CENTENAS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
    "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
    "setecientos": 700, "ochocientos": 800, "novecientos": 900,
}


def normaliza_monto(s: str) -> float:
    """Normaliza un monto capturado por PATRONES_MONTO a float, tolerando
    formatos EC/US mezclados (el ultimo separador que aparece en el string
    es el decimal -- mismo criterio para "." y ","). Antes de eso, quita
    "´"/"'"/"'" (separador de millones que a veces usa el portal ademas de
    "." para miles, ver PATRONES_MONTO): no aportan informacion de donde
    esta el decimal (eso siempre lo da la coma o el ultimo punto), asi que
    se eliminan sin mas."""
    s = s.strip().rstrip(".,")
    s = s.replace("´", "").replace("'", "").replace("’", "")
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        mil = "," if dec == "." else "."
        s = s.replace(mil, "").replace(dec, ".")
    elif "," in s:  # solo coma
        ent, _, frac = s.rpartition(",")
        s = f"{ent.replace(',', '')}.{frac}" if len(frac) == 2 else s.replace(",", "")
    else:  # solo punto (o nada)
        ent, _, frac = s.rpartition(".")
        s = f"{ent.replace('.', '')}.{frac}" if len(frac) == 2 else s.replace(".", "")
    return float(s)


def _sin_tildes(texto: str) -> str:
    sin = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin if not unicodedata.combining(c))


def texto_a_numero(texto: str) -> int | None:
    """Convierte un numero ENTERO escrito en palabras en espanol (el
    "monto en letras" de las resoluciones SERCOP, ej. "DOS MILLONES
    TRESCIENTOS NOVENTA MIL CIENTO VEINTE Y TRES") a int. Soporta "VEINTE
    Y TRES" con la "Y" separada (asi lo escriben estos documentos, no
    "VEINTITRES" junto). Devuelve None si no reconocio ninguna palabra
    numerica -- nunca lanza, para que un formato inesperado quede como "no
    se pudo validar" (ver validar_monto) en vez de romper el script."""
    palabras = re.findall(r"[a-zñ]+", _sin_tildes(texto.lower()))
    if not palabras:
        return None

    total = 0
    parcial = 0
    algo_reconocido = False
    for palabra in palabras:
        if palabra == "y":
            continue
        if palabra in _CENTENAS:
            parcial += _CENTENAS[palabra]
            algo_reconocido = True
        elif palabra in _DECENAS:
            parcial += _DECENAS[palabra]
            algo_reconocido = True
        elif palabra in _UNIDADES:
            parcial += _UNIDADES[palabra]
            algo_reconocido = True
        elif palabra == "mil":
            parcial = parcial or 1
            total += parcial * 1_000
            parcial = 0
            algo_reconocido = True
        elif palabra in ("millon", "millones"):
            parcial = parcial or 1
            total += parcial * 1_000_000
            parcial = 0
            algo_reconocido = True
        # palabras no numericas ("de", "dolares", etc.) se ignoran.
    total += parcial
    return total if algo_reconocido else None


def extraer_monto_en_letras(texto_cercano: str) -> float | None:
    """Busca un bloque entre parentesis que mencione "DOLARES" cerca del
    monto en digitos (ej. "(DOS MILLONES ... CON 53/100 DOLARES DE LOS
    ESTADOS UNIDOS DE AMERICA)") y lo convierte a float (parte entera via
    texto_a_numero + centavos de "CON XX/100"). None si no hay un bloque
    asi o no se pudo interpretar."""
    m = _PATRON_MONTO_LETRAS.search(texto_cercano)
    if m is None:
        return None
    bloque = m.group(1)
    m_centavos = _PATRON_CENTAVOS.search(bloque)
    parte_entera_texto = bloque[: m_centavos.start()] if m_centavos else bloque
    entero = texto_a_numero(parte_entera_texto)
    if entero is None:
        return None
    centavos = int(m_centavos.group(1)) if m_centavos else 0
    return entero + centavos / 100


def validar_monto(monto_digitos: float, texto_cercano: str) -> bool:
    """True si el monto en letras (cuando aparece y se pudo interpretar)
    coincide con `monto_digitos` (tolerancia de 1 centavo, por redondeo de
    float). Si no hay monto en letras reconocible ahi, no hay con que
    contrastar -- se deja pasar (True): lo que se rechaza es un monto en
    letras que SI se pudo leer pero da un numero distinto, no la ausencia
    de uno."""
    monto_letras = extraer_monto_en_letras(texto_cercano)
    if monto_letras is None:
        return True
    return abs(monto_letras - monto_digitos) < 0.01


def extraer_monto_de_texto(texto: str) -> tuple[float, str] | None:
    """Prueba PATRONES_MONTO en orden; de la PRIMERA plantilla que matchee
    en algun lado, toma la ULTIMA coincidencia del documento completo (el
    parrafo resolutivo final -- "RESUELVE: ... ADJUDICAR ..." -- va cerca
    del final del PDF, confirmado en un caso real: pagina 46 de 46; un
    parrafo anterior de "recomendacion" de la Comision Tecnica puede traer
    el mismo texto antes en el documento). Devuelve (monto, fragmento) con
    fragmento = los 400 caracteres siguientes al monto, para validar_monto.
    None si ninguna plantilla matchea en ningun lado."""
    for patron in PATRONES_MONTO:
        coincidencias = list(re.finditer(patron, texto, re.IGNORECASE))
        if not coincidencias:
            continue
        m = coincidencias[-1]
        try:
            monto = normaliza_monto(m.group(1))
        except ValueError:
            continue
        fragmento = texto[m.end() : m.end() + 400]
        return monto, fragmento
    return None


def _es_estado_objetivo(estado: str | None) -> bool:
    return bool(estado) and database._normalizar_para_busqueda(estado).strip() in _ESTADOS_OBJETIVO


def _procesos_pendientes(entidad: str | None) -> list[dict[str, Any]]:
    """Filas en _ESTADOS_OBJETIVO, con `url`, y `monto_adjudicado` vacio/0/
    None -- candidatas a completar via PDF de resolucion."""
    todos = database.get_all_contrataciones()
    pendientes = [
        r for r in todos if r.get("url") and not r.get("monto_adjudicado") and _es_estado_objetivo(r.get("estado"))
    ]
    if entidad:
        clave = entidad.strip().lower()
        pendientes = [r for r in pendientes if (r.get("entidad_contratante") or "").strip().lower() == clave]
    return pendientes


async def _con_reintentos(descripcion: str, corrutina_factory):
    """Reintenta `corrutina_factory()` hasta _INTENTOS_MAX veces con
    backoff exponencial (2s, 4s, 8s...) antes de propagar la ultima
    excepcion -- para tolerar caidas de red puntuales contra un portal
    publico sin descartar el proceso a la primera."""
    for intento in range(1, _INTENTOS_MAX + 1):
        try:
            return await corrutina_factory()
        except Exception:
            if intento == _INTENTOS_MAX:
                raise
            espera = 2**intento
            print(f"    intento {intento}/{_INTENTOS_MAX} de {descripcion} fallo, reintentando en {espera}s...")
            await asyncio.sleep(espera)


async def _descargar_pdf_resolucion(context: BrowserContext, pagina: Page, url: str) -> tuple[bytes | None, str | None, str | None]:
    """Navega la pagina de detalle -> "Ver Resultados de Publicacion" ->
    ubica el enlace cuyo texto contiene "resoluci" + "adjudica" (sin
    distinguir mayusculas/tildes) -> descarga sus bytes. Devuelve (bytes,
    url_pdf, motivo_fallo); exactamente uno de (bytes, motivo_fallo) es
    None. Nunca lanza para fallos esperados (enlace ausente): los reporta
    como motivo, para que _procesar_uno los escriba en montos_fallidos.csv
    en vez de abortar el resto del lote."""
    if not url_portal_valida(url):
        return None, None, "url fuera de la lista blanca del portal (no se visita)"
    await pagina.goto(url, timeout=30000)
    try:
        await pagina.click("button:has-text('Aceptar')", timeout=3000)
    except Exception:
        pass

    enlace_resultados = pagina.locator("text=/resultados de publicaci/i").first
    try:
        await enlace_resultados.click(timeout=10000)
        await pagina.wait_for_load_state("load", timeout=15000)
    except PlaywrightTimeoutError:
        return None, None, "sin_enlace_resultados_publicacion"

    textos = await pagina.locator("a").all_text_contents()
    hrefs = await pagina.locator("a").evaluate_all("els => els.map(e => e.href)")
    pdf_url = None
    for texto, href in zip(textos, hrefs, strict=True):
        t = _sin_tildes(texto).upper()
        if "RESOLUCI" in t and "ADJUDICA" in t:
            pdf_url = href
            break

    if pdf_url is None:
        return None, None, "sin_pdf_resolucion_adjudicacion"

    try:
        resp = await context.request.get(pdf_url, timeout=120000)
    except Exception:
        return None, None, "error_descarga_pdf"
    if not resp.ok:
        return None, None, f"error_descarga_pdf_http_{resp.status}"

    return await resp.body(), pdf_url, None


def _extraer_texto_pdf(contenido: bytes) -> str:
    doc = fitz.open(stream=contenido, filetype="pdf")
    try:
        return "".join(pagina.get_text() for pagina in doc)
    finally:
        doc.close()


async def _procesar_uno(context: BrowserContext, pagina: Page, proceso: dict[str, Any]) -> dict[str, Any]:
    """Devuelve un dict con el resultado de UN proceso: siempre trae
    `codigo`; si tuvo exito, `monto` y `pdf_url`; si no, `motivo` (una de
    las razones de montos_fallidos.csv: sin_enlace_resultados_publicacion,
    sin_pdf_resolucion_adjudicacion, error_descarga_pdf(_http_NNN),
    pdf_escaneado_sin_ocr, sin_monto_en_texto, revisar_manual_letras_no_
    coinciden)."""
    codigo = proceso["codigo"]
    contenido, pdf_url, motivo = await _con_reintentos(
        f"descarga de {codigo}", lambda: _descargar_pdf_resolucion(context, pagina, proceso["url"])
    )
    if contenido is None:
        return {"codigo": codigo, "motivo": motivo}

    texto = _extraer_texto_pdf(contenido)
    if len(texto.strip()) < _UMBRAL_TEXTO_ESCANEADO:
        # Posible PDF escaneado (sin capa de texto): este script no hace
        # OCR (pytesseract/pdf2image necesitan ademas un binario de
        # Tesseract instalado en el sistema, una dependencia nueva y
        # pesada que ninguno de los 5 PDF de prueba necesito) -- se
        # reporta para revision manual en vez de fingir un resultado.
        return {"codigo": codigo, "motivo": "pdf_escaneado_sin_ocr", "pdf_url": pdf_url}

    encontrado = extraer_monto_de_texto(texto)
    if encontrado is None:
        return {"codigo": codigo, "motivo": "sin_monto_en_texto", "pdf_url": pdf_url}

    monto, fragmento = encontrado
    if not validar_monto(monto, fragmento):
        return {"codigo": codigo, "motivo": "revisar_manual_letras_no_coinciden", "pdf_url": pdf_url}

    return {"codigo": codigo, "monto": monto, "pdf_url": pdf_url}


async def completar(entidad: str | None, aplicar: bool) -> tuple[list[dict], list[dict]]:
    """Devuelve (extraidos, fallidos) -- una entrada por proceso procesado
    en cada lista, mutuamente excluyentes. Con `aplicar=True`, ademas
    escribe monto_adjudicado (+ monto_origen/monto_pdf_url) de cada
    extraido exitoso en la base via database.update_contratacion."""
    procesos = _procesos_pendientes(entidad)
    if not procesos:
        print("No hay procesos pendientes (todos tienen monto_adjudicado, o ninguno esta en Adjudicada/Finalizada).")
        return [], []

    print(f"{len(procesos)} proceso(s) objetivo (estado Adjudicada/Finalizada, sin monto_adjudicado).")

    extraidos: list[dict] = []
    fallidos: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        pagina = await context.new_page()

        for i, proceso in enumerate(procesos):
            codigo = proceso["codigo"]
            print(f"  [{i + 1}/{len(procesos)}] {codigo}...")
            try:
                resultado = await _procesar_uno(context, pagina, proceso)
            except Exception as e:
                resultado = {"codigo": codigo, "motivo": f"error_inesperado:{e!r}"}

            if "monto" in resultado:
                print(f"      OK: $ {resultado['monto']:,.2f}")
                extraidos.append({**resultado, "id": proceso["id"]})
            else:
                print(f"      FALLO: {resultado['motivo']}")
                fallidos.append(resultado)

            if i < len(procesos) - 1:
                await asyncio.sleep(_PAUSA_ENTRE_PROCESOS_S)

        await browser.close()

    if aplicar:
        for item in extraidos:
            database.update_contratacion(
                item["id"],
                {
                    "monto_adjudicado": item["monto"],
                    "monto_origen": "resolucion_pdf",
                    "monto_pdf_url": item["pdf_url"],
                },
            )

    _escribir_csv_extraidos(extraidos)
    _escribir_csv_fallidos(fallidos)
    return extraidos, fallidos


def _escribir_csv_extraidos(extraidos: list[dict]) -> None:
    with open(RUTA_EXTRAIDOS, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["codigo", "monto", "url"])
        for item in extraidos:
            writer.writerow([item["codigo"], f"{item['monto']:.2f}", item["pdf_url"]])


def _escribir_csv_fallidos(fallidos: list[dict]) -> None:
    with open(RUTA_FALLIDOS, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["codigo", "motivo"])
        for item in fallidos:
            writer.writerow([item["codigo"], item["motivo"]])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--entidad", type=str, default=None,
        help="Solo procesa procesos de esta Entidad Contratante exacta (por defecto, todos).",
    )
    parser.add_argument(
        "--apply", dest="aplicar", action="store_true",
        help="Escribe los montos encontrados en la base. Sin esta bandera, solo dry-run (imprime/loguea y genera los CSV, sin tocar la base).",
    )
    args = parser.parse_args()

    if not args.aplicar:
        print("=== DRY-RUN (sin --apply): no se escribe nada en la base, solo se genera el reporte ===\n")

    inicio = time.time()
    extraidos, fallidos = asyncio.run(completar(entidad=args.entidad, aplicar=args.aplicar))
    print(
        f"\nCompleto en {time.time() - inicio:.0f}s: {len(extraidos) + len(fallidos)} objetivo(s), "
        f"{len(extraidos)} resuelto(s), {len(fallidos)} fallido(s)."
    )
    print(f"Reporte: {RUTA_EXTRAIDOS.name}, {RUTA_FALLIDOS.name}")
