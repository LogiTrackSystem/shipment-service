import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cliente, Usuario
from ..schemas import UsuarioActualizar, UsuarioCrear, UsuarioLeer
from ..seguridad import hashear_password, requerir_roles

# Gestión de cuentas: solo el administrador (se exige también aquí, no solo en el gateway)
router = APIRouter(prefix="/usuarios", tags=["usuarios"], dependencies=[Depends(requerir_roles("administrador"))])


@router.post("/", response_model=UsuarioLeer, status_code=201)
def crear_usuario(payload: UsuarioCrear, db: Session = Depends(get_db)):
    cliente_id = None
    if payload.rol == "cliente":
        if payload.codigo_cliente is not None:
            cliente = db.query(Cliente).filter(Cliente.codigo_cliente == payload.codigo_cliente).first()
        elif payload.cliente_id is not None:
            cliente = db.query(Cliente).filter(Cliente.id == payload.cliente_id).first()
        else:
            raise HTTPException(status_code=422, detail="Una cuenta de cliente requiere cliente_id o codigo_cliente")
        if cliente is None:
            raise HTTPException(status_code=422, detail="El cliente indicado no existe")
        cliente_id = cliente.id
    elif payload.cliente_id is not None or payload.codigo_cliente is not None:
        raise HTTPException(status_code=422, detail="Solo las cuentas con rol 'cliente' se ligan a un cliente")

    usuario = Usuario(
        email=payload.email,
        nombre=payload.nombre.strip(),
        password_hash=hashear_password(payload.password),
        rol=payload.rol,
        cliente_id=cliente_id,
    )
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo")
    db.refresh(usuario)
    return usuario


@router.get("/", response_model=list[UsuarioLeer])
def listar_usuarios(rol: str | None = None, limite: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    query = db.query(Usuario)
    if rol:
        query = query.filter(Usuario.rol == rol)
    return query.order_by(Usuario.creado_en.desc()).limit(limite).all()


@router.patch("/{usuario_id}", response_model=UsuarioLeer)
def actualizar_usuario(usuario_id: uuid.UUID, payload: UsuarioActualizar, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    cambios = payload.model_dump(exclude_unset=True)
    if "password" in cambios:
        usuario.password_hash = hashear_password(cambios.pop("password"))
    for campo, valor in cambios.items():
        if valor is not None:
            setattr(usuario, campo, valor)
    db.commit()
    db.refresh(usuario)
    return usuario
