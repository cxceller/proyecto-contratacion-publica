"""Segunda pasada de enriquecimiento sobre procesos "Desierta": ademas de
la version en lenguaje llano que ya genera scripts/explicar_estado_desierta.py
(RAG sobre el resumen corto de motivo_estado_raw), esta descarga el/los
PDF(s) del oficio real del SERCOP citado en el motivo, extrae su texto, y
le pide al mismo RAG (POST /explicar-desierta, con textos_oficios) una
version TECNICA adicional -- fundamentada en el oficio real, no solo en
el resumen. `explicacion_estado` queda con las dos versiones:

    [Técnica] <1-3 frases con articulos y terminos legales citados>

    [Para todos] <2-4 frases en lenguaje llano>

Idempotente: salta los procesos cuya explicacion_estado ya trae el
marcador MARCA_YA_PROCESADO ("[Técnica]"), salvo --forzar.

Verificado en vivo contra el proceso SIE-MIMG-2026-005 (oficio
SERCOP-DSP-2026-6563-OF):
- La pagina de detalle (`url`, ya capturada por scrape_portal.py) NO pide
  CAPTCHA -- ese solo esta en la busqueda, no aca -- pero SI tiene el
  banner obligatorio de politica de datos personales (mismo patron
  "button:has-text('Aceptar')" que ya usa scrape_portal.py).
- La pestaña "Archivos" carga por AJAX ("Cargando datos, Por favor
  espere..."): hay que esperar a que ese texto desaparezca, networkidle
  solo no alcanza.
- El oficio real vive bajo la seccion "Resolución de declaración de
  desierto" de esa pestaña. Localizarlo con
  `xpath=//*[contains(text(),'{oficio}')]/ancestor::tr[1]` (el ANCESTRO
  <tr> MAS CERCANO al nodo cuyo texto ES el numero de oficio) -- NO con
  `page.locator("tr", has_text=oficio).first" (ese matchea cualquier <tr>
  que CONTENGA el texto en cualquier parte de su subarbol; en esta tabla,
  el primero en orden de documento es una fila gigante que envuelve TODA
  la pestaña Archivos, y su primer "Descargar Archivo" es la Resolucion
  de Inicio -- un documento totalmente distinto, sin error visible).

A diferencia de scripts/explicar_estado_desierta.py (llamadas HTTP
directas al RAG, sin navegador), este script SI necesita Playwright con
Chromium (ya instalado, lo usa scrape_portal.py) + PyMuPDF para leer los
PDFs. Sigue la misma convencion que el resto de scripts/ batch de este
repo (actualizar_motivos_desierta.py, explicar_estado_desierta.py): lee
y escribe la base de datos SQLite DIRECTO via src/database, sin pasar
por la API HTTP (no necesita API_KEY).

`--headless`: por defecto la ventana de Chromium es VISIBLE (mismo
criterio que scrape_portal.py: nunca headless por defecto contra el
portal SERCOP). Pasar `--headless` solo si ya confirmaste, corriendo
antes en modo visible, que el/los proceso(s) que vas a correr no piden
CAPTCHA en la pagina de detalle.

Uso:
    .venv/Scripts/python.exe scripts/analizar_oficios_desierta.py             # todos los pendientes
    .venv/Scripts/python.exe scripts/analizar_oficios_desierta.py --limite 1  # prueba controlada
    .venv/Scripts/python.exe scripts/analizar_oficios_desierta.py --forzar    # reprocesa todos
"""
import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import fitz  # PyMuPDF
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.url_segura import url_portal_valida  # noqa: E402
from services.criterio_juridico import explicar_desierta as _explicar_desierta_rag  # noqa: E402
from src import database  # noqa: E402

DIRECTORIO_OFICIOS_TXT = Path(__file__).resolve().parent.parent / "data" / "oficios_txt"
PATRON_OFICIO = re.compile(r"SERCOP-[A-Z]{2,}-\d{4}-\d+-OF", re.IGNORECASE)
MARCA_YA_PROCESADO = "[Técnica]"
LARGO_MAXIMO_EXPLICACION = 2000  # limite actual de explicacion_estado (src/models.py)
PAUSA_ENTRE_PROCESOS_S = 1.5  # cortesia con el portal, mismo criterio que scrape_portal.py
TIMEOUT_NAVEGACION_MS = 60000
TIMEOUT_ARCHIVOS_MS = 20000


def extraer_oficios(motivo: str) -> list[str]:
    """Numeros de oficio citados en motivo_estado_raw, en el orden en que
    aparecen y sin duplicados -- un motivo puede citar mas de uno (ej. el
    oficio de observaciones y la respuesta), el mismo texto normalmente
    solo cita el que de verdad importa para la declaratoria de desierto."""
    vistos: dict[str, None] = {}
    for m in PATRON_OFICIO.findall(motivo or ""):
        vistos.setdefault(m.upper(), None)
    return list(vistos)


def _aceptar_banner_politica_datos(page: Page) -> None:
    """Banner obligatorio de politica de tratamiento de datos personales
    -- mismo patron ya usado en scrape_portal.py (ej. linea 451)."""
    try:
        page.click("button:has-text('Aceptar')", timeout=3000)
    except Exception:
        pass


def _extraer_texto_oficio(page: Page, url_proceso: str, oficio: str) -> str | None:
    """Abre el detalle del proceso, entra a "Archivos", ubica la fila del
    oficio (ver docstring del modulo sobre por que ancestor::tr[1] y no
    "tr que contiene el texto") y devuelve el texto extraido de su PDF
    (o None si no se encuentra el oficio, no hay enlace de descarga, la
    descarga falla, o el PDF no tiene capa de texto -- escaneado, sin
    OCR configurado en este script)."""
    if not url_portal_valida(url_proceso):
        return None  # url fuera de la lista blanca del portal: no se visita
    page.goto(url_proceso, wait_until="networkidle", timeout=TIMEOUT_NAVEGACION_MS)
    _aceptar_banner_politica_datos(page)

    try:
        page.get_by_text("Archivos", exact=True).first.click()
    except Exception:
        return None
    try:
        page.wait_for_selector("text=Cargando datos", state="hidden", timeout=TIMEOUT_ARCHIVOS_MS)
    except PlaywrightTimeoutError:
        pass  # puede que ya no estuviera visible -- seguir igual

    fila = page.locator(f"xpath=//*[contains(text(),'{oficio}')]/ancestor::tr[1]").first
    if fila.count() == 0:
        return None
    enlace = fila.locator("a[href*='bajarArchivo']").first
    if enlace.count() == 0:
        return None
    href = enlace.get_attribute("href")
    if not href:
        return None

    href_absoluto = urljoin(page.url, href)
    resp = page.request.get(href_absoluto, timeout=TIMEOUT_NAVEGACION_MS)
    if resp.status != 200:
        return None
    try:
        with fitz.open(stream=resp.body(), filetype="pdf") as doc:
            texto = "\n".join(pagina.get_text() for pagina in doc).strip()
    except Exception:
        return None
    if not texto:
        return None  # PDF escaneado sin capa de texto -- sin OCR en este script, se omite

    DIRECTORIO_OFICIOS_TXT.mkdir(parents=True, exist_ok=True)
    (DIRECTORIO_OFICIOS_TXT / f"{oficio}.txt").write_text(texto, encoding="utf-8")
    return texto


def _procesos_pendientes(limite: int | None, forzar: bool) -> list[dict]:
    candidatos = database.get_all_contrataciones(status="Desierta")
    pendientes = [
        r for r in candidatos
        if r.get("motivo_estado_raw") and (forzar or MARCA_YA_PROCESADO not in (r.get("explicacion_estado") or ""))
    ]
    return pendientes[:limite] if limite is not None else pendientes


def enriquecer(page: Page, limite: int | None = None, forzar: bool = False) -> dict[str, int]:
    """Devuelve el resumen por resultado. `page` ya viene con el
    navegador abierto (ver main) -- inyectable para tests con un doble
    que no toca la red real."""
    procesos = _procesos_pendientes(limite=limite, forzar=forzar)
    resumen = {"ok": 0, "sin_oficio": 0, "sin_url": 0, "oficio_no_hallado": 0, "sin_rag": 0, "error": 0}
    if not procesos:
        print("No hay procesos 'Desierta' pendientes de analizar oficio.")
        return resumen

    sufijo_limite = f" (limite: {limite})" if limite is not None else ""
    print(f"{len(procesos)} proceso(s) 'Desierta' pendiente(s) de analizar oficio{sufijo_limite}.")

    for proceso in procesos:
        codigo = proceso.get("codigo") or ""
        try:
            oficios = extraer_oficios(proceso["motivo_estado_raw"])
            if not oficios:
                print(f"  {codigo}: sin numero de oficio en el motivo.")
                resumen["sin_oficio"] += 1
                continue
            if not proceso.get("url"):
                print(f"  {codigo}: sin url de detalle.")
                resumen["sin_url"] += 1
                continue

            textos = []
            for oficio in oficios:
                texto = _extraer_texto_oficio(page, proceso["url"], oficio)
                if texto:
                    textos.append(texto)
                else:
                    print(f"  {codigo}: oficio {oficio} no encontrado/legible en 'Archivos'.")
            if not textos:
                resumen["oficio_no_hallado"] += 1
                continue

            resultado = _explicar_desierta_rag(
                motivo_raw=proceso["motivo_estado_raw"],
                objeto=proceso.get("objeto_proceso") or "",
                codigo=codigo,
                textos_oficios=textos,
            )
            explicacion = (resultado or {}).get("explicacion") or ""
            tecnica = (resultado or {}).get("explicacion_tecnica") or ""
            if not explicacion or not tecnica:
                print(f"  {codigo}: el RAG no devolvio ambas versiones.")
                resumen["sin_rag"] += 1
                continue

            combinado = f"[Técnica] {tecnica.strip()}\n\n[Para todos] {explicacion.strip()}"
            if len(combinado) > LARGO_MAXIMO_EXPLICACION:
                print(f"  {codigo}: combinado ({len(combinado)} caracteres) recortado a {LARGO_MAXIMO_EXPLICACION}.")
                combinado = combinado[:LARGO_MAXIMO_EXPLICACION]

            database.update_contratacion(proceso["id"], {"explicacion_estado": combinado})
            print(f"  {codigo}: OK ({len(combinado)} caracteres)")
            print("    " + combinado.replace("\n", "\n    "))
            resumen["ok"] += 1
        except Exception as exc:
            print(f"  {codigo}: ERROR {exc}", file=sys.stderr)
            resumen["error"] += 1

        time.sleep(PAUSA_ENTRE_PROCESOS_S)

    return resumen


def main(limite: int | None, forzar: bool, headless: bool) -> None:
    inicio = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            resumen = enriquecer(page, limite=limite, forzar=forzar)
        finally:
            browser.close()
    print(f"\nCompleto en {time.time() - inicio:.0f}s. Resumen: {resumen}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--limite", type=int, default=None,
        help="Maximo de procesos a analizar en esta corrida (por defecto, todos los pendientes).",
    )
    parser.add_argument("--forzar", action="store_true", help="Reprocesa incluso los que ya tienen '[Técnica]'.")
    parser.add_argument(
        "--headless", action="store_true",
        help="Corre Chromium sin ventana visible. Por defecto es visible (ver docstring del modulo).",
    )
    args = parser.parse_args()
    main(limite=args.limite, forzar=args.forzar, headless=args.headless)
