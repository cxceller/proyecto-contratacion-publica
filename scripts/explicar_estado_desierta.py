"""Genera, via la API de Claude, una explicacion en lenguaje simple de por
que un proceso de contratacion quedo "Desierta", a partir del texto crudo
que scrape_portal.py ya captura en `motivo_estado_raw` (columna "Estado del
Proceso" de la pagina general de detalle -- ver Cambio 10 /
_extraer_motivo_estado en scripts/scrape_portal.py).

Se corre como paso APARTE, no dentro del scraper: scrape_portal.py ya hace
suficientes peticiones de red por proceso (visita a la pagina de detalle +
Resumen de Contrato/Resultados PN) y agregarle una llamada a un LLM por
cada uno encima de eso sumaria otra dependencia (API key, rate limits,
latencia) a un script que ya es la fase mas lenta de la importacion.
Reusa el mismo patron de llamada a la API de Claude que
scripts/importador_parametros.py (manejo de API key via .env, timeout,
errores transitorios vs. permanentes) en vez de duplicarlo.

Uso:
    .venv/Scripts/python.exe scripts/explicar_estado_desierta.py
"""
import argparse
import sys
import time
from pathlib import Path

import anthropic
import truststore
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import database  # noqa: E402

# Igual que scripts/importador_parametros.py: sin esto, httpx (usado por el
# SDK de anthropic) valida certificados TLS contra el bundle fijo de
# certifi, que no incluye la CA raiz interna de proxies/firewalls con
# inspeccion TLS (comun en redes institucionales) -- inject_into_ssl() hace
# que valide contra el almacen de certificados del sistema operativo en su
# lugar. Se llama una sola vez, al importar este modulo.
truststore.inject_into_ssl()

# A diferencia de app_ui.py (que carga .env al arrancar la app completa),
# este es un script standalone pensado para correr por linea de comandos
# aparte -- sin este load_dotenv() propio, ANTHROPIC_API_KEY del .env del
# repo no llegaria al proceso.
load_dotenv()

MODELO_LLM_POR_DEFECTO = "claude-haiku-4-5"
TIMEOUT_LLM_S = 30.0
MAX_TOKENS_EXPLICACION = 300

PROMPT_SISTEMA = (
    "Eres un asistente que explica procesos de contratacion publica del Ecuador a "
    "personas sin conocimiento tecnico ni legal. Recibes el texto crudo que el portal "
    "SERCOP muestra como motivo de un proceso declarado 'Desierto' (Razon, Fecha y "
    "Justificacion legal) y debes explicarlo en 1 o 2 frases simples, en español, sin "
    "jerga legal ni citar artículos de ley textualmente. Usa exclusivamente la "
    "informacion del texto que se te da: no inventes, no resumas de mas, ni agregues "
    "razones que no esten ahi."
)


class ErrorLLMExplicacionEstado(Exception):
    """Error transitorio de la llamada al LLM (red, timeout, respuesta no
    interpretable) para UN proceso puntual -- no interrumpe el resto del
    lote, ver `enriquecer`, mismo criterio de tolerancia a fallos que ya
    usa scrape_portal.py para procesos individuales."""


def _explicar_motivo(motivo_estado_raw: str, cliente_llm, modelo: str) -> str:
    try:
        respuesta = cliente_llm.with_options(timeout=TIMEOUT_LLM_S).messages.create(
            model=modelo,
            max_tokens=MAX_TOKENS_EXPLICACION,
            system=PROMPT_SISTEMA,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Texto original del portal SERCOP sobre por que este proceso "
                        f"fue declarado 'Desierto':\n\n{motivo_estado_raw}"
                    ),
                }
            ],
        )
    except anthropic.APIError as exc:
        raise ErrorLLMExplicacionEstado(f"no se pudo generar la explicacion ({exc})") from exc

    texto = next((b.text for b in respuesta.content if b.type == "text"), None)
    if not texto or not texto.strip():
        raise ErrorLLMExplicacionEstado("la IA no devolvio una respuesta interpretable")
    return texto.strip()


def _procesos_pendientes() -> list[dict]:
    """Procesos "Desierta" con `motivo_estado_raw` ya capturado (ver
    Cambio 10) pero todavia sin `explicacion_estado` -- para no volver a
    gastar una llamada al LLM en procesos ya explicados. `status="Desierta"`
    en get_all_contrataciones ya filtra por prefijo de estado en SQL (ver
    src/database.py); el resto del filtro se aplica en Python, mismo
    patron que `_procesos_pendientes` en
    scripts/actualizar_montos_adjudicados.py."""
    candidatos = database.get_all_contrataciones(status="Desierta")
    return [r for r in candidatos if r.get("motivo_estado_raw") and not r.get("explicacion_estado")]


def enriquecer(cliente_llm=None, modelo: str = MODELO_LLM_POR_DEFECTO) -> tuple[int, int]:
    """Devuelve (explicados, con_error)."""
    if cliente_llm is None:
        cliente_llm = anthropic.Anthropic()

    procesos = _procesos_pendientes()
    if not procesos:
        print("No hay procesos 'Desierta' pendientes de explicar.")
        return 0, 0

    print(f"{len(procesos)} proceso(s) 'Desierta' pendiente(s) de explicar.")
    explicados, con_error = 0, 0
    for proceso in procesos:
        try:
            explicacion = _explicar_motivo(proceso["motivo_estado_raw"], cliente_llm, modelo)
        except ErrorLLMExplicacionEstado as exc:
            print(f"  {proceso['codigo']}: {exc}.")
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
