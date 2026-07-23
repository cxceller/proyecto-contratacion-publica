"""Modelos Pydantic para validacion de entrada/salida."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContratacionBase(BaseModel):
    entidad_contratante: str = Field(..., min_length=1, max_length=300)
    objeto_proceso: str = Field(..., min_length=1, max_length=1000)
    estado: str = Field(..., min_length=1, max_length=100)
    provincia_canton: str | None = Field(None, max_length=200)
    presupuesto_referencial: float | None = Field(None, ge=0)
    fecha_publicacion: date | None = None
    palabra_clave: str | None = Field(
        None, max_length=200, description="Palabra clave usada en la busqueda del portal"
    )

    @field_validator(
        "entidad_contratante", "objeto_proceso", "estado", "provincia_canton", "palabra_clave"
    )
    @classmethod
    def strip_and_validate(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if stripped == "":
            raise ValueError("no puede ser una cadena vacia")
        return stripped


class ContratacionCreate(ContratacionBase):
    codigo: str = Field(..., min_length=1, max_length=100)

    @field_validator("codigo")
    @classmethod
    def strip_codigo(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("codigo no puede ser una cadena vacia")
        return stripped


class ContratacionUpdate(BaseModel):
    codigo: str | None = Field(None, min_length=1, max_length=100)
    entidad_contratante: str | None = Field(None, min_length=1, max_length=300)
    objeto_proceso: str | None = Field(None, min_length=1, max_length=1000)
    estado: str | None = Field(None, min_length=1, max_length=100)
    provincia_canton: str | None = Field(None, max_length=200)
    presupuesto_referencial: float | None = Field(None, ge=0)
    fecha_publicacion: date | None = None
    palabra_clave: str | None = Field(None, max_length=200)

    @field_validator(
        "codigo",
        "entidad_contratante",
        "objeto_proceso",
        "estado",
        "provincia_canton",
        "palabra_clave",
    )
    @classmethod
    def strip_and_validate(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if stripped == "":
            raise ValueError("no puede ser una cadena vacia")
        return stripped


class ContratacionOut(ContratacionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: str
