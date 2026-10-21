from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..jwt_simple import crear_token
from ..models import Cliente, Usuario
from ..registro import validar_codigo_personal
from ..schemas import LoginSolicitud, RegistroSolicitud, TokenRespuesta, UsuarioLeer
from ..seguridad import Contexto, hashear_password, obtener_contexto, secreto_jwt, verificar_password, vigencia_token_s

router = APIRouter(prefix="/auth", tags=["auth"])

# Hash de relleno: se verifica siempre una contraseña, exista o no el usuario, para no revelar cuentas por el tiempo de respuesta
_HASH_RELLENO = hashear_password("relleno-no-valido")


@router.post("/login", response_model=TokenRespuesta)
def iniciar_sesion(payload: LoginSolicitud, db: Session = Depends(get_db)):
    """Inicia sesión y devuelve un token Bearer. Envíelo en `Authorization: Bearer <token>`."""
    secreto = secreto_jwt()
    usuario = db.query(Usuario).filter(Usuario.email == payload.email).first()
    valido = verificar_password(payload.password, usuario.password_hash if usuario else _HASH_RELLENO)
    if usuario is None or not valido or not usuario.activo:
        raise HTTPException(
            status_code=401,
            detail={"codigo": "CREDENCIALES_INVALIDAS", "mensaje": "Correo o contraseña incorrectos"},
        )
    usuario.ultimo_acceso = datetime.now(timezone.utc)
    db.commit()
    db.refresh(usuario)
    return _emitir_token(usuario, secreto)


def _emitir_token(usuario: Usuario, secreto: str) -> TokenRespuesta:
    vigencia = vigencia_token_s()
    token = crear_token(
        {
            "sub": str(usuario.id),
            "rol": usuario.rol,
            "cliente_id": str(usuario.cliente_id) if usuario.cliente_id else None,
            "nombre": usuario.nombre,
        },
        secreto,
        vigencia,
    )
    return TokenRespuesta(access_token=token, expires_in=vigencia, usuario=UsuarioLeer.model_validate(usuario))


def _conflicto(codigo: str, mensaje: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"codigo": codigo, "mensaje": mensaje})


@router.post("/registro", response_model=TokenRespuesta, status_code=201)
def registrarse(payload: RegistroSolicitud, db: Session = Depends(get_db)):
    """Alta pública de cuenta (no requiere sesión) y devuelve el token, igual que el login.

    - `rol: "cliente"` (por defecto): crea el cliente y su cuenta. El código de cliente lo asigna el sistema
      y llega en `usuario.codigo_cliente`.
    - `rol: "operador"` o `"gestor_flota"`: requiere `codigo_acceso`, el código que solo conoce el administrador.
    - `administrador` no se puede crear por aquí.
    """
    secreto = secreto_jwt()
    if payload.rol != "cliente":
        validar_codigo_personal(payload.codigo_acceso)  # primero el código: sin él no se revela nada más

    if db.query(Usuario.id).filter(Usuario.email == payload.email).first() is not None:
        raise _conflicto("CORREO_YA_REGISTRADO", "Ya existe una cuenta con ese correo")

    cliente = None
    if payload.rol == "cliente":
        # Si el documento ya pertenece a un cliente existente NO se le liga la cuenta nueva: así nadie puede
        # adueñarse del historial de otro cliente. Quien ya es cliente pide que el administrador le cree la cuenta.
        existente = (
            db.query(Cliente.id)
            .filter(Cliente.tipo_documento == payload.tipo_documento, Cliente.numero_documento == payload.numero_documento)
            .first()
        )
        if existente is not None:
            raise _conflicto(
                "CLIENTE_YA_REGISTRADO",
                "Ya existe un cliente con ese documento. Si ya es cliente de LogiTrack, pida al administrador que le cree el acceso.",
            )
        cliente = Cliente(
            nombre=payload.nombre,
            tipo_documento=payload.tipo_documento,
            numero_documento=payload.numero_documento,
            email=payload.email,
            telefono=payload.telefono,
            direccion=payload.direccion,
        )
        db.add(cliente)
        db.flush()  # obtiene el id (el código de cliente lo pone la secuencia de la base de datos)

    usuario = Usuario(
        email=payload.email,
        nombre=payload.nombre,
        password_hash=hashear_password(payload.password),
        rol=payload.rol,
        cliente_id=cliente.id if cliente is not None else None,
        ultimo_acceso=datetime.now(timezone.utc),
    )
    db.add(usuario)
    try:
        db.commit()  # cliente y cuenta se guardan juntos o no se guarda ninguno
    except IntegrityError:
        db.rollback()
        raise _conflicto("REGISTRO_DUPLICADO", "Ya existe una cuenta o un cliente con esos datos")
    db.refresh(usuario)
    return _emitir_token(usuario, secreto)


@router.get("/me", response_model=UsuarioLeer)
def mi_perfil(ctx: Contexto = Depends(obtener_contexto), db: Session = Depends(get_db)):
    """Datos de la cuenta con la que se hizo la petición."""
    if ctx.usuario_id is None:
        raise HTTPException(
            status_code=401,
            detail={"codigo": "NO_AUTENTICADO", "mensaje": "Debe iniciar sesión"},
        )
    usuario = db.query(Usuario).filter(Usuario.id == ctx.usuario_id).first()
    if usuario is None or not usuario.activo:
        raise HTTPException(
            status_code=401,
            detail={"codigo": "NO_AUTENTICADO", "mensaje": "La cuenta ya no está activa"},
        )
    return usuario
