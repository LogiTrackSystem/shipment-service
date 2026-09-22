from fastapi import FastAPI

from .database import engine_healthcheck
from .events import check_rabbitmq, close_connection
from .routers import envios

app = FastAPI(title="Shipment Service")
app.include_router(envios.router)

@app.get("/health")
async def health():
    db_ok = engine_healthcheck()
    rabbitmq_ok = await check_rabbitmq()
    return {
        "status": "ok" if db_ok and rabbitmq_ok else "degraded",
        "service": "shipment-service",
        "dependencies": {
            "database": "ok" if db_ok else "down",
            "rabbitmq": "ok" if rabbitmq_ok else "down",
        },
    }

@app.on_event("shutdown")
async def shutdown_event():
    await close_connection()