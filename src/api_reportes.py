"""Endpoint para generar y descargar el informe .docx de procesos de
contratacion publica, ensamblado con scripts/report_generator.py."""
import logging
import tempfile
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from scripts.report_generator import generar_reporte
from src import database
from src.auth import verificar_api_key

CAPTURAS_DIR = Path(__file__).resolve().parent.parent / "capturas"

logger = logging.getLogger(__name__)

router = APIRouter()


class GenerarReporteRequest(BaseModel):
    palabras_clave: list[str] = Field(..., min_length=1)
    fecha_inicio: date
    fecha_fin: date
    lote_id: str | None = Field(
        None, description="Si se indica, acota el reporte a una unica ejecucion de scraping/importacion"
    )

    @model_validator(mode="after")
    def _validar_rango_fechas(self) -> "GenerarReporteRequest":
        # Sin esto, un rango invertido no daba error 422 aqui: llegaba
        # intacto a la consulta SQL (BETWEEN con limites cruzados no
        # devuelve filas) y el endpoint respondia 404 "no se encontraron
        # procesos", un mensaje confuso que no explica la causa real.
        if self.fecha_inicio > self.fecha_fin:
            raise ValueError("La fecha de inicio debe ser anterior a la fecha de fin")
        return self


def _borrar_archivo(ruta: str) -> None:
    """Tarea en segundo plano (BackgroundTasks): borra el .docx temporal
    despues de que FileResponse termino de enviarlo al cliente."""
    Path(ruta).unlink(missing_ok=True)


@router.post("/api/generar-reporte", dependencies=[Depends(verificar_api_key)])
def generar_reporte_endpoint(
    payload: GenerarReporteRequest, background_tasks: BackgroundTasks
) -> FileResponse:
    registros = database.get_contrataciones_para_reporte(
        palabras_clave=payload.palabras_clave,
        fecha_inicio=payload.fecha_inicio.isoformat(),
        fecha_fin=payload.fecha_fin.isoformat(),
        lote_id=payload.lote_id,
    )
    if not registros:
        raise HTTPException(
            status_code=404,
            detail="No se encontraron procesos para las palabras clave y el rango de fechas indicados",
        )

    ruta_salida = Path(tempfile.gettempdir()) / f"reporte_{uuid.uuid4().hex}.docx"
    try:
        generar_reporte(
            df=pd.DataFrame(registros),
            palabras_clave=payload.palabras_clave,
            fecha_inicio_global=payload.fecha_inicio,
            fecha_fin_global=payload.fecha_fin,
            ruta_salida=ruta_salida,
            capturas_dir=CAPTURAS_DIR,
        )
    except Exception:
        logger.exception("Fallo al generar el reporte Word en %s", ruta_salida)
        ruta_salida.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Ocurrio un error al generar el reporte. Intenta nuevamente en unos minutos.",
        )

    background_tasks.add_task(_borrar_archivo, str(ruta_salida))

    return FileResponse(
        path=ruta_salida,
        filename="reporte_contrataciones.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        background=background_tasks,
    )
