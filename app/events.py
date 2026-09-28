import json
import os
import uuid

import aio_pika
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Envio, EnvioEvento

RABBITMQ_URL = os.getenv("RABBITMQ_URL")
EXCHANGE_NAME = "logitrack_events"


async def publish_event(routing_key: str, payload: dict):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        message = aio_pika.Message(
            body=json.dumps(payload, default=str).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=routing_key)


async def _procesar_customs_held(payload: dict):
    """Cierra el hueco de Customs Service: cuando aduanas retiene un envío
    internacional, Shipment Service refleja esa retención en su propio
    estado (sin que Customs escriba directamente en esta base de datos —
    Database per Service se mantiene, la comunicación es por evento)."""
    db: Session = SessionLocal()
    try:
        envio_id = uuid.UUID(payload["envio_id"])
        envio = db.query(Envio).filter(Envio.id == envio_id).first()
        if envio is None:
            return
        envio.estado = "retenido_aduana"
        db.add(EnvioEvento(
            envio_id=envio.id,
            tipo_evento="retenido_aduana",
            notas=payload.get("motivo_retencion", "retenido en aduana"),
        ))
        db.commit()
    finally:
        db.close()


async def _procesar_customs_cleared(payload: dict):
    db: Session = SessionLocal()
    try:
        envio_id = uuid.UUID(payload["envio_id"])
        envio = db.query(Envio).filter(Envio.id == envio_id).first()
        if envio is None:
            return
        if envio.estado == "retenido_aduana":
            envio.estado = "en_transito"
        db.add(EnvioEvento(
            envio_id=envio.id,
            tipo_evento="liberado_aduana",
            notas="declaración aduanera aprobada",
        ))
        db.commit()
    finally:
        db.close()


_HANDLERS = {
    "customs.held": _procesar_customs_held,
    "customs.cleared": _procesar_customs_cleared,
}


async def _on_message(message: aio_pika.IncomingMessage):
    async with message.process():
        payload = json.loads(message.body.decode())
        handler = _HANDLERS.get(message.routing_key)
        if handler:
            await handler(payload)


async def iniciar_consumidor():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue("shipment_service.eventos", durable=True)
    await queue.bind(exchange, routing_key="customs.held")
    await queue.bind(exchange, routing_key="customs.cleared")
    await queue.consume(_on_message)
    return connection