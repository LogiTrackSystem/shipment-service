import os

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

ROUTING_SERVICE_URL = os.getenv("ROUTING_SERVICE_URL")
TIMEOUT_S = 60.0  # la primera vez que se pide un par nuevo, Routing consulta OSRM


async def obtener_ruta_maestra(origen_id, origen_codigo, destino_id, destino_codigo) -> dict:
    """Pide a Routing la ruta maestra del par origen→destino (la calcula si no existe).
    Si algo no es válido, traduce el motivo a un error claro para quien creó el envío."""
    if not ROUTING_SERVICE_URL:
        raise HTTPException(
            status_code=503,
            detail={"codigo": "ROUTING_NO_CONFIGURADO", "mensaje": "Falta ROUTING_SERVICE_URL en Shipment Service"},
        )

    cuerpo = {
        "origen_id": str(origen_id) if origen_id else None,
        "origen_codigo": origen_codigo,
        "destino_id": str(destino_id) if destino_id else None,
        "destino_codigo": destino_codigo,
    }
    cuerpo = {k: v for k, v in cuerpo.items() if v is not None}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            resp = await client.post(f"{ROUTING_SERVICE_URL}/rutas-maestras/calcular", json=cuerpo)
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail={
                "codigo": "ROUTING_NO_DISPONIBLE",
                "mensaje": "El servicio de rutas no responde. Intente de nuevo en unos segundos.",
            },
        )

    if resp.status_code in (200, 201):
        return resp.json()
    if resp.status_code == 422:
        try:
            detalle = resp.json().get("detail")
        except ValueError:
            detalle = None
        raise HTTPException(status_code=422, detail=detalle or "Origen o destino no válidos")
    raise HTTPException(
        status_code=502,
        detail={"codigo": "ROUTING_ERROR", "mensaje": f"El servicio de rutas respondió con error {resp.status_code}"},
    )