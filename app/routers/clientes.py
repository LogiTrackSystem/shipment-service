import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cliente
from ..schemas import ClienteActualizar, ClienteCrear, ClienteLeer
from ..seguridad import Contexto, obtener_contexto

router = APIRouter(prefix="/clientes", tags=["clientes"])


def _no_cliente(ctx: Contexto) -> None:
    if ctx.es_cliente:
        raise HTTPException(
            status_code=403,
            detail={"codigo": "SIN_PERMISO", "mensaje": "Su rol no puede crear ni modificar clientes"},
        )


def _ajeno(ctx: Contexto, cliente: Cliente) -> bool:
    """Una cuenta de cliente solo puede ver su propio registro (los demás responden 404)."""
    return ctx.es_cliente and cliente.id != ctx.cliente_id


@router.post("/", response_model=ClienteLeer, status_code=201)
def crear_cliente(payload: ClienteCrear, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    _no_cliente(ctx)
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
    ctx: Contexto = Depends(obtener_contexto),
):
    """Búsqueda para el selector del frontend: por nombre, documento o código de cliente.
    Una cuenta de cliente solo ve su propio registro."""
    query = db.query(Cliente)
    if ctx.es_cliente:
        query = query.filter(Cliente.id == ctx.cliente_id)
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
def obtener_cliente_por_codigo(codigo: int, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    cliente = db.query(Cliente).filter(Cliente.codigo_cliente == codigo).first()
    if cliente is None or _ajeno(ctx, cliente):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.get("/{cliente_id}", response_model=ClienteLeer)
def obtener_cliente(cliente_id: uuid.UUID, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if cliente is None or _ajeno(ctx, cliente):
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.patch("/{cliente_id}", response_model=ClienteLeer)
def actualizar_cliente(
    cliente_id: uuid.UUID, payload: ClienteActualizar, db: Session = Depends(get_db),
    ctx: Contexto = Depends(obtener_contexto),
):
    _no_cliente(ctx)
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