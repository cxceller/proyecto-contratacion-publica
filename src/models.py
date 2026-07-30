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


class ContratacionOut(ContratacionCreate):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: int
    created_at: str
