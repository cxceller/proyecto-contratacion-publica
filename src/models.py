"""Modelos Pydantic para validacion de entrada/salida."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

# str_strip_whitespace=True le pide a Pydantic que recorte espacios en
# blanco de TODO campo string antes de aplicar el resto de sus propias
# validaciones (min_length incluido); reemplaza el validador manual
# `strip_and_validate` que antes estaba duplicado en ContratacionBase y
# ContratacionUpdate. min_length=1 en los campos opcionales
# (provincia_canton/palabra_clave/url) preserva el "no puede quedar vacio
# tras el recorte" que tenia ese validador (None sigue estando permitido:
# min_length no se evalua si el valor es None).
_CONFIG_STRIP_WHITESPACE = ConfigDict(str_strip_whitespace=True)


class ContratacionBase(BaseModel):
    model_config = _CONFIG_STRIP_WHITESPACE

    entidad_contratante: str = Field(..., min_length=1, max_length=300)
    objeto_proceso: str = Field(..., min_length=1, max_length=1000)
    estado: str = Field(..., min_length=1, max_length=100)
    provincia_canton: str | None = Field(None, min_length=1, max_length=200)
    presupuesto_referencial: float | None = Field(None, ge=0)
    fecha_publicacion: date | None = None
    palabra_clave: str | None = Field(
        None, min_length=1, max_length=200, description="Palabra clave usada en la busqueda del portal"
    )
    url: str | None = Field(
        None, min_length=1, max_length=500, description="Enlace directo al detalle del proceso en el portal"
    )
    lote_id: str | None = Field(
        None,
        max_length=64,
        description=(
            "Identificador de la ejecucion de scraping/importacion que genero "
            "este registro (mismo valor para todas las filas de una misma "
            "busqueda). Permite reconstruir bloques de busqueda de forma "
            "confiable en los reportes."
        ),
    )
    monto_adjudicado: float | None = Field(
        None,
        ge=0,
        description=(
            "Monto de Adjudicación ($) real, leido de la pagina de detalle del "
            "proceso (campo `url`) durante el scraping -- no viene en la tabla "
            "de resultados de busqueda."
        ),
    )
    motivo_estado_raw: str | None = Field(
        None,
        max_length=5000,
        description=(
            "Texto completo (Razón/Fecha/Justificación) de la celda 'Estado del "
            "Proceso' de la página general de detalle, leído durante el "
            "scraping -- no solo la etiqueta corta del estado."
        ),
    )
    explicacion_estado: str | None = Field(
        None,
        max_length=2000,
        description=(
            "Explicación en lenguaje simple de motivo_estado_raw, generada por "
            "un LLM (ver scripts/explicar_estado_desierta.py) -- hoy solo se "
            "completa para procesos en estado 'Desierta'."
        ),
    )


class ContratacionCreate(ContratacionBase):
    codigo: str = Field(..., min_length=1, max_length=100)


class ContratacionUpdate(BaseModel):
    model_config = _CONFIG_STRIP_WHITESPACE

    codigo: str | None = Field(None, min_length=1, max_length=100)
    entidad_contratante: str | None = Field(None, min_length=1, max_length=300)
    objeto_proceso: str | None = Field(None, min_length=1, max_length=1000)
    estado: str | None = Field(None, min_length=1, max_length=100)
    provincia_canton: str | None = Field(None, min_length=1, max_length=200)
    presupuesto_referencial: float | None = Field(None, ge=0)
    fecha_publicacion: date | None = None
    palabra_clave: str | None = Field(None, min_length=1, max_length=200)
    url: str | None = Field(None, min_length=1, max_length=500)
    lote_id: str | None = Field(None, max_length=64)
    monto_adjudicado: float | None = Field(None, ge=0)
    motivo_estado_raw: str | None = Field(None, max_length=5000)
    explicacion_estado: str | None = Field(None, max_length=2000)


class ContratacionOut(ContratacionCreate):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: int
    created_at: str


class BorradorContratacionUpsert(BaseModel):
    """Se usa tanto para crear como para actualizar un borrador: siempre
    se reemplaza el registro completo (nombre + datos_json), no hay
    actualizacion parcial de un borrador."""

    model_config = _CONFIG_STRIP_WHITESPACE

    nombre_contratacion: str = Field(..., min_length=1, max_length=500)
    datos_json: str = Field(
        ..., min_length=1, description="Estado del formulario de Especificaciones Técnicas, ya serializado a JSON"
    )


class BorradorContratacionResumen(BaseModel):
    """Version liviana (sin datos_json) para listar los borradores
    guardados, ej. en el selectbox de app_ui.py."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_contratacion: str
    fecha_actualizacion: str


class BorradorContratacionOut(BorradorContratacionResumen):
    datos_json: str
