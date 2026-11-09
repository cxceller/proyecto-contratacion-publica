"""Completa retroactivamente el campo `motivo_estado_raw` de procesos en
estado "Desierta" que ya estan en la base de datos pero fueron importados
sin visitar su pagina de detalle (o antes del fix de render-timing/parseo
de _extraer_motivo_estado en scripts/scrape_portal.py), visitando de nuevo
la pagina general guardada en `url` -- sin volver a pasar por el buscador
del portal ni por el CAPTCHA: esa pagina de detalle es publica, se accede
por enlace directo (ver _extraer_motivo_estado, que este script reusa sin
duplicar logica). Por eso, igual que actualizar_montos_adjudicados.py, esta
ventana de Chromium corre headless -- no hace falta que el usuario resuelva
nada.

Por que existe APARTE de actualizar_montos_adjudicados.py: ese script solo
visita procesos en un estado adjudicable (_es_estado_adjudicable ahi
excluye Desierta a proposito -- nunca tiene fase contractual, asi que
buscarle un monto es una peticion inutil), asi que nunca captura
motivo_estado_raw para un proceso Desierta como efecto secundario. Este
script cubre exactamente ese hueco: visita SOLO la pagina general (nunca
"Resumen de Contrato" ni ninguna pagina de resultados/adjudicacion, que un
proceso Desierta no tiene) y lee "Estado del Proceso" -- mismo dato que
_obtener_montos_adjudicados captura gratis para los procesos que si visita.

Uso:
    .venv/Scripts/python.exe scripts/actualizar_motivos_desierta.py
    .venv/Scripts/python.exe scripts/actualizar_motivos_desierta.py --entidad "Municipalidad de Guayaquil"
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scrape_portal import (  # noqa: E402
    ESPERA_ENTRE_ADJUDICACIONES_S,
    MAX_PESTANAS_DETALLE_CONCURRENTES,
    TIMEOUT_ADJUDICACION_MS,
    TIMEOUT_MOTIVO_ESTADO_MS,
    USER_AGENT,
    _extraer_motivo_estado,
)
from scripts.url_segura import url_portal_valida  # noqa: E402
from src import database  # noqa: E402


def _procesos_pendientes(entidad: str | None) -> list[dict]:
    """Procesos "Desierta" con `url` conocida pero sin `motivo_estado_raw`
    todavia -- candidatos a completar. `get_all_contrataciones(status=...)`
    ya filtra por prefijo de estado en SQL (ver src/database.py); el resto
    se aplica en Python, mismo patron que _procesos_pendientes en
    actualizar_montos_adjudicados.py y en explicar_estado_desierta.py."""
    todos = database.get_all_contrataciones(status="Desierta")
    pendientes = [r for r in todos if url_portal_valida(r.get("url")) and not r.get("motivo_estado_raw")]
    if entidad:
        clave = entidad.strip().lower()
        pendientes = [r for r in pendientes if (r.get("entidad_contratante") or "").strip().lower() == clave]
    return pendientes


async def _obtener_motivos(context, mapa_urls: dict[str, str]) -> dict[str, str | None]:
    """Visita la pagina general de detalle de cada proceso y lee "Estado
    del Proceso" -- mismo pool acotado de pestañas concurrentes
    (MAX_PESTANAS_DETALLE_CONCURRENTES) que _obtener_montos_adjudicados en
    scrape_portal.py, pero sin ninguna navegacion adicional: un proceso
    Desierta no tiene "Resumen de Contrato" ni ninguna pagina de
    resultados/adjudicacion que buscar, asi que esta version es mas
    liviana a proposito (una sola pagina por proceso, no dos)."""
    if not mapa_urls:
        return {}

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
            except Exception as exc:
                print(f"  Motivo de {codigo}: no se pudo obtener ({exc}).")
                motivos[codigo] = None
            completados += 1
            if completados % 5 == 0 or completados == total:
                print(f"  Motivo del Estado: {completados}/{total} procesados...")
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
    return motivos


async def actualizar(entidad: str | None = None) -> tuple[int, int, int]:
    """Devuelve (actualizados, sin_motivo_todavia, con_error)."""
    procesos = _procesos_pendientes(entidad)
    if not procesos:
        print("No hay procesos 'Desierta' pendientes de actualizar (todos tienen motivo_estado_raw o no tienen url).")
        return 0, 0, 0

    print(f"{len(procesos)} proceso(s) 'Desierta' pendiente(s) de revisar.")
    # Keyear por `codigo` (UNIQUE), no por `id`: mismo motivo que
    # actualizar_montos_adjudicados.py, por consistencia con el resto del
    # pipeline, aunque aca no hay ruta VPN/Licitacion/Subasta/Consultoria
    # que dependa del prefijo.
    mapa_urls = {str(r["codigo"]).strip(): r["url"] for r in procesos}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)

        motivos = await _obtener_motivos(context, mapa_urls)

        await browser.close()

    actualizados, sin_motivo, con_error = 0, 0, 0
    for proceso in procesos:
        motivo = motivos.get(str(proceso["codigo"]).strip())
        if motivo is None:
            sin_motivo += 1
            continue
        ok = database.update_contratacion(proceso["id"], {"motivo_estado_raw": motivo})
        if ok:
            actualizados += 1
            print(f"  {proceso['codigo']}: {motivo[:80]}")
        else:
            con_error += 1

    return actualizados, sin_motivo, con_error


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--entidad",
        type=str,
        default=None,
        help="Solo actualiza procesos de esta Entidad Contratante exacta (por defecto, todos).",
    )
    args = parser.parse_args()

    inicio = time.time()
    actualizados, sin_motivo, con_error = asyncio.run(actualizar(entidad=args.entidad))
    print(
        f"\nCompleto en {time.time() - inicio:.0f}s: {actualizados} actualizado(s), "
        f"{sin_motivo} sin motivo todavia, {con_error} con error."
    )
