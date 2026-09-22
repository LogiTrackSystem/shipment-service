import json
import logging
import os
from typing import Any, Optional

import aio_pika
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("shipment-service.events")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
EXCHANGE_NAME = "logitrack_events"

_connection: Optional[aio_pika.RobustConnection] = None
_exchange: Optional[aio_pika.abc.AbstractExchange] = None

async def get_exchange() -> aio_pika.abc.AbstractExchange:
    global _connection, _exchange
    if _exchange is not None and _connection is not None and not _connection.is_closed:
        return _exchange
    _connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await _connection.channel()
    _exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    return _exchange

async def publish_event(routing_key: str, payload: dict[str, Any]) -> None:
    try:
        exchange = await get_exchange()
        message = aio_pika.Message(
            body=json.dumps(payload, default=str).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=routing_key)
        logger.info("Evento publicado: %s -> %s", routing_key, payload.get("envio_id"))
    except Exception as exc:
        logger.warning("No se pudo publicar el evento '%s': %s", routing_key, exc)

async def check_rabbitmq() -> bool:
    try:
        await get_exchange()
        return True
    except Exception:
        return False

async def close_connection() -> None:
    global _connection
    if _connection is not None and not _connection.is_closed:
        await _connection.close()