import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cliente
from ..schemas import ClienteActualizar, ClienteCrear, ClienteLeer

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.post("/", response_model=ClienteLeer, status_code=201)
def crear_cliente(payload: ClienteCrear, db: Session = Depends(get_db)):
    cliente = Cliente(**payload.model_dump())
    db.add(cliente)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un cliente con ese tipo y número de documento")
    db.refresh(cliente)
    return cliente


@router.get("/", response_model=list[ClienteLeer])
def listar_clientes(
    q: Optional[str] = None,
    activo: Optional[bool] = None,
    limite: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Búsqueda para el selector del frontend: por nombre, documento o código de cliente."""
    query = db.query(Cliente)
    if activo is not None:
        query = query.filter(Cliente.activo == activo)
    if q:
        q = q.strip()
        query = query.filter(
            or_(
                Cliente.nombre.ilike(f"%{q}%"),
                Cliente.numero_documento.ilike(f"%{q}%"),
                cast(Cliente.codigo_cliente, String).like(f"{q}%"),
            )
        )
    return query.order_by(Cliente.nombre.asc()).limit(limite).all()


@router.get("/codigo/{codigo}", response_model=ClienteLeer)
def obtener_cliente_por_codigo(codigo: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.codigo_cliente == codigo).first()
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.get("/{cliente_id}", response_model=ClienteLeer)
def obtener_cliente(cliente_id: uuid.UUID, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.patch("/{cliente_id}", response_model=ClienteLeer)
def actualizar_cliente(cliente_id: uuid.UUID, payload: ClienteActualizar, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if cliente is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    cambios = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    for campo, valor in cambios.items():
        setattr(cliente, campo, valor)

    if (cliente.tipo_documento is None) != (cliente.numero_documento is None):
        db.rollback()
        raise HTTPException(status_code=422, detail="tipo_documento y numero_documento deben enviarse juntos")
    if cliente.numero_documento:
        cliente.es_historico = False

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe un cliente con ese tipo y número de documento")
    db.refresh(cliente)
    return cliente