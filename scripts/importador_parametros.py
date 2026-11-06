"""Importador robusto de "Parámetros técnicos" para Especificaciones Técnicas
por Ítem: convierte un archivo subido (.xlsx/.csv/.txt) en una lista de
{"nombre": ..., "valor": ...}, sin importar cómo esté estructurado el
archivo de origen.

Camino híbrido:
1. Parser determinístico rápido (`_intentar_camino_rapido`), sin costo de
   LLM: funciona cuando el archivo ya es 2 columnas limpias (con o sin
   filas de continuación sin nombre, que se fusionan al valor anterior --
   patrón ya usado en archivos reales de este flujo). Si el archivo tiene
   más de 2 columnas pobladas en alguna fila (celdas combinadas de Excel
   colapsadas en una "columna de categoría"), o nunca hay una fila con 2
   celdas pobladas, o se pierde más del 30% de las filas no vacías sin
   poder mapearlas, se escala al camino 2.
2. Normalizador vía API de Claude (`_normalizar_con_llm`): recibe la
   matriz cruda completa (todas las filas/columnas, celdas vacías
   incluidas) y devuelve pares Parámetro/Valor con salida estructurada
   (JSON Schema estricto vía `output_config.format`), más la lista de
   filas descartadas con motivo -- nunca se pierde contenido en silencio.

En ambos caminos se calcula una advertencia de integridad (comparación de
caracteres entre el archivo original y el resultado) para detectar
alucinación o pérdida de contenido, sin bloquear el flujo.

Nada de esto guarda en base de datos -- el resultado se anexa a las filas
editables del formulario, igual que si el usuario las hubiera escrito a
mano (ver app_ui.py)."""

import anthropic
import truststore

from scripts.lectura_archivos_tabulares import leer_matriz_cruda
from scripts.llm_seguro import (
    RespaldoIADesactivado,
    RespuestaLLMParametros,
    llm_fallback_habilitado,
    preparar_matriz_para_llm,
    validar_respuesta_llm,
)

# httpx (usado por el SDK de anthropic) valida certificados TLS contra el
# bundle de certifi -- una lista fija de CAs publicas que no incluye la CA
# raiz interna que agregan los proxies/firewalls con inspeccion TLS de redes
# corporativas o institucionales (comun en la red de una municipalidad).
# Windows SI confia en esa CA (esta en su almacen de certificados, por eso
# curl/Schannel funciona), pero certifi no. inject_into_ssl() hace que el
# modulo ssl de Python valide contra el almacen de certificados del sistema
# operativo en vez del bundle de certifi, evitando el "Connection error"
# (en realidad un CERTIFICATE_VERIFY_FAILED envuelto por el SDK) al llamar
# a la API de Claude desde esta red. Se llama una sola vez, al importar este
# modulo, antes de que se cree ningun cliente HTTPS.
truststore.inject_into_ssl()

UMBRAL_PROPORCION_UTIL_CAMINO_RAPIDO = 0.7
UMBRAL_ADVERTENCIA_INTEGRIDAD = 0.15
TAMANO_BLOQUE_LLM = 150
MODELO_LLM_POR_DEFECTO = "claude-haiku-4-5"

PROMPT_SISTEMA_LLM = """Eres un normalizador de datos. Recibes una matriz cruda de celdas \
(filas y columnas, separadas por " | ") extraída de un archivo Excel/CSV/TXT con \
especificaciones técnicas, y debes reorganizarla en pares Parámetro/Valor.

Reglas estrictas:
- No inventes, no resumas, no parafrasees ni completes información que no esté en el \
archivo. Tu única tarea es reorganizar el contenido existente en pares Parámetro/Valor.
- Si una columna es una categoría o encabezado de grupo que solo aparece en la primera \
fila de un conjunto de filas relacionadas (patrón típico de celdas combinadas de Excel \
exportadas a CSV), NO la uses como nombre de parámetro -- ignórala o mantenla solo como \
contexto de agrupación.
- Si una fila no tiene nombre de parámetro pero sí tiene valor, es continuación del \
parámetro de la fila anterior: une ese valor al valor previo (con salto de línea), no \
crees un parámetro nuevo con nombre vacío.
- Si una fila es claramente un título o encabezado general del documento y no representa \
un parámetro técnico real, no la incluyas en "parametros": repórtala en "descartadas" con \
el texto de la fila y el motivo (ej. "fila de título").
- Toda fila del archivo original debe terminar mapeada a un parámetro, fusionada como \
continuación de un valor, o reportada en "descartadas" -- ninguna se pierde en silencio.
- Devuelve el texto de cada valor exactamente como aparece en el archivo, sin alterar \
números, unidades, símbolos (≥, ≤, °C, etc.) ni signos de puntuación."""

ESQUEMA_SALIDA_LLM = {
    "type": "object",
    "properties": {
        "parametros": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "parametro": {"type": "string"},
                    "valor": {"type": "string"},
                },
                "required": ["parametro", "valor"],
                "additionalProperties": False,
            },
        },
        "descartadas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fila": {"type": "string"},
                    "motivo": {"type": "string"},
                },
                "required": ["fila", "motivo"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["parametros", "descartadas"],
    "additionalProperties": False,
}


class ErrorImportacionParametros(ValueError):
    """Error permanente: archivo vacío, corrupto, o sin ningún contenido
    reconocible como parámetro (ni por el camino rápido ni con ayuda de
    IA). Apto para mostrar directamente en st.error."""


class ErrorLLMImportacionParametros(Exception):
    """Error transitorio del camino LLM (timeout, red, límite de tokens,
    respuesta no interpretable). A diferencia de ErrorImportacionParametros,
    el archivo ya cargado no se pierde y conviene ofrecer reintentar."""


class ResultadoImportacionParametros:
    """Resultado de `importar_parametros`. `camino` es "rapido" o "llm" --
    útil para el resumen post-importación que exige el flujo (cuántos
    parámetros, qué camino se usó, qué se descartó)."""

    def __init__(
        self,
        parametros: list[dict],
        camino: str,
        filas_descartadas: list[dict],
        advertencia_integridad: str | None,
    ) -> None:
        self.parametros = parametros
        self.camino = camino
        self.filas_descartadas = filas_descartadas
        self.advertencia_integridad = advertencia_integridad


def _leer_matriz_cruda(nombre_archivo: str, contenido: bytes) -> list[list[str]]:
    """Delegado a scripts.lectura_archivos_tabulares (compartido con
    scripts/importador_items.py): envuelve el ValueError genérico de ahí en
    ErrorImportacionParametros, mismo mensaje que antes."""
    try:
        return leer_matriz_cruda(nombre_archivo, contenido)
    except ValueError as exc:
        raise ErrorImportacionParametros(str(exc)) from exc


def _intentar_camino_rapido(matriz: list[list[str]]) -> list[dict] | None:
    """Camino rápido determinístico, sin LLM. Devuelve None (para que el
    llamador escale al camino LLM) si el archivo no tiene pinta de ser un
    2 columnas simple:
    - alguna fila tiene más de 2 celdas pobladas (columna de categoría de
      celda combinada u otra columna extra), o
    - ninguna fila tiene 2 celdas pobladas a la vez (no hay estructura de
      2 columnas reconocible -- ej. texto libre sin separador claro), o
    - más del 30% de las filas no vacías no se pudieron mapear a un
      parámetro nuevo ni fusionar como continuación de uno existente.

    Si el archivo aplica, columna 0 = Parámetro, columna 1 = Valor/Descripción
    (mismo contrato que el parser anterior); una fila con columna 0 vacía
    y columna 1 con contenido se trata como continuación del Valor de la
    ÚLTIMA fila ya registrada (se fusiona con "\\n"), replicando el
    comportamiento ya probado en producción para listas multilínea."""
    filas_no_vacias = [fila for fila in matriz if any(celda.strip() for celda in fila)]
    if not filas_no_vacias:
        return None

    ancho_max = max(sum(1 for celda in fila if celda.strip()) for fila in filas_no_vacias)
    if ancho_max > 2 or ancho_max < 2:
        return None

    parametros: list[dict] = []
    filas_perdidas = 0
    for fila in filas_no_vacias:
        nombre = fila[0].strip() if len(fila) > 0 else ""
        valor = fila[1].strip() if len(fila) > 1 else ""
        if nombre:
            parametros.append({"nombre": nombre, "valor": valor})
        elif valor and parametros:
            parametros[-1]["valor"] = f"{parametros[-1]['valor']}\n{valor}".strip()
        else:
            filas_perdidas += 1

    if not parametros:
        return None
    proporcion_util = (len(filas_no_vacias) - filas_perdidas) / len(filas_no_vacias)
    if proporcion_util < UMBRAL_PROPORCION_UTIL_CAMINO_RAPIDO:
        return None
    return parametros


def _normalizar_bloque_con_llm(
    bloque: list[list[str]], cliente_llm, modelo: str
) -> tuple[list[dict], list[dict]]:
    # Privacidad: solo lo necesario y con datos personales enmascarados (ver
    # scripts/llm_seguro.py) antes de salir hacia la API externa.
    matriz_texto = "\n".join(" | ".join(celda for celda in fila) for fila in preparar_matriz_para_llm(bloque))
    try:
        respuesta = cliente_llm.with_options(timeout=60.0).messages.create(
            model=modelo,
            max_tokens=8192,
            system=PROMPT_SISTEMA_LLM,
            output_config={"format": {"type": "json_schema", "schema": ESQUEMA_SALIDA_LLM}},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Matriz cruda del archivo (una fila por línea, celdas "
                        f"separadas por \" | \"):\n\n{matriz_texto}"
                    ),
                }
            ],
        )
    except anthropic.APIError as exc:
        raise ErrorLLMImportacionParametros(
            f"No se pudo interpretar el archivo con IA: {exc}"
        ) from exc

    texto_json = next((b.text for b in respuesta.content if b.type == "text"), None)
    if texto_json is None:
        raise ErrorLLMImportacionParametros("La IA no devolvió una respuesta interpretable.")
    try:
        # Respuesta NO confiable: se valida con Pydantic y se limpia (ver llm_seguro.py).
        datos = validar_respuesta_llm(RespuestaLLMParametros, texto_json)
    except ValueError as exc:
        raise ErrorLLMImportacionParametros(
            f"La IA devolvió una respuesta no válida: {exc}"
        ) from exc

    parametros = [
        {"nombre": p.get("parametro", ""), "valor": p.get("valor", "")}
        for p in datos.get("parametros", [])
    ]
    descartadas = [
        {"fila": d.get("fila", ""), "motivo": d.get("motivo", "")}
        for d in datos.get("descartadas", [])
    ]
    return parametros, descartadas


def _normalizar_con_llm(
    matriz: list[list[str]],
    cliente_llm=None,
    modelo: str = MODELO_LLM_POR_DEFECTO,
) -> tuple[list[dict], list[dict]]:
    """Normaliza la matriz completa vía la API de Claude. Si el archivo es
    grande (más de TAMANO_BLOQUE_LLM filas no vacías), se procesa por
    bloques y se combinan los resultados -- limitación conocida: la fusión
    de una fila de continuación solo opera dentro de un mismo bloque, no a
    través del límite entre bloques."""
    if cliente_llm is None:
        if not llm_fallback_habilitado():
            raise RespaldoIADesactivado
        cliente_llm = anthropic.Anthropic()

    filas_no_vacias = [fila for fila in matriz if any(celda.strip() for celda in fila)]
    bloques = [
        filas_no_vacias[i : i + TAMANO_BLOQUE_LLM] for i in range(0, len(filas_no_vacias), TAMANO_BLOQUE_LLM)
    ]

    parametros: list[dict] = []
    descartadas: list[dict] = []
    for bloque in bloques:
        parametros_bloque, descartadas_bloque = _normalizar_bloque_con_llm(bloque, cliente_llm, modelo)
        parametros.extend(parametros_bloque)
        descartadas.extend(descartadas_bloque)
    return parametros, descartadas


def _calcular_advertencia_integridad(matriz: list[list[str]], parametros: list[dict]) -> str | None:
    """Compara la suma de caracteres de todas las celdas no vacías del
    archivo original con la suma de caracteres de nombre+valor del
    resultado. Si difieren en más del 15%, devuelve una advertencia (no
    bloquea el flujo, solo alerta)."""
    caracteres_originales = sum(len(celda.strip()) for fila in matriz for celda in fila if celda.strip())
    if caracteres_originales == 0:
        return None
    caracteres_resultado = sum(len(p["nombre"]) + len(p["valor"]) for p in parametros)
    diferencia = abs(caracteres_originales - caracteres_resultado) / caracteres_originales
    if diferencia > UMBRAL_ADVERTENCIA_INTEGRIDAD:
        return (
            "El contenido importado difiere significativamente del archivo original, "
            "revisa cuidadosamente antes de guardar."
        )
    return None


def importar_parametros(
    nombre_archivo: str, contenido: bytes, cliente_llm=None
) -> ResultadoImportacionParametros:
    """Punto de entrada único: intenta el camino rápido y, si no aplica,
    escala al normalizador LLM. Lanza ErrorImportacionParametros si el
    archivo no tiene ningún contenido reconocible como parámetro por
    ninguno de los dos caminos; lanza ErrorLLMImportacionParametros si el
    camino LLM se necesita pero falla (red, timeout, respuesta inválida)."""
    matriz = _leer_matriz_cruda(nombre_archivo, contenido)
    if not any(any(celda.strip() for celda in fila) for fila in matriz):
        raise ErrorImportacionParametros("El archivo está vacío o no tiene contenido reconocible.")

    parametros_rapido = _intentar_camino_rapido(matriz)
    if parametros_rapido is not None:
        return ResultadoImportacionParametros(
            parametros=parametros_rapido,
            camino="rapido",
            filas_descartadas=[],
            advertencia_integridad=_calcular_advertencia_integridad(matriz, parametros_rapido),
        )

    parametros_llm, descartadas_llm = _normalizar_con_llm(matriz, cliente_llm)
    if not parametros_llm:
        raise ErrorImportacionParametros(
            "No se pudo extraer ningún parámetro válido del archivo, ni por el camino "
            "rápido ni con ayuda de IA."
        )
    return ResultadoImportacionParametros(
        parametros=parametros_llm,
        camino="llm",
        filas_descartadas=descartadas_llm,
        advertencia_integridad=_calcular_advertencia_integridad(matriz, parametros_llm),
    )
