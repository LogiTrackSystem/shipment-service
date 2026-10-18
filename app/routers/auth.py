from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..jwt_simple import crear_token
from ..models import Usuario
from ..schemas import LoginSolicitud, TokenRespuesta, UsuarioLeer
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
