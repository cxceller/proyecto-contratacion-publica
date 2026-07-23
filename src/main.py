"""API REST de procesos de contratacion publica (FastAPI + SQLite)."""
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Response, status

from src import database
from src.models import ContratacionCreate, ContratacionOut, ContratacionUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="API de Contratacion Publica", lifespan=lifespan)


@app.get("/api/todos", response_model=list[ContratacionOut])
def listar_contrataciones(
    status: str | None = None,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    palabra_clave: str | None = None,
):
    rows = database.get_all_contrataciones(
        status=status,
        fecha_inicio=fecha_inicio.isoformat() if fecha_inicio else None,
        fecha_fin=fecha_fin.isoformat() if fecha_fin else None,
        palabra_clave=palabra_clave,
    )
    return [ContratacionOut(**row) for row in rows]


@app.get("/api/todos/{contratacion_id}", response_model=ContratacionOut)
def obtener_contratacion(contratacion_id: int):
    row = database.get_contratacion_by_id(contratacion_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proceso de contratacion con id {contratacion_id} no encontrado",
        )
    return ContratacionOut(**row)


@app.post("/api/todos", response_model=ContratacionOut, status_code=status.HTTP_201_CREATED)
def crear_contratacion(payload: ContratacionCreate):
    data = payload.model_dump()
    if data.get("fecha_publicacion") is not None:
        data["fecha_publicacion"] = data["fecha_publicacion"].isoformat()

    new_id = database.insert_contratacion(data)
    row = database.get_contratacion_by_id(new_id)
    return ContratacionOut(**row)


@app.patch("/api/todos/{contratacion_id}", response_model=ContratacionOut)
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


@app.delete("/api/todos/{contratacion_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_contratacion(contratacion_id: int):
    existing = database.get_contratacion_by_id(contratacion_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proceso de contratacion con id {contratacion_id} no encontrado",
        )
    database.delete_contratacion(contratacion_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete("/api/todos", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_todas_las_contrataciones():
    database.delete_all_contrataciones()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
