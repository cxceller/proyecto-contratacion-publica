"""Importador robusto de "Ítems" para la sección Ítems y Presupuesto de
Especificaciones Técnicas: convierte un archivo subido (.xlsx/.csv/.txt)
con un presupuesto/lista de ítems en una lista de filas listas para
anexarse a la tabla editable, sin importar el orden de columnas, encabezados
con errores de tipeo, ni filas de título/total intercaladas.

Camino híbrido (mismo patrón que scripts/importador_parametros.py):
1. Parser determinístico rápido (`_intentar_camino_rapido`): detecta la fila
   de encabezado escaneando las primeras filas del archivo, mapea columnas
   por fuzzy matching (difflib) contra variantes conocidas de cada campo
   (ej. "PRECIO UNIARIO" -> valor_unitario), excluye explícitamente las
   columnas de "Descripción/Detalle del CPC" y "Valor Total" (nunca se usan
   como fuente de datos), y descarta filas de TOTAL/SUBTOTAL reportándolas.
   Si no se detecta un encabezado reconocible o quedan muy pocos campos
   mapeados, se escala al camino 2.
2. Normalizador vía API de Claude (`_normalizar_con_llm`): mismo esquema de
   salida estructurada (JSON Schema estricto vía `output_config.format`)
   para archivos sin estructura de columnas clara (ej. TXT libre).

Ambos caminos comparten el mismo parser numérico (`_parsear_numero`) y el
mismo lookup contra el catálogo CPC (`_aplicar_catalogo`) -- una sola
implementación de cada cosa, no importa por qué camino llegó la fila.

El catálogo CPC (`catalogo_cpc: dict[str, str]`) se recibe por inyección de
dependencia -- este módulo no sabe ni le importa cómo se carga (en
ui/especificaciones_tecnicas.py vive `_cargar_catalogo_cpc()`, cacheada con
`st.cache_data`); acá solo se usa para marcar códigos no reconocidos, igual
que ya hace `_autocompletar_descripcion_cpc` en ese mismo módulo al guardar
(ver ese módulo: esta es una conveniencia de UX inmediata, no un reemplazo
de esa lógica).

"Tipo" (Bien/Servicio) se infiere de la descripción del producto/servicio
por palabras clave (`_inferir_tipo`) en el camino rápido, y por el propio
LLM (guiado por el mismo criterio, ver PROMPT_SISTEMA_LLM) en el camino de
respaldo -- nunca por el código CPC, que no aparece en ninguno de los dos
criterios. En ambos casos es solo un prellenado: el selector Bien/Servicio
de la tabla sigue totalmente editable, y si no hay ninguna palabra clave
reconocible se deja "" en vez de adivinar con un valor por defecto
arbitrario.

Nada de esto guarda en base de datos -- el resultado se anexa a las filas
editables de la tabla, igual que si el usuario las hubiera escrito a mano
(ver app_ui.py)."""
import difflib
import json
import re
import unicodedata

import anthropic
import truststore

from scripts.lectura_archivos_tabulares import leer_matriz_cruda

# Ver el mismo bloque de comentario en scripts/importador_parametros.py:
# la red institucional de este proyecto tiene un proxy/firewall con
# inspeccion TLS cuya CA raiz Windows si confia pero certifi (el bundle que
# usa httpx/el SDK de anthropic) no. Cada modulo que construye su propio
# cliente de Anthropic llama esto de forma independiente -- no se asume que
# otro modulo ya lo haya activado, para que este importador funcione aunque
# se use standalone (ej. en un test que no importe importador_parametros).
truststore.inject_into_ssl()

TAMANO_BLOQUE_LLM = 150
MODELO_LLM_POR_DEFECTO = "claude-haiku-4-5"

UMBRAL_SIMILITUD_ENCABEZADO = 0.6
MIN_CAMPOS_NUCLEO_PARA_ENCABEZADO = 3
FILAS_A_ESCANEAR_ENCABEZADO = 15

# Variantes conocidas por campo objetivo, ya normalizadas (mayúsculas, sin
# tildes). El fuzzy matching (difflib) resuelve errores de tipeo menores
# (ej. "PRECIO UNIARIO") contra estas variantes; no hace falta listar cada
# typo posible a mano.
VARIANTES_POR_CAMPO = {
    "item": ["ITEM", "N", "NO", "NUM"],
    "descripcion": ["DESCRIPCION DEL PRODUCTO", "DESCRIPCION DEL BIEN O SERVICIO", "DESCRIPCION"],
    "unidad_medida": ["UNIDAD", "UNIDAD DE MEDIDA"],
    "cantidad_solicitada": ["CANTIDAD", "CANTIDAD SOLICITADA"],
    "valor_unitario": ["PRECIO UNITARIO", "VALOR UNITARIO"],
    "numero_cpc": ["CPC", "CODIGO CPC", "NUMERO CPC"],
}
CAMPOS_NUCLEO = ["item", "descripcion", "unidad_medida", "cantidad_solicitada", "valor_unitario"]
PALABRAS_FILA_TOTAL = {"TOTAL", "SUBTOTAL", "TOTAL GENERAL"}

# Palabras clave (ya en mayúsculas/sin tildes, ver _normalizar_encabezado)
# para inferir "Tipo" desde la descripción -- mismo criterio que se le pide
# al LLM en PROMPT_SISTEMA_LLM para el camino de respaldo. SERVICIO se
# revisa primero: una descripción de mantenimiento/reparación casi siempre
# menciona también el equipo o material involucrado (ej. "MANTENIMIENTO DE
# EQUIPOS"), y es la acción -- no el sustantivo -- la que determina el tipo.
PALABRAS_CLAVE_SERVICIO = [
    "MANTENIMIENTO",
    "REPARACION",
    "REPOTENCIACION",
    "CONSULTORIA",
    "ASESORIA",
    "AUDITORIA",
    "FISCALIZACION",
    "SUPERVISION",
    "CAPACITACION",
    "MANO DE OBRA",
    "INSTALACION",
    "LIMPIEZA",
    "VIGILANCIA",
    "SEGURIDAD",
    "TRANSPORTE",
    "ARRENDAMIENTO",
    "ALQUILER",
    "SERVICIO",
    "PRESTACION",
    "IMPLEMENTACION",
    "DESARROLLO DE",
    "DISENO DE",
    "ELABORACION",
    "ACTUALIZACION",
]
PALABRAS_CLAVE_BIEN = [
    "SUMINISTRO",
    "ADQUISICION",
    "COMPRA",
    "EQUIPO",
    "MATERIAL",
    "REPUESTO",
    "INSUMO",
    "HERRAMIENTA",
    "MOBILIARIO",
    "VEHICULO",
    "UNIFORME",
    "MAQUINARIA",
]

PROMPT_SISTEMA_LLM = """Eres un normalizador de datos de presupuestos de contratación pública. \
Recibes una matriz cruda de celdas (filas y columnas, separadas por " | ") extraída de un \
archivo Excel/CSV/TXT con la lista de ítems de un presupuesto, y debes reorganizarla en una \
lista de ítems.

Reglas estrictas:
- No inventes, no completes ni corrijas datos que no estén en el archivo. Tu única tarea es \
reorganizar el contenido existente.
- Extrae SOLO estos campos por ítem: número de ítem, CPC, descripción del producto/servicio, \
unidad de medida, cantidad solicitada y precio/valor unitario.
- Si el archivo tiene una columna de "Descripción del CPC" o "Detalle del CPC" (el texto \
oficial del catálogo CPC), IGNÓRALA por completo -- nunca la uses como descripción del \
producto.
- Si el archivo tiene una columna "Valor Total", IGNÓRALA -- siempre se recalcula aparte, \
nunca se extrae del archivo.
- Para cada ítem, clasifica "tipo" como "Bien" o "Servicio" según su descripción (nunca según \
el código CPC): "Bien" para compras físicas, suministro de equipos, materiales, partes y \
elementos tangibles (ej. "SUMINISTRO DE LUMINARIA LED"); "Servicio" para mantenimientos, \
reparaciones, consultorías, mano de obra, trabajos especializados y prestaciones (ej. \
"MANTENIMIENTO PREVENTIVO Y REPOTENCIACIÓN").
- Los campos numéricos (cantidad_solicitada, valor_unitario) se devuelven como texto, \
EXACTAMENTE como aparecen en el archivo (mismos separadores/símbolos), sin redondear ni \
convertir.
- Si una fila es un título, encabezado de sección, o una fila de "TOTAL"/"SUBTOTAL" y no \
representa un ítem real, no la incluyas en "items": repórtala en "filas_con_error" con el \
texto de la fila y el motivo.
- Toda fila de datos del archivo original debe terminar mapeada a un ítem o reportada en \
"filas_con_error" -- ninguna se pierde en silencio."""

ESQUEMA_SALIDA_LLM = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "cpc": {"type": "string"},
                    "descripcion": {"type": "string"},
                    "unidad_de_medida": {"type": "string"},
                    "cantidad_solicitada": {"type": "string"},
                    "valor_unitario": {"type": "string"},
                    "tipo": {"type": "string", "enum": ["Bien", "Servicio"]},
                },
                "required": [
                    "item",
                    "cpc",
                    "descripcion",
                    "unidad_de_medida",
                    "cantidad_solicitada",
                    "valor_unitario",
                    "tipo",
                ],
                "additionalProperties": False,
            },
        },
        "filas_con_error": {
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
    "required": ["items", "filas_con_error"],
    "additionalProperties": False,
}


class ErrorImportacionItems(ValueError):
    """Error permanente: archivo vacío, corrupto, o sin ningún ítem
    reconocible (ni por el camino rápido ni con ayuda de IA). Apto para
    mostrar directamente en st.error."""


class ErrorLLMImportacionItems(Exception):
    """Error transitorio del camino LLM (timeout, red, límite de tokens,
    respuesta no interpretable). A diferencia de ErrorImportacionItems, el
    archivo ya cargado no se pierde y conviene ofrecer reintentar."""


class ResultadoImportacionItems:
    """Resultado de `importar_items`. `filas` usa vocabulario propio en
    snake_case (tipo, descripcion, unidad_medida, cantidad_solicitada,
    valor_unitario, numero_cpc, descripcion_cpc), desacoplado de los
    nombres exactos de columna de app_ui.py -- es ese módulo quien traduce
    esto a las columnas reales de la tabla."""

    def __init__(
        self,
        filas: list[dict],
        camino: str,
        filas_con_error: list[dict],
        cpc_no_encontrados: list[str],
    ) -> None:
        self.filas = filas
        self.camino = camino
        self.filas_con_error = filas_con_error
        self.cpc_no_encontrados = cpc_no_encontrados


def _normalizar_encabezado(texto: str) -> str:
    """Mayúsculas, sin tildes, espacios colapsados -- forma comparable
    tanto para el fuzzy matching de encabezados como para detectar filas de
    TOTAL/SUBTOTAL."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sin_tildes).strip().upper()


def _similitud(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _encabezado_excluido(encabezado_normalizado: str) -> bool:
    """Columnas que nunca deben mapearse a ningún campo, evaluado ANTES de
    intentar el fuzzy matching: "Descripción/Detalle del CPC" (para que
    jamás compita con "Descripción del Producto" por el campo
    `descripcion`) y "Valor Total" (siempre se recalcula, nunca se
    extrae)."""
    tiene_cpc = "CPC" in encabezado_normalizado
    if tiene_cpc and ("DESCRIPCION" in encabezado_normalizado or "DETALLE" in encabezado_normalizado):
        return True
    return _similitud(encabezado_normalizado, "VALOR TOTAL") >= UMBRAL_SIMILITUD_ENCABEZADO


def _mapear_encabezados(fila: list[str]) -> dict[int, str]:
    """Asigna cada índice de columna de `fila` a lo sumo un campo objetivo,
    y cada campo objetivo a lo sumo una columna, por asignación golosa
    global: se calculan todos los pares (columna, campo, similitud) por
    encima del umbral, se ordenan de mayor a menor similitud, y se asignan
    en ese orden saltando lo que ya esté usado."""
    normalizados = [_normalizar_encabezado(celda) for celda in fila]
    candidatos = []
    for indice, encabezado in enumerate(normalizados):
        if not encabezado or _encabezado_excluido(encabezado):
            continue
        for campo, variantes in VARIANTES_POR_CAMPO.items():
            mejor_ratio = max(_similitud(encabezado, variante) for variante in variantes)
            if mejor_ratio >= UMBRAL_SIMILITUD_ENCABEZADO:
                candidatos.append((mejor_ratio, indice, campo))
    candidatos.sort(key=lambda c: c[0], reverse=True)

    mapeo: dict[int, str] = {}
    campos_usados: set[str] = set()
    for _, indice, campo in candidatos:
        if indice in mapeo or campo in campos_usados:
            continue
        mapeo[indice] = campo
        campos_usados.add(campo)
    return mapeo


def _detectar_fila_encabezado(matriz: list[list[str]]) -> int | None:
    """Escanea las primeras FILAS_A_ESCANEAR_ENCABEZADO filas y devuelve el
    índice de la primera que mapea al menos MIN_CAMPOS_NUCLEO_PARA_ENCABEZADO
    de los 5 campos núcleo. None si ninguna califica (archivo sin
    estructura de columnas reconocible -- escala al camino LLM)."""
    for indice_fila in range(min(len(matriz), FILAS_A_ESCANEAR_ENCABEZADO)):
        mapeo = _mapear_encabezados(matriz[indice_fila])
        if sum(1 for campo in mapeo.values() if campo in CAMPOS_NUCLEO) >= MIN_CAMPOS_NUCLEO_PARA_ENCABEZADO:
            return indice_fila
    return None


def _parsear_numero(texto: str) -> float | None:
    """Convierte texto de una celda numérica a float, tolerando símbolos de
    moneda y ambos convenios de separador decimal/miles: si aparecen coma Y
    punto, el que está más a la derecha es el decimal (el otro se trata
    como separador de miles y se elimina); si solo aparece coma, se asume
    separador decimal (convención Ecuador, ver scripts/formato_ec.py).
    Devuelve None si no se puede interpretar como número (la fila no se
    descarta por esto -- ver _construir_fila)."""
    texto = (texto or "").strip()
    if not texto:
        return None
    limpio = re.sub(r"[^0-9,.\-]", "", texto)
    if not limpio or limpio in ("-", ".", ","):
        return None
    if "," in limpio and "." in limpio:
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return None


def _inferir_tipo(descripcion: str) -> str:
    """Infiere "Bien" o "Servicio" a partir de palabras clave en la
    descripción del producto/servicio (ver PALABRAS_CLAVE_SERVICIO /
    PALABRAS_CLAVE_BIEN) -- usado por el camino rápido, que no tiene un LLM
    a mano para interpretar la descripción. Si ninguna palabra clave
    aparece, devuelve "" en vez de adivinar: el usuario elige a mano en el
    selector, igual que si la fila la hubiera escrito él."""
    texto = _normalizar_encabezado(descripcion)
    if not texto:
        return ""
    if any(palabra in texto for palabra in PALABRAS_CLAVE_SERVICIO):
        return "Servicio"
    if any(palabra in texto for palabra in PALABRAS_CLAVE_BIEN):
        return "Bien"
    return ""


def _es_fila_total(valores: dict[str, str]) -> bool:
    """Fila de TOTAL/SUBTOTAL: la celda de descripción (o, si esa vino
    vacía, cualquier otra celda mapeada) dice literalmente eso."""
    if _normalizar_encabezado(valores.get("descripcion", "")) in PALABRAS_FILA_TOTAL:
        return True
    return any(_normalizar_encabezado(valor) in PALABRAS_FILA_TOTAL for valor in valores.values())


def _construir_fila(valores: dict[str, str]) -> tuple[dict, str | None]:
    """Arma una fila en el vocabulario de salida a partir de los valores ya
    mapeados por campo (misma función para el camino rápido y para la
    salida del LLM, así hay un solo lugar que interpreta números). Si
    Cantidad Solicitada o Valor Unitario no se pueden parsear como número,
    la fila NO se descarta: el campo queda en 0.0 y se devuelve un motivo
    para reportar en filas_con_error. `valores["tipo"]` ya viene resuelto
    por el llamador (heurística de palabras clave en el camino rápido,
    clasificación del propio LLM en el camino de respaldo) -- esta función
    no decide Bien/Servicio, solo lo traslada."""
    errores = []

    cantidad_texto = valores.get("cantidad_solicitada", "")
    cantidad = _parsear_numero(cantidad_texto)
    if cantidad_texto and cantidad is None:
        errores.append(f"Cantidad Solicitada no numérica: '{cantidad_texto}'")
    cantidad = cantidad or 0.0

    valor_texto = valores.get("valor_unitario", "")
    valor_unitario = _parsear_numero(valor_texto)
    if valor_texto and valor_unitario is None:
        errores.append(f"Valor Unitario no numérico: '{valor_texto}'")
    valor_unitario = valor_unitario or 0.0

    fila = {
        "tipo": valores.get("tipo", ""),
        "descripcion": valores.get("descripcion", ""),
        "unidad_medida": valores.get("unidad_medida", ""),
        "cantidad_solicitada": cantidad,
        "valor_unitario": valor_unitario,
        "numero_cpc": valores.get("numero_cpc", ""),
        "descripcion_cpc": "",
    }
    return fila, ("; ".join(errores) if errores else None)


def _aplicar_catalogo(fila: dict, catalogo_cpc: dict[str, str] | None, cpc_no_encontrados: list[str]) -> None:
    """Autocompleta `descripcion_cpc` contra el catálogo inyectado -- misma
    función usada por ambos caminos. Si el código no está vacío pero no
    aparece en el catálogo, se acumula en cpc_no_encontrados (el guardado
    normal de app_ui.py lo reintentará como red de seguridad)."""
    codigo = fila.get("numero_cpc", "")
    if not codigo or catalogo_cpc is None:
        return
    if codigo in catalogo_cpc:
        fila["descripcion_cpc"] = catalogo_cpc[codigo]
    else:
        cpc_no_encontrados.append(codigo)


def _intentar_camino_rapido(
    matriz: list[list[str]], catalogo_cpc: dict[str, str] | None
) -> tuple[list[dict], list[dict], list[str]] | None:
    """Camino rápido determinístico, sin LLM. Devuelve None (para escalar
    al camino LLM) si no se detecta una fila de encabezado reconocible o si
    el resultado queda vacío."""
    indice_encabezado = _detectar_fila_encabezado(matriz)
    if indice_encabezado is None:
        return None
    mapeo = _mapear_encabezados(matriz[indice_encabezado])

    filas: list[dict] = []
    filas_con_error: list[dict] = []
    cpc_no_encontrados: list[str] = []
    for fila_cruda in matriz[indice_encabezado + 1 :]:
        if not any(celda.strip() for celda in fila_cruda):
            continue  # fila totalmente vacia (espaciado visual de Excel): no es contenido perdido

        valores = {
            campo: (fila_cruda[indice].strip() if indice < len(fila_cruda) else "")
            for indice, campo in mapeo.items()
        }
        valores["tipo"] = _inferir_tipo(valores.get("descripcion", ""))
        texto_fila_original = " | ".join(celda for celda in fila_cruda if celda.strip())
        if _es_fila_total(valores):
            filas_con_error.append({"fila": texto_fila_original, "motivo": "fila de total/subtotal excluida"})
            continue

        fila, motivo_numerico = _construir_fila(valores)
        if motivo_numerico:
            filas_con_error.append({"fila": texto_fila_original, "motivo": motivo_numerico})
        _aplicar_catalogo(fila, catalogo_cpc, cpc_no_encontrados)
        filas.append(fila)

    if not filas:
        return None
    return filas, filas_con_error, cpc_no_encontrados


def _normalizar_bloque_con_llm(
    bloque: list[list[str]],
    cliente_llm,
    modelo: str,
    catalogo_cpc: dict[str, str] | None,
    cpc_no_encontrados: list[str],
) -> tuple[list[dict], list[dict]]:
    matriz_texto = "\n".join(" | ".join(celda for celda in fila) for fila in bloque)
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
        raise ErrorLLMImportacionItems(f"No se pudo interpretar el archivo con IA: {exc}") from exc

    texto_json = next((b.text for b in respuesta.content if b.type == "text"), None)
    if texto_json is None:
        raise ErrorLLMImportacionItems("La IA no devolvió una respuesta interpretable.")
    try:
        datos = json.loads(texto_json)
    except json.JSONDecodeError as exc:
        raise ErrorLLMImportacionItems(f"La IA devolvió una respuesta no válida: {exc}") from exc

    filas: list[dict] = []
    filas_con_error: list[dict] = []
    for item in datos.get("items", []):
        descripcion = item.get("descripcion", "")
        tipo_llm = item.get("tipo", "")
        valores = {
            "descripcion": descripcion,
            "unidad_medida": item.get("unidad_de_medida", ""),
            "cantidad_solicitada": item.get("cantidad_solicitada", ""),
            "valor_unitario": item.get("valor_unitario", ""),
            "numero_cpc": item.get("cpc", ""),
            # El esquema estricto (enum "Bien"/"Servicio") ya garantiza un valor
            # válido, pero se valida igual antes de confiar en él: si por lo que
            # sea llega otra cosa, se cae de vuelta a la heurística de palabras
            # clave en vez de propagar un valor fuera de las dos opciones válidas.
            "tipo": tipo_llm if tipo_llm in ("Bien", "Servicio") else _inferir_tipo(descripcion),
        }
        fila, motivo_numerico = _construir_fila(valores)
        if motivo_numerico:
            descriptor = item.get("descripcion") or item.get("item") or "(sin descripción)"
            filas_con_error.append({"fila": descriptor, "motivo": motivo_numerico})
        _aplicar_catalogo(fila, catalogo_cpc, cpc_no_encontrados)
        filas.append(fila)

    filas_con_error.extend(
        {"fila": d.get("fila", ""), "motivo": d.get("motivo", "")} for d in datos.get("filas_con_error", [])
    )
    return filas, filas_con_error


def _normalizar_con_llm(
    matriz: list[list[str]],
    catalogo_cpc: dict[str, str] | None,
    cliente_llm=None,
    modelo: str = MODELO_LLM_POR_DEFECTO,
) -> tuple[list[dict], list[dict], list[str]]:
    """Normaliza la matriz completa vía la API de Claude, por bloques de
    TAMANO_BLOQUE_LLM filas si el archivo es grande (misma limitación
    documentada que en importador_parametros.py: nada que dependa de
    contexto entre bloques se resuelve a través del límite de bloque)."""
    if cliente_llm is None:
        cliente_llm = anthropic.Anthropic()

    filas_no_vacias = [fila for fila in matriz if any(celda.strip() for celda in fila)]
    bloques = [
        filas_no_vacias[i : i + TAMANO_BLOQUE_LLM] for i in range(0, len(filas_no_vacias), TAMANO_BLOQUE_LLM)
    ]

    filas: list[dict] = []
    filas_con_error: list[dict] = []
    cpc_no_encontrados: list[str] = []
    for bloque in bloques:
        filas_bloque, errores_bloque = _normalizar_bloque_con_llm(
            bloque, cliente_llm, modelo, catalogo_cpc, cpc_no_encontrados
        )
        filas.extend(filas_bloque)
        filas_con_error.extend(errores_bloque)
    return filas, filas_con_error, cpc_no_encontrados


def importar_items(
    nombre_archivo: str,
    contenido: bytes,
    catalogo_cpc: dict[str, str] | None = None,
    cliente_llm=None,
) -> ResultadoImportacionItems:
    """Punto de entrada único: intenta el camino rápido y, si no aplica,
    escala al normalizador LLM. Lanza ErrorImportacionItems si el archivo
    no tiene ningún ítem reconocible por ninguno de los dos caminos; lanza
    ErrorLLMImportacionItems si el camino LLM se necesita pero falla (red,
    timeout, respuesta inválida)."""
    try:
        matriz = leer_matriz_cruda(nombre_archivo, contenido)
    except ValueError as exc:
        raise ErrorImportacionItems(str(exc)) from exc
    if not any(any(celda.strip() for celda in fila) for fila in matriz):
        raise ErrorImportacionItems("El archivo está vacío o no tiene contenido reconocible.")

    resultado_rapido = _intentar_camino_rapido(matriz, catalogo_cpc)
    if resultado_rapido is not None:
        filas, filas_con_error, cpc_no_encontrados = resultado_rapido
        return ResultadoImportacionItems(
            filas=filas, camino="rapido", filas_con_error=filas_con_error, cpc_no_encontrados=cpc_no_encontrados
        )

    filas_llm, filas_con_error_llm, cpc_no_encontrados_llm = _normalizar_con_llm(matriz, catalogo_cpc, cliente_llm)
    if not filas_llm:
        raise ErrorImportacionItems(
            "No se pudo extraer ningún ítem válido del archivo, ni por el camino rápido ni con ayuda de IA."
        )
    return ResultadoImportacionItems(
        filas=filas_llm, camino="llm", filas_con_error=filas_con_error_llm, cpc_no_encontrados=cpc_no_encontrados_llm
    )
