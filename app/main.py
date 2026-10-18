import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
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


@app.get("/health")
def health():
    return {"status": "ok", "service": "shipment-service"}