"""Registro público de cuentas (POST /auth/registro).

- Cualquier persona puede registrarse como CLIENTE: se le crea su registro de cliente (el código de cliente lo
  asigna la base de datos, nadie lo digita) y su cuenta de acceso, todo en una sola operación.
- Para ser OPERADOR o GESTOR DE FLOTA hace falta un código de acceso que solo conoce el administrador
  (variable de entorno CODIGO_REGISTRO_PERSONAL). Sin ese código no se puede crear ninguna cuenta de trabajo.
- El rol ADMINISTRADOR nunca se crea por aquí: solo lo crea otro administrador (POST /usuarios) o, el primero,
  desde la terminal (python -m app.crear_usuario).

Los intentos fallidos con el código de acceso se limitan: pasados REGISTRO_MAX_FALLOS fallos dentro de
REGISTRO_VENTANA_S segundos, el registro de personal responde 429 hasta que la ventana se vacíe.
"""
import hmac
import os
import threading
import time
from collections import deque
from typing import Optional

from fastapi import HTTPException

LARGO_MINIMO_CODIGO = 8

_fallos: deque = deque()
_cerrojo = threading.Lock()


def _entero_env(nombre: str, defecto: int) -> int:
    try:
        return max(1, int(os.getenv(nombre, str(defecto))))
    except ValueError:
        return defecto


def codigo_personal_configurado() -> str:
    """Código vigente, o cadena vacía si el administrador no lo definió (o es demasiado corto)."""
    valor = os.getenv("CODIGO_REGISTRO_PERSONAL", "").strip()
    return valor if len(valor) >= LARGO_MINIMO_CODIGO else ""


def reiniciar_limite() -> None:
    with _cerrojo:
        _fallos.clear()


def validar_codigo_personal(enviado: Optional[str]) -> None:
    """Lanza HTTPException si el código no corresponde. No devuelve nada cuando es correcto."""
    esperado = codigo_personal_configurado()
    if not esperado:
        raise HTTPException(
            status_code=403,
            detail={
                "codigo": "REGISTRO_PERSONAL_DESHABILITADO",
                "mensaje": "El registro de operadores y gestores no está habilitado. Pida su cuenta al administrador.",
            },
        )
    maximo = _entero_env("REGISTRO_MAX_FALLOS", 8)
    ventana = _entero_env("REGISTRO_VENTANA_S", 600)
    with _cerrojo:
        ahora = time.monotonic()
        while _fallos and ahora - _fallos[0] > ventana:
            _fallos.popleft()
        if len(_fallos) >= maximo:
            espera = max(1, int(ventana - (ahora - _fallos[0])))
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": str(espera)},
                detail={
                    "codigo": "DEMASIADOS_INTENTOS",
                    "mensaje": f"Demasiados intentos con el código de acceso. Intente de nuevo en {espera} segundos.",
                },
            )
        correcto = bool(enviado) and hmac.compare_digest(enviado.encode("utf-8"), esperado.encode("utf-8"))
        if not correcto:
            _fallos.append(ahora)
    if not correcto:
        raise HTTPException(
            status_code=403,
            detail={"codigo": "CODIGO_ACCESO_INVALIDO", "mensaje": "El código de acceso no es válido"},
        )
