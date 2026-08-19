"""Completa retroactivamente el campo `monto_adjudicado` de procesos que
ya estan en la base de datos (importados antes de que este campo existiera,
o cuya extraccion fallo en su momento), visitando de nuevo la pagina de
detalle guardada en `url` -- sin volver a pasar por el buscador del portal
ni por el CAPTCHA: estas paginas de detalle son publicas, se acceden por
enlace directo (ver _obtener_montos_adjudicados/_ir_a_resumen_de_contrato
en scripts/scrape_portal.py, que este script reusa sin duplicar logica).
Por eso, a diferencia de scrape_portal.py, esta ventana de Chromium corre
headless -- no hace falta que el usuario resuelva nada.

Uso:
    .venv/Scripts/python.exe scripts/actualizar_montos_adjudicados.py
    .venv/Scripts/python.exe scripts/actualizar_montos_adjudicados.py --entidad "Municipalidad de Guayaquil"
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.scrape_portal import USER_AGENT, _obtener_montos_adjudicados  # noqa: E402
from src import database  # noqa: E402


def _procesos_pendientes(entidad: str | None) -> list[dict]:
    """Procesos con `url` conocida pero sin `monto_adjudicado` todavia --
    candidatos a completar. `get_all_contrataciones` no filtra por
    entidad, asi que ese filtro (si se pide `--entidad`) se aplica aca en
    Python, con el mismo criterio insensible a mayusculas/tildes que ya
    usa filtrar_por_entidad en app_ui.py."""
    todos = database.get_all_contrataciones()
    pendientes = [r for r in todos if r.get("url") and r.get("monto_adjudicado") is None]
    if entidad:
        clave = entidad.strip().lower()
        pendientes = [r for r in pendientes if (r.get("entidad_contratante") or "").strip().lower() == clave]
    return pendientes


async def actualizar(entidad: str | None = None) -> tuple[int, int, int]:
    """Devuelve (actualizados, sin_adjudicar_todavia, con_error)."""
    procesos = _procesos_pendientes(entidad)
    if not procesos:
        print("No hay procesos pendientes de actualizar (todos tienen monto_adjudicado o no tienen url).")
        return 0, 0, 0

    print(f"{len(procesos)} proceso(s) pendiente(s) de revisar.")
    mapa_urls = {str(r["id"]): r["url"] for r in procesos}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Sin _forzar_codificacion_windows1252 a proposito: ese parche es
        # solo para la pagina de resultados de busqueda -- estas paginas de
        # detalle sirven UTF-8 correctamente, forzar windows-1252 ahi
        # corrompe los acentos (ver el comentario en main() de
        # scrape_portal.py sobre la misma pestana). _obtener_montos_adjudicados
        # ahora abre su propio pool de pestanas concurrentes (ver esa
        # funcion en scrape_portal.py) a partir de un BrowserContext, no de
        # una sola pestana -- por eso aca se crea un context en vez de una
        # sola pagina.
        context = await browser.new_context(user_agent=USER_AGENT)

        montos = await _obtener_montos_adjudicados(context, mapa_urls)

        await browser.close()

    actualizados, sin_adjudicar, con_error = 0, 0, 0
    for proceso in procesos:
        monto = montos.get(str(proceso["id"]))
        if monto is None:
            sin_adjudicar += 1
            continue
        ok = database.update_contratacion(proceso["id"], {"monto_adjudicado": monto})
        if ok:
            actualizados += 1
            print(f"  {proceso['codigo']}: $ {monto:,.2f}")
        else:
            con_error += 1

    return actualizados, sin_adjudicar, con_error


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
    actualizados, sin_adjudicar, con_error = asyncio.run(actualizar(entidad=args.entidad))
    print(
        f"\nCompleto en {time.time() - inicio:.0f}s: {actualizados} actualizado(s), "
        f"{sin_adjudicar} sin adjudicar todavia, {con_error} con error."
    )
