import os

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

FLEET_SERVICE_URL = os.getenv("FLEET_SERVICE_URL")
TIMEOUT_S = 5.0


async def verificar_viabilidad(peso_kg, volumen_m3, tipo_carga, es_hazmat) -> None:
    """Rechaza (422) un envío que ninguna pareja vehículo+conductor de la flota podría transportar jamás.
    Si Fleet no responde NO se bloquea la creación: la Saga de asignación lo resolverá después."""
    if not FLEET_SERVICE_URL:
        return
    cuerpo = {"peso_kg": float(peso_kg), "tipo_carga": tipo_carga, "es_hazmat": bool(es_hazmat)}
    if volumen_m3 is not None:
        cuerpo["volumen_m3"] = float(volumen_m3)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(f"{FLEET_SERVICE_URL}/reservas/viabilidad", json=cuerpo)
    except httpx.HTTPError as exc:
        print(f"[shipment] no se pudo consultar la viabilidad en Fleet (se acepta el envío): {type(exc).__name__}")
        return
    if resp.status_code != 200:
        print(f"[shipment] Fleet respondió HTTP {resp.status_code} a la viabilidad (se acepta el envío)")
        return
    datos = resp.json()
    if not datos.get("viable", True):
        raise HTTPException(
            status_code=422,
            detail={
                "codigo": datos.get("causa") or "SIN_VEHICULO_COMPATIBLE",
                "mensaje": datos.get("mensaje") or "Ningún vehículo de la flota puede transportar esta carga",
            },
        )