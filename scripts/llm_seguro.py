"""Controles de seguridad del respaldo con IA de los importadores
(importador_parametros.py / importador_items.py).

El respaldo envia el contenido del archivo subido a un tercero (API de
Anthropic), asi que:

1. Esta DESACTIVADO por defecto: solo se usa si LLM_FALLBACK_ENABLED=true.
2. Antes de enviar, se ENMASCARAN datos personales reconocibles (cedula, RUC,
   correos, telefonos) y se limita cuanto se manda (filas y largo de celda).
   Los nombres de personas no se pueden detectar de forma confiable: por eso
   la UI avisa de que el archivo sale hacia un servicio externo.
3. La RESPUESTA no se confia: se valida con Pydantic (tipos, largos), se le
   quitan caracteres de control y etiquetas HTML, y recien entonces se usa.
   (Al mostrarla, la UI igualmente escapa con html.escape.)
"""
import os
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MENSAJE_RESPALDO_IA_DESACTIVADO = (
    "No se reconoció la estructura del archivo y el respaldo con IA está desactivado "
    "(por privacidad: enviaría el contenido a un servicio externo). Ajusta el archivo a las "
    "columnas esperadas o pide al administrador activar LLM_FALLBACK_ENABLED."
)

AVISO_ENVIO_A_SERVICIO_EXTERNO = (
    "Respaldo con IA activo: si no se reconoce la estructura del archivo, su contenido se enviará a un "
    "servicio externo (Anthropic) para interpretarlo. Se enmascaran cédulas, RUC, correos y teléfonos "
    "reconocibles, pero NO los nombres de personas: no subas archivos con datos personales que no deban salir."
)

MAX_FILAS_LLM = 300
MAX_LARGO_CELDA_LLM = 300


class RespaldoIADesactivado(Exception):
    """El camino rapido no alcanzo y el respaldo con IA esta apagado. Su
    mensaje es fijo y seguro de mostrar al usuario."""

    def __init__(self) -> None:
        super().__init__(MENSAJE_RESPALDO_IA_DESACTIVADO)


def llm_fallback_habilitado() -> bool:
    return os.environ.get("LLM_FALLBACK_ENABLED", "false").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


# ------------------------------------------------------------ enmascarado
_RE_RUC = re.compile(r"(?<!\d)\d{13}(?!\d)")
_RE_CEDULA_O_CELULAR = re.compile(r"(?<!\d)\d{10}(?!\d)")
_RE_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Solo con prefijo internacional "+593": el formato local (0XX...) NO se enmascara
# aqui porque chocaria con codigos CPC de 9 digitos que empiezan en 0; los
# celulares locales de 10 digitos ya los cubre _RE_CEDULA_O_CELULAR.
_RE_TELEFONO = re.compile(r"\+593[\s-]?\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4}(?!\d)")


def enmascarar_datos_personales(texto: str) -> str:
    """Reemplaza RUC, cedula/celular de 10 digitos, correos y telefonos por
    marcadores. No toca codigos CPC (9 digitos) ni montos."""
    texto = _RE_RUC.sub("[RUC]", texto)
    texto = _RE_CEDULA_O_CELULAR.sub("[CEDULA/TELEFONO]", texto)
    texto = _RE_CORREO.sub("[CORREO]", texto)
    return _RE_TELEFONO.sub("[TELEFONO]", texto)


def preparar_matriz_para_llm(matriz: list[list[str]]) -> list[list[str]]:
    """Solo lo necesario: sin filas vacias, maximo MAX_FILAS_LLM filas, celdas
    de maximo MAX_LARGO_CELDA_LLM caracteres y con datos personales
    enmascarados."""
    filas = [fila for fila in matriz if any(celda.strip() for celda in fila)][:MAX_FILAS_LLM]
    return [[enmascarar_datos_personales(celda)[:MAX_LARGO_CELDA_LLM] for celda in fila] for fila in filas]


# ------------------------------------------------- validacion de respuesta
_RE_ETIQUETAS_HTML = re.compile(r"<[^>]{0,300}>")


# Caracteres de control (salvo \n), de ancho cero y direccionales.
_RE_CONTROL_SIN_SALTO = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f​-‏ -‮⁠-⁤﻿]")


def _texto_llm(valor):
    """Limpia un texto de la IA conservando los saltos de linea (los valores
    de parametros multilinea, ej. listas de certificados, dependen de ellos):
    quita etiquetas HTML y caracteres de control, y normaliza espacios por linea."""
    if valor is None:
        return ""
    if not isinstance(valor, str):
        raise ValueError("se esperaba texto")
    limpio = unicodedata.normalize("NFC", _RE_ETIQUETAS_HTML.sub("", valor))
    limpio = _RE_CONTROL_SIN_SALTO.sub("", limpio.replace("\r\n", "\n").replace("\r", "\n"))
    lineas = [" ".join(linea.split()) for linea in limpio.split("\n")]
    return "\n".join(lineas).strip("\n").strip()


class _ModeloLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ParametroLLM(_ModeloLLM):
    parametro: str = Field("", max_length=300)
    valor: str = Field("", max_length=5000)

    _limpiar = field_validator("parametro", "valor", mode="before")(_texto_llm)


class DescartadaLLM(_ModeloLLM):
    fila: str = Field("", max_length=2000)
    motivo: str = Field("", max_length=500)

    _limpiar = field_validator("fila", "motivo", mode="before")(_texto_llm)


class RespuestaLLMParametros(_ModeloLLM):
    parametros: list[ParametroLLM] = Field(default_factory=list, max_length=2000)
    descartadas: list[DescartadaLLM] = Field(default_factory=list, max_length=2000)


class ItemLLM(_ModeloLLM):
    item: str = Field("", max_length=50)
    cpc: str = Field("", max_length=30)
    descripcion: str = Field("", max_length=3000)
    unidad_de_medida: str = Field("", max_length=100)
    cantidad_solicitada: str = Field("", max_length=50)
    valor_unitario: str = Field("", max_length=50)
    tipo: str = Field("", max_length=20)

    _limpiar = field_validator(
        "item", "cpc", "descripcion", "unidad_de_medida", "cantidad_solicitada", "valor_unitario", "tipo",
        mode="before",
    )(_texto_llm)


class RespuestaLLMItems(_ModeloLLM):
    items: list[ItemLLM] = Field(default_factory=list, max_length=2000)
    filas_con_error: list[DescartadaLLM] = Field(default_factory=list, max_length=2000)


def validar_respuesta_llm(modelo: type[BaseModel], texto_json: str) -> dict:
    """Parsea y valida `texto_json` contra `modelo`; devuelve un dict con las
    mismas claves que usaba el codigo (valores ya limpios). Lanza ValueError
    (mensaje sin contenido de la respuesta) si no cumple."""
    try:
        return modelo.model_validate_json(texto_json).model_dump()
    except ValidationError as exc:
        raise ValueError(f"respuesta de IA invalida ({exc.error_count()} errores de validacion)") from exc
