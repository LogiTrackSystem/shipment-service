import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..events import publish_event
from ..models import PruebaEntrega, Envio, EnvioEvento
from ..schemas import (
    PruebaEntregaCrear, PruebaEntregaLeer, EnvioAsignar,
    EnvioCrear, EnvioEventoLeer, EnvioLeer, EnvioActualizarEstado,
)

router = APIRouter(prefix="/envios", tags=["envios"])

def _obtener_envio_o_404(db: Session, envio_id: uuid.UUID) -> Envio:
    envio = db.query(Envio).filter(Envio.id == envio_id).first()
    if envio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Envío no encontrado")
    return envio

def _registrar_evento(db: Session, envio_id: uuid.UUID, tipo_evento: str, notas: Optional[str] = None) -> None:
    db.add(EnvioEvento(envio_id=envio_id, tipo_evento=tipo_evento, notas=notas))

@router.post("/", response_model=EnvioLeer, status_code=status.HTTP_201_CREATED)
async def crear_envio(payload: EnvioCrear, db: Session = Depends(get_db)):
    envio = Envio(**payload.model_dump())
    db.add(envio)
    db.commit()
    db.refresh(envio)
    _registrar_evento(db, envio.id, "creado")
    db.commit()

    await publish_event("shipment.created", {
        "envio_id": str(envio.id),
        "cliente_id": str(envio.cliente_id),
        "origen": envio.origen,
        "destino": envio.destino,
        "es_internacional": envio.es_internacional,
        "peso_kg": float(envio.peso_kg),
        "volumen_m3": float(envio.volumen_m3) if envio.volumen_m3 is not None else None,
        "fecha_limite_sla": envio.fecha_limite_sla,
    })
    return envio

@router.get("/", response_model=list[EnvioLeer])
def listar_envios(estado: Optional[str] = None, cliente_id: Optional[uuid.UUID] = None, db: Session = Depends(get_db)):
    query = db.query(Envio)
    if estado:
        query = query.filter(Envio.estado == estado)
    if cliente_id:
        query = query.filter(Envio.cliente_id == cliente_id)
    return query.order_by(Envio.creado_en.desc()).all()

@router.get("/{envio_id}", response_model=EnvioLeer)
def obtener_envio(envio_id: uuid.UUID, db: Session = Depends(get_db)):
    return _obtener_envio_o_404(db, envio_id)

@router.get("/{envio_id}/eventos", response_model=list[EnvioEventoLeer])
def obtener_eventos_envio(envio_id: uuid.UUID, db: Session = Depends(get_db)):
    _obtener_envio_o_404(db, envio_id)
    return (
        db.query(EnvioEvento)
        .filter(EnvioEvento.envio_id == envio_id)
        .order_by(EnvioEvento.fecha_hora.asc())
        .all()
    )

@router.patch("/{envio_id}/asignar", response_model=EnvioLeer)
def asignar_envio(envio_id: uuid.UUID, payload: EnvioAsignar, db: Session = Depends(get_db)):
    envio = _obtener_envio_o_404(db, envio_id)
    envio.vehiculo_id = payload.vehiculo_id
    envio.ruta_id = payload.ruta_id
    _registrar_evento(db, envio.id, "asignado", notas=f"vehiculo_id={payload.vehiculo_id}")
    db.commit()
    db.refresh(envio)
    return envio

@router.patch("/{envio_id}/estado", response_model=EnvioLeer)
async def actualizar_estado_envio(envio_id: uuid.UUID, payload: EnvioActualizarEstado, db: Session = Depends(get_db)):
    envio = _obtener_envio_o_404(db, envio_id)
    envio.estado = payload.estado
    _registrar_evento(db, envio.id, payload.estado, notas=payload.notas)
    db.commit()
    db.refresh(envio)

    if payload.estado == "con_incidencia":
        await publish_event("shipment.incident", {"envio_id": str(envio.id), "notas": payload.notas})
    elif payload.estado == "devuelto":
        await publish_event("shipment.returned", {"envio_id": str(envio.id), "notas": payload.notas})
    return envio

@router.post("/{envio_id}/prueba-entrega", response_model=PruebaEntregaLeer, status_code=status.HTTP_201_CREATED)
async def registrar_prueba_entrega(envio_id: uuid.UUID, payload: PruebaEntregaCrear, db: Session = Depends(get_db)):
    envio = _obtener_envio_o_404(db, envio_id)
    existente = db.query(PruebaEntrega).filter(PruebaEntrega.envio_id == envio_id).first()
    if existente is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este envío ya tiene una prueba de entrega registrada")

    prueba = PruebaEntrega(envio_id=envio_id, **payload.model_dump())
    db.add(prueba)
    envio.estado = "entregado"
    _registrar_evento(db, envio.id, "entregado", notas=f"receptor={payload.nombre_receptor}")
    db.commit()
    db.refresh(prueba)
    db.refresh(envio)

    await publish_event("shipment.delivered", {
        "envio_id": str(envio.id),
        "entregado_en": prueba.entregado_en,
        "nombre_receptor": prueba.nombre_receptor,
    })
    return prueba