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
from scripts.url_segura import url_portal_valida  # noqa: E402
from src import database  # noqa: E402

# Estados (ya normalizados via database._normalizar_para_busqueda: minusculas,
# sin tildes) para los que el proceso puede tener un Monto de Adjudicacion
# real que valga la pena ir a buscar -- confirmado contra los valores reales
# de la columna `estado` en la base (ver NOMBRES_ESTADO_COMPLETOS en
# app_ui.py para los mismos nombres completos). El resto de estados
# (Desierta, Suspendido, Calificacion de Participantes, etc.) nunca tienen
# fase contractual, asi que visitarlos es una peticion inutil al portal.
# "En Recepcion" y "Finalizado por mutuo acuerdo" se agregan porque tambien
# implican que el proceso ya paso por adjudicacion/contrato (recepcion de lo
# contratado o cierre anticipado por acuerdo entre las partes), asi que
# pueden tener Monto de Adjudicacion real igual que los tres estados
# originales.
_ESTADOS_ADJUDICABLES = (
    "adjudicado - registro",
    "ejecucion de contrato",
    "en recepcion",
    "finalizada",
    "finalizado por mutuo acuerdo",
)


def _es_estado_adjudicable(estado: str | None) -> bool:
    """True si `estado` (con o sin truncar -- ver el comentario sobre
    valores truncados en database.get_all_contrataciones) coincide con
    alguno de _ESTADOS_ADJUDICABLES por prefijo, en cualquiera de los dos
    sentidos: cubre tanto un `estado` truncado mas corto que el nombre
    completo (ej. "Adjudicado -") como, si el portal cambiara y guardara
    algo mas largo que el nombre completo, ese caso tambien."""
    if not estado:
        return False
    normalizado = database._normalizar_para_busqueda(estado).strip()
    return any(normalizado.startswith(p) or p.startswith(normalizado) for p in _ESTADOS_ADJUDICABLES)


def _procesos_pendientes(entidad: str | None) -> list[dict]:
    """Procesos con `url` conocida, sin `monto_adjudicado` todavia, y en un
    estado que realmente puede tener fase contractual (_es_estado_adjudicable)
    -- candidatos a completar. `get_all_contrataciones` no filtra por
    entidad, asi que ese filtro (si se pide `--entidad`) se aplica aca en
    Python, con el mismo criterio insensible a mayusculas/tildes que ya
    usa filtrar_por_entidad en app_ui.py."""
    todos = database.get_all_contrataciones()
    pendientes = [
        r
        for r in todos
        if url_portal_valida(r.get("url")) and r.get("monto_adjudicado") is None and _es_estado_adjudicable(r.get("estado"))
    ]
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
    # Keyear por `codigo` (UNIQUE, idx_contrataciones_codigo_unico), no por
    # `id`: _obtener_montos_adjudicados/_es_proceso_produccion_nacional
    # (scrape_portal.py) esperan la clave que reciben en `mapa_urls` como
    # el codigo real del proceso (para poder detectar el prefijo "VPN-");
    # con el `id` numerico ningun proceso VPN se reconoceria como tal.
    mapa_urls = {str(r["codigo"]).strip(): r["url"] for r in procesos}

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

        # _obtener_montos_adjudicados devuelve (montos, motivos); este
        # script solo completa monto_adjudicado -- persistir tambien
        # motivo_estado_raw ampliaria su alcance, asi que motivos se
        # descarta aca a proposito.
        montos, _motivos = await _obtener_montos_adjudicados(context, mapa_urls)

        await browser.close()

    actualizados, sin_adjudicar, con_error = 0, 0, 0
    for proceso in procesos:
        monto = montos.get(str(proceso["codigo"]).strip())
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
