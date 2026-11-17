import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from .interno import proteger_servicio

from .routers import auth, clientes, envios, usuarios
from .events import iniciar_consumidor
from .programacion import bucle_programacion


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection = await iniciar_consumidor()
    vigilante = asyncio.create_task(bucle_programacion())  # arranca los envíos programados a su hora
    yield
    vigilante.cancel()
    await connection.close()


app = FastAPI(title="Shipment Service", lifespan=lifespan)
proteger_servicio(app)
app.include_router(envios.router)
app.include_router(clientes.router)
app.include_router(auth.router)
app.include_router(usuarios.router)


# Métricas para Prometheus (GET /metrics): peticiones por método/estado y tiempos de respuesta
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)


@app.get("/health")
def health():
    return {"status": "ok", "service": "shipment-service", "version": os.getenv("APP_VERSION", "dev")}