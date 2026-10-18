import os

import httpx
from .interno import cabeceras_internas
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

FLEET_SERVICE_URL = os.getenv("FLEET_SERVICE_URL")
TIMEOUT_S = 5.0


async def verificar_viabilidad(peso_kg, volumen_m3, tipo_carga, es_hazmat, es_divisible=False, lanzar=True):
    """Rechaza (422) un envío que la flota no podría transportar jamás (ni dividido, si es divisible).
    Devuelve la respuesta de Fleet (con 'requiere_division', 'partes'...) o None si no se pudo consultar.
    Con lanzar=False no rechaza: solo devuelve el diagnóstico (lo usa la cotización).
    Si Fleet no responde NO se bloquea la creación: la Saga de asignación lo resolverá después."""
    if not FLEET_SERVICE_URL:
        return None
    cuerpo = {
        "peso_kg": float(peso_kg), "tipo_carga": tipo_carga,
        "es_hazmat": bool(es_hazmat), "es_divisible": bool(es_divisible),
    }
    if volumen_m3 is not None:
        cuerpo["volumen_m3"] = float(volumen_m3)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, headers=cabeceras_internas()) as client:
            resp = await client.post(f"{FLEET_SERVICE_URL}/reservas/viabilidad", json=cuerpo)
    except httpx.HTTPError as exc:
        print(f"[shipment] no se pudo consultar la viabilidad en Fleet (se acepta el envío): {type(exc).__name__}")
        return None
    if resp.status_code != 200:
        print(f"[shipment] Fleet respondió HTTP {resp.status_code} a la viabilidad (se acepta el envío)")
        return None
    datos = resp.json()
    if lanzar and not datos.get("viable", True):
        raise HTTPException(
            status_code=422,
            detail={
                "codigo": datos.get("causa") or "SIN_VEHICULO_COMPATIBLE",
                "mensaje": datos.get("mensaje") or "Ningún vehículo de la flota puede transportar esta carga",
                "capacidad_maxima_kg": datos.get("capacidad_maxima_kg"),
                "requiere_division": datos.get("requiere_division", False),
                "division_posible": datos.get("division_posible", False),
            },
        )
    return datos