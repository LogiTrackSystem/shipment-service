import os
from typing import Optional

import httpx
from .interno import cabeceras_internas
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

BILLING_SERVICE_URL = os.getenv("BILLING_SERVICE_URL")
TIMEOUT_S = 5.0


def facturacion_activa() -> bool:
    return bool(BILLING_SERVICE_URL)


def _no_disponible(motivo: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "codigo": "FACTURACION_NO_DISPONIBLE",
            "mensaje": f"No se pudo calcular el precio del pedido ({motivo}). Intente de nuevo en unos minutos.",
        },
    )


async def calcular_cotizacion(peso_kg, distancia_km, cliente_id=None) -> Optional[dict]:
    """Pide a Billing el precio en COP de un pedido. Devuelve None si el cobro no está configurado
    (no hay BILLING_SERVICE_URL). Si está configurado y Billing no responde, se rechaza con 503: sin
    precio verificado no se puede crear un pedido que debe cobrarse."""
    if not BILLING_SERVICE_URL:
        return None
    cuerpo = {"peso_kg": float(peso_kg), "distancia_km": float(distancia_km)}
    if cliente_id is not None:
        cuerpo["cliente_id"] = str(cliente_id)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=cabeceras_internas()) as client:
            resp = await client.post(f"{BILLING_SERVICE_URL}/cotizaciones/calcular", json=cuerpo)
    except httpx.HTTPError as exc:
        raise _no_disponible(type(exc).__name__)
    if resp.status_code not in (200, 201):
        raise _no_disponible(f"HTTP {resp.status_code}")
    return resp.json()
