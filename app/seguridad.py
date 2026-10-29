"""Contraseñas, contexto de usuario y control de acceso del Shipment Service.

- Shipment guarda los usuarios y firma los tokens (POST /auth/login).
- El API Gateway verifica el token y reenvía a los servicios la identidad en cabeceras
  (X-User-Id, X-User-Rol, X-Cliente-Id). Aquí se leen para aplicar la propiedad del recurso.
- Una petición SIN esas cabeceras es una llamada interna entre servicios y no se restringe.
"""
import base64
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request

ROLES = ("cliente", "operador", "gestor_flota", "administrador")
ITERACIONES = 240_000


# ---------- Contraseñas ----------

def hashear_password(password: str) -> str:
    sal = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, ITERACIONES)
    return "pbkdf2_sha256${}${}${}".format(
        ITERACIONES, base64.b64encode(sal).decode(), base64.b64encode(derivado).decode()
    )


def verificar_password(password: str, guardado: str) -> bool:
    try:
        algoritmo, iteraciones, sal_b64, hash_b64 = guardado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        derivado = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(sal_b64), int(iteraciones)
        )
        return hmac.compare_digest(derivado, base64.b64decode(hash_b64))
    except Exception:
        return False


# ---------- Configuración del token ----------

def secreto_jwt() -> str:
    valor = os.getenv("JWT_SECRET", "").strip()
    if len(valor) < 16:
        raise HTTPException(
            status_code=503,
            detail={"codigo": "JWT_NO_CONFIGURADO", "mensaje": "Falta JWT_SECRET (mínimo 16 caracteres) en Shipment Service"},
        )
    return valor


def vigencia_token_s() -> int:
    return int(os.getenv("JWT_VIGENCIA_MIN", "480")) * 60


# ---------- Contexto de la petición ----------

@dataclass(frozen=True)
class Contexto:
    rol: Optional[str] = None          # None = llamada interna entre servicios
    usuario_id: Optional[uuid.UUID] = None
    cliente_id: Optional[uuid.UUID] = None

    @property
    def interno(self) -> bool:
        return self.rol is None

    @property
    def es_cliente(self) -> bool:
        return self.rol == "cliente"


def _uuid_o_none(valor: Optional[str]):
    try:
        return uuid.UUID(valor) if valor else None
    except ValueError:
        return None


def obtener_contexto(request: Request) -> Contexto:
    rol = request.headers.get("x-user-rol")
    if rol is not None and rol not in ROLES:
        raise HTTPException(status_code=403, detail={"codigo": "SIN_PERMISO", "mensaje": "Rol no reconocido"})
    ctx = Contexto(
        rol=rol,
        usuario_id=_uuid_o_none(request.headers.get("x-user-id")),
        cliente_id=_uuid_o_none(request.headers.get("x-cliente-id")),
    )
    if ctx.es_cliente and ctx.cliente_id is None:
        raise HTTPException(status_code=403, detail={"codigo": "SIN_PERMISO", "mensaje": "La cuenta de cliente no está ligada a un cliente"})
    return ctx


def requerir_roles(*roles: str):
    """Dependencia ESTRICTA: exige una identidad con uno de los roles (no admite llamadas internas)."""
    def dependencia(ctx: Contexto = Depends(obtener_contexto)) -> Contexto:
        if ctx.rol not in roles:
            raise HTTPException(
                status_code=403,
                detail={"codigo": "SIN_PERMISO", "mensaje": "Su rol no tiene permiso para esta operación"},
            )
        return ctx
    return dependencia
