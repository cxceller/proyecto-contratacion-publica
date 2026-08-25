"""Genera, via el RAG de Contratacion Publica (Proyecto_02, ver
services/criterio_juridico.py), una explicacion en lenguaje simple de por
que un proceso de contratacion quedo "Desierta", a partir del texto crudo
que scrape_portal.py ya captura en `motivo_estado_raw` (columna "Estado del
Proceso" de la pagina general de detalle -- ver Cambio 10 /
_extraer_motivo_estado en scripts/scrape_portal.py).

Se corre como paso APARTE, no dentro del scraper: scrape_portal.py ya hace
suficientes peticiones de red por proceso (visita a la pagina de detalle +
Resumen de Contrato/Resultados PN) y agregarle una llamada de red por cada
uno encima de eso sumaria otra dependencia (RAG corriendo, latencia) a un
script que ya es la fase mas lenta de la importacion.

Antes esto llamaba a la API de Claude directamente, sin ningun retrieval de
normativa real -- por eso el prompt anterior tenia una regla explicita de
"no inventes articulos de ley": no tenia como fundamentar una cita. Ahora
el RAG (Proyecto_02) tiene la LOSNCP y su Reglamento indexados, asi que
puede citar el articulo real (ver POST /explicar-desierta ahi) cuando el
motivo lo permite.

Requiere que el RAG este corriendo (ver RAG_CONTRATACION_URL en .env,
por defecto http://localhost:8001) -- si no responde, explicar_desierta()
devuelve None y el proceso se cuenta como error sin interrumpir el lote.

Uso:
    .venv/Scripts/python.exe scripts/explicar_estado_desierta.py
"""
import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.criterio_juridico import explicar_desierta as _explicar_desierta_rag  # noqa: E402
from src import database  # noqa: E402

# Script standalone pensado para correr por linea de comandos aparte (a
# diferencia de app_ui.py, que carga .env al arrancar la app completa) --
# sin este load_dotenv() propio, RAG_CONTRATACION_URL/_TIMEOUT_S del .env
# del repo no llegarian al proceso antes de que services/criterio_juridico.py
# los lea (se leen una sola vez, al importar ese modulo).
load_dotenv()


def _procesos_pendientes() -> list[dict]:
    """Procesos "Desierta" con `motivo_estado_raw` ya capturado (ver
    Cambio 10) pero todavia sin `explicacion_estado` -- para no volver a
    gastar una llamada al RAG en procesos ya explicados. `status="Desierta"`
    en get_all_contrataciones ya filtra por prefijo de estado en SQL (ver
    src/database.py); el resto del filtro se aplica en Python, mismo
    patron que `_procesos_pendientes` en
    scripts/actualizar_montos_adjudicados.py."""
    candidatos = database.get_all_contrataciones(status="Desierta")
    return [r for r in candidatos if r.get("motivo_estado_raw") and not r.get("explicacion_estado")]


def enriquecer(explicar_fn=_explicar_desierta_rag) -> tuple[int, int]:
    """Devuelve (explicados, con_error). `explicar_fn` es inyectable para
    tests (ver tests/test_explicar_estado_desierta.py) -- mismo patron que
    antes usaba `cliente_llm`, ahora sobre la funcion que llama al RAG en
    vez de un cliente Anthropic."""
    procesos = _procesos_pendientes()
    if not procesos:
        print("No hay procesos 'Desierta' pendientes de explicar.")
        return 0, 0

    print(f"{len(procesos)} proceso(s) 'Desierta' pendiente(s) de explicar.")
    explicados, con_error = 0, 0
    for proceso in procesos:
        resultado = explicar_fn(
            motivo_raw=proceso["motivo_estado_raw"],
            objeto=proceso.get("objeto_proceso") or "",
            codigo=proceso.get("codigo") or "",
        )
        explicacion = (resultado or {}).get("explicacion") or ""
        if not explicacion:
            print(f"  {proceso['codigo']}: el RAG no devolvio una explicacion.")
            con_error += 1
            continue
        database.update_contratacion(proceso["id"], {"explicacion_estado": explicacion})
        print(f"  {proceso['codigo']}: {explicacion}")
        explicados += 1

    return explicados, con_error


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()

    inicio = time.time()
    explicados, con_error = enriquecer()
    print(f"\nCompleto en {time.time() - inicio:.0f}s: {explicados} explicado(s), {con_error} con error.")
