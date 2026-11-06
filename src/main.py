"""API REST de procesos de contratacion publica (FastAPI + SQLite)."""
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status

from src import database, reset
from src.auth import verificar_api_key
from src.logging_config import configurar_logging
from src.models import (
    BorradorContratacionOut,
    BorradorContratacionResumen,
    BorradorContratacionUpsert,
    ContratacionCreate,
    ContratacionOut,
    ContratacionUpdate,
    ResetCompletoRequest,
    ResetCompletoResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


configurar_logging()

def _es_produccion() -> bool:
    """Cloud Run (K_SERVICE) o APP_ENV=production."""
    return bool(os.environ.get("K_SERVICE")) or os.environ.get("APP_ENV", "").lower() == "production"


def _opciones_documentacion() -> dict:
    """En produccion no se publica la documentacion interactiva ni el esquema
    OpenAPI (/docs, /redoc, /openapi.json): no regalan el mapa de la API."""
    if _es_produccion():
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


app = FastAPI(title="API de Contratacion Publica", lifespan=lifespan, **_opciones_documentacion())


@app.get("/api/todos", response_model=list[ContratacionOut], dependencies=[Depends(verificar_api_key)])
def listar_contrataciones(
    estado: str | None = Query(None, max_length=100),
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    palabra_clave: str | None = Query(None, max_length=200),
):
    rows = database.get_all_contrataciones(
        status=estado,
        fecha_inicio=fecha_inicio.isoformat() if fecha_inicio else None,
        fecha_fin=fecha_fin.isoformat() if fecha_fin else None,
        palabra_clave=palabra_clave,
    )
    return [ContratacionOut(**row) for row in rows]


@app.get(
    "/api/todos/{contratacion_id}", response_model=ContratacionOut, dependencies=[Depends(verificar_api_key)]
)
def obtener_contratacion(contratacion_id: int):
    row = database.get_contratacion_by_id(contratacion_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proceso de contratacion con id {contratacion_id} no encontrado",
        )
    return ContratacionOut(**row)


@app.post(
    "/api/todos",
    response_model=ContratacionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verificar_api_key)],
)
def crear_contratacion(payload: ContratacionCreate):
    data = payload.model_dump()
    if data.get("fecha_publicacion") is not None:
        data["fecha_publicacion"] = data["fecha_publicacion"].isoformat()

    try:
        new_id = database.insert_contratacion(data)
    except sqlite3.IntegrityError as exc:
        # `codigo` tiene un indice UNIQUE (ver database.init_db, agregado
        # para que la importacion masiva pueda hacer upsert por codigo --
        # ver database.upsert_contratacion). Esta ruta de creacion manual
        # via API usa insert_contratacion a proposito (no upsert): un
        # codigo repetido aca es un error del que hay que avisarle al
        # cliente de la API, no algo para fusionar en silencio con una
        # fila existente.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un proceso de contratacion con el codigo {data['codigo']!r}",
        ) from exc
    row = database.get_contratacion_by_id(new_id)
    return ContratacionOut(**row)


@app.patch(
    "/api/todos/{contratacion_id}",
    response_model=ContratacionOut,
    dependencies=[Depends(verificar_api_key)],
)
def actualizar_contratacion(contratacion_id: int, payload: ContratacionUpdate):
    existing = database.get_contratacion_by_id(contratacion_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proceso de contratacion con id {contratacion_id} no encontrado",
        )

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=400,
            detail="Debe enviar al menos un campo para actualizar",
        )

    if fields.get("fecha_publicacion") is not None:
        fields["fecha_publicacion"] = fields["fecha_publicacion"].isoformat()

    database.update_contratacion(contratacion_id, fields)
    row = database.get_contratacion_by_id(contratacion_id)
    return ContratacionOut(**row)


@app.delete(
    "/api/todos/{contratacion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_api_key)],
)
def eliminar_contratacion(contratacion_id: int):
    existing = database.get_contratacion_by_id(contratacion_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proceso de contratacion con id {contratacion_id} no encontrado",
        )
    database.delete_contratacion(contratacion_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete(
    "/api/todos",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_api_key)],
)
def eliminar_todas_las_contrataciones():
    database.delete_all_contrataciones()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_RESET_COMPLETO_POR_DEFECTO = ResetCompletoRequest()


@app.post(
    "/api/reset-completo",
    response_model=ResetCompletoResponse,
    dependencies=[Depends(verificar_api_key)],
)
def reset_completo(payload: ResetCompletoRequest = _RESET_COMPLETO_POR_DEFECTO):
    """Zona de peligro > "Borrar todos los procesos importados"
    (app_ui.py::render_vaciar_base_datos): a diferencia de DELETE /api/todos
    (que solo vacia `contrataciones`), esto ademas respalda y borra los
    .docx generados por Reportes (salidas/reportes/) y, si se pide,
    capturas/. Ver src/reset.py para el orden exacto de operaciones."""
    try:
        return reset.ejecutar_reset_completo(borrar_capturas=payload.borrar_capturas)
    except reset.ArchivoBloqueadoError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except reset.RespaldoRemotoError as exc:
        # Cloud Run: no se pudo subir el respaldo -> no se borro NADA.
        raise HTTPException(
            status_code=503,
            detail="No se pudo guardar el respaldo en Cloud Storage; no se borró nada. Inténtalo de nuevo.",
        ) from exc


@app.get(
    "/api/borradores", response_model=list[BorradorContratacionResumen], dependencies=[Depends(verificar_api_key)]
)
def listar_borradores():
    rows = database.get_all_borradores()
    return [BorradorContratacionResumen(**row) for row in rows]


@app.get(
    "/api/borradores/{borrador_id}", response_model=BorradorContratacionOut, dependencies=[Depends(verificar_api_key)]
)
def obtener_borrador(borrador_id: int):
    row = database.get_borrador_by_id(borrador_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Borrador con id {borrador_id} no encontrado")
    return BorradorContratacionOut(**row)


@app.post(
    "/api/borradores",
    response_model=BorradorContratacionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verificar_api_key)],
)
def crear_borrador(payload: BorradorContratacionUpsert):
    new_id = database.insert_borrador(payload.nombre_contratacion, payload.datos_json)
    row = database.get_borrador_by_id(new_id)
    return BorradorContratacionOut(**row)


@app.put(
    "/api/borradores/{borrador_id}",
    response_model=BorradorContratacionOut,
    dependencies=[Depends(verificar_api_key)],
)
def actualizar_borrador(borrador_id: int, payload: BorradorContratacionUpsert):
    existing = database.get_borrador_by_id(borrador_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Borrador con id {borrador_id} no encontrado")
    database.update_borrador(borrador_id, payload.nombre_contratacion, payload.datos_json)
    row = database.get_borrador_by_id(borrador_id)
    return BorradorContratacionOut(**row)


@app.delete(
    "/api/borradores/{borrador_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_api_key)],
)
def eliminar_borrador(borrador_id: int):
    existing = database.get_borrador_by_id(borrador_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Borrador con id {borrador_id} no encontrado")
    database.delete_borrador(borrador_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
