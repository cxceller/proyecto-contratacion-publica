"""Endpoint para generar y descargar el informe .docx de procesos de
contratacion publica, ensamblado con scripts/report_generator.py."""
import tempfile
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from scripts.report_generator import generar_reporte
from src import database

CAPTURAS_DIR = Path(__file__).resolve().parent.parent / "capturas"

router = APIRouter()


class GenerarReporteRequest(BaseModel):
    palabras_clave: list[str] = Field(..., min_length=1)
    fecha_inicio: date
    fecha_fin: date
    lote_id: str | None = Field(
        None, description="Si se indica, acota el reporte a una unica ejecucion de scraping/importacion"
    )


def _borrar_archivo(ruta: str) -> None:
    """Tarea en segundo plano (BackgroundTasks): borra el .docx temporal
    despues de que FileResponse termino de enviarlo al cliente."""
    Path(ruta).unlink(missing_ok=True)


@router.post("/api/generar-reporte")
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
    generar_reporte(
        df=pd.DataFrame(registros),
        palabras_clave=payload.palabras_clave,
        fecha_inicio_global=payload.fecha_inicio,
        fecha_fin_global=payload.fecha_fin,
        ruta_salida=ruta_salida,
        capturas_dir=CAPTURAS_DIR,
    )

    background_tasks.add_task(_borrar_archivo, str(ruta_salida))

    return FileResponse(
        path=ruta_salida,
        filename="reporte_contrataciones.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        background=background_tasks,
    )
