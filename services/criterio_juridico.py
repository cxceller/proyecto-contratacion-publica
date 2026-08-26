"""Cliente hacia el RAG de Contratacion Publica (Proyecto_02, tema_4/Proyecto_02
en este mismo equipo): pide la explicacion en lenguaje sencillo de por que un
proceso quedo "Desierta", fundamentada en la LOSNCP/Reglamento que ese RAG ya
tiene indexados -- reemplaza la llamada directa a Claude que antes hacia
scripts/explicar_estado_desierta.py (sin retrieval, por eso nunca podia citar
un articulo real).

Dos servicios FastAPI conviven en desarrollo, por eso puertos distintos:
SERCOP API en 8000, este RAG en 8001 (RAG_CONTRATACION_URL)."""
import os

import requests

RAG_BASE_URL = os.getenv("RAG_CONTRATACION_URL", "http://localhost:8001")
RAG_TIMEOUT_S = float(os.getenv("RAG_CONTRATACION_TIMEOUT_S", "60"))


def explicar_desierta(
    motivo_raw: str, objeto: str = "", codigo: str = "", textos_oficios: list[str] | None = None
) -> dict | None:
    """POST /explicar-desierta. Devuelve {'explicacion', 'explicacion_tecnica',
    'causal_legal', 'fuentes'} o None si el RAG no esta disponible / no
    respondio 200 / el motivo esta vacio. No lanza excepcion: ante
    cualquier fallo devuelve None para que el lote de
    scripts/explicar_estado_desierta.py (o scripts/analizar_oficios_desierta.py)
    continue con el resto de procesos en vez de interrumpirse.

    `textos_oficios` (opcional, scripts/analizar_oficios_desierta.py): texto
    completo de el/los oficio(s) del SERCOP ya descargados y extraidos --
    el RAG lo usa como fuente primaria de 'explicacion_tecnica'. Sin este
    argumento, el llamado se comporta igual que antes (solo 'explicacion')."""
    if not (motivo_raw or "").strip():
        return None
    payload = {"motivo_raw": motivo_raw, "objeto_proceso": objeto, "codigo": codigo}
    if textos_oficios:
        payload["textos_oficios"] = textos_oficios
    try:
        resp = requests.post(f"{RAG_BASE_URL}/explicar-desierta", json=payload, timeout=RAG_TIMEOUT_S)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()
