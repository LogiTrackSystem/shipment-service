import asyncio
import json
import os
import uuid
from datetime import datetime

import aio_pika
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import SessionLocal
from .estados import ESTADOS_ENTREGABLES, ESTADOS_FINALES
from .models import Envio, EnvioEvento, PruebaEntrega

RABBITMQ_URL = os.getenv("RABBITMQ_URL")
EXCHANGE_NAME = "logitrack_events"
ENTREGA_AUTOMATICA = os.getenv("ENTREGA_AUTOMATICA", "true").strip().lower() in ("1", "true", "si", "sí", "yes")
RECEPTOR_SIMULADO = "Entrega simulada automática"


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


def _a_uuid(valor):
    try:
        return uuid.UUID(str(valor))
    except (ValueError, TypeError):
        return None


def _a_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError:
        return None


def _buscar_envio(db: Session, envio_id):
    """Busca el envío bloqueando su fila, para que dos eventos simultáneos no se pisen."""
    if envio_id is None:
        return None
    return db.query(Envio).filter(Envio.id == envio_id).with_for_update(of=Envio).first()


# ---------- Saga de asignación (eventos de Routing) ----------

async def _procesar_route_assigned(payload: dict):
    ruta_id = _a_uuid(payload.get("ruta_id"))
    db: Session = SessionLocal()
    try:
        envio = _buscar_envio(db, _a_uuid(payload.get("envio_id")))
        if envio is None or ruta_id is None or envio.estado in ESTADOS_FINALES:
            return
        if envio.ruta_id == ruta_id:
            return  # mensaje repetido: ya estaba aplicado

        envio.ruta_id = ruta_id
        envio.vehiculo_id = _a_uuid(payload.get("vehiculo_id"))
        envio.conductor_id = _a_uuid(payload.get("conductor_id"))
        envio.placa_vehiculo = payload.get("placa")
        envio.tipo_vehiculo = payload.get("tipo_vehiculo")
        envio.conductor_nombre = payload.get("conductor_nombre")
        envio.codigo_conductor = payload.get("codigo_conductor")
        envio.hora_estimada_llegada = _a_fecha(payload.get("hora_estimada_llegada"))
        envio.motivo_sin_asignacion = None

        if envio.estado in ("pendiente", "sin_asignacion"):
            envio.estado = "asignado"
        elif envio.estado == "retenido_aduana":
            envio.estado_previo = "asignado"  # al liberar aduana, vuelve a 'asignado'

        db.add(EnvioEvento(
            envio_id=envio.id,
            tipo_evento="asignado",
            notas=(
                f"vehículo {payload.get('placa')}, conductor {payload.get('conductor_nombre')}, "
                f"ruta {payload.get('codigo_ruta')}"
            ),
        ))
        db.commit()
    finally:
        db.close()


async def _procesar_route_unassigned(payload: dict):
    motivo = payload.get("motivo")
    db: Session = SessionLocal()
    try:
        envio = _buscar_envio(db, _a_uuid(payload.get("envio_id")))
        if envio is None:
            return
        if envio.estado == "retenido_aduana":
            if envio.estado_previo in (None, "pendiente", "sin_asignacion"):
                envio.estado_previo = "sin_asignacion"
        elif envio.estado in ("pendiente", "sin_asignacion"):
            if envio.estado == "sin_asignacion" and envio.motivo_sin_asignacion == motivo:
                return  # mismo aviso repetido
            envio.estado = "sin_asignacion"
        else:
            return  # aviso atrasado: el envío ya avanzó o terminó
        envio.motivo_sin_asignacion = motivo
        db.add(EnvioEvento(envio_id=envio.id, tipo_evento="sin_asignacion", notas=motivo))
        db.commit()
    finally:
        db.close()


# ---------- Aduanas ----------

async def _procesar_customs_held(payload: dict):
    """Cuando aduanas retiene un envío internacional, Shipment refleja esa retención
    y recuerda el estado anterior para volver a él cuando se libere."""
    db: Session = SessionLocal()
    try:
        envio = _buscar_envio(db, _a_uuid(payload.get("envio_id")))
        if envio is None or envio.estado in ESTADOS_FINALES or envio.estado == "retenido_aduana":
            return
        envio.estado_previo = envio.estado
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
        envio = _buscar_envio(db, _a_uuid(payload.get("envio_id")))
        if envio is None:
            return
        if envio.estado == "retenido_aduana":
            envio.estado = envio.estado_previo or "pendiente"
            envio.estado_previo = None
        db.add(EnvioEvento(
            envio_id=envio.id,
            tipo_evento="liberado_aduana",
            notas="declaración aduanera aprobada",
        ))
        db.commit()
    finally:
        db.close()


async def _publicar_con_reintentos(routing_key: str, payload: dict, intentos: int = 3):
    for n in range(1, intentos + 1):
        try:
            await publish_event(routing_key, payload)
            return
        except Exception as exc:
            print(f"[shipment] no se pudo publicar {routing_key} (intento {n}/{intentos}): {exc}")
            if n < intentos:
                await asyncio.sleep(n)


# ---------- Viaje simulado (eventos de Tracking) ----------

async def _procesar_trip_started(payload: dict):
    db: Session = SessionLocal()
    try:
        envio = _buscar_envio(db, _a_uuid(payload.get("envio_id")))
        if envio is None or envio.estado in ESTADOS_FINALES:
            return
        eta = _a_fecha(payload.get("hora_estimada_llegada"))
        if eta is not None:
            envio.hora_estimada_llegada = eta
        if envio.estado == "asignado":
            envio.estado = "en_transito"
            db.add(EnvioEvento(
                envio_id=envio.id,
                tipo_evento="en_transito",
                notas=f"el vehículo {payload.get('placa')} salió hacia {envio.destino}",
            ))
        elif envio.estado == "retenido_aduana":
            envio.estado_previo = "en_transito"  # al liberar aduana, el viaje ya estaba en marcha
        db.commit()
    finally:
        db.close()


async def _procesar_trip_arrived(payload: dict):
    entrega = None
    db: Session = SessionLocal()
    try:
        envio = _buscar_envio(db, _a_uuid(payload.get("envio_id")))
        if envio is None or envio.estado not in ESTADOS_ENTREGABLES:
            return
        db.add(EnvioEvento(
            envio_id=envio.id,
            tipo_evento="llegada_destino",
            notas=f"el vehículo {payload.get('placa')} llegó a {envio.destino}",
        ))
        ya_tiene_prueba = db.query(PruebaEntrega).filter(PruebaEntrega.envio_id == envio.id).first() is not None
        if ENTREGA_AUTOMATICA and not ya_tiene_prueba:
            prueba = PruebaEntrega(envio_id=envio.id, nombre_receptor=RECEPTOR_SIMULADO, simulada=True)
            db.add(prueba)
            envio.estado = "entregado"
            envio.estado_previo = None
            db.add(EnvioEvento(
                envio_id=envio.id,
                tipo_evento="entregado",
                notas=f"receptor={RECEPTOR_SIMULADO} (prueba de entrega simulada)",
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # un operador registró la entrega al mismo tiempo
                return
            db.refresh(prueba)
            entrega = {
                "envio_id": str(envio.id),
                "entregado_en": prueba.entregado_en,
                "nombre_receptor": prueba.nombre_receptor,
                "simulada": True,
            }
        else:
            db.commit()
    finally:
        db.close()

    if entrega:
        # Routing escucha este evento: libera la reserva en Fleet y reasigna a los envíos en espera
        await _publicar_con_reintentos("shipment.delivered", entrega)

_HANDLERS = {
    "route.assigned": _procesar_route_assigned,
    "route.unassigned": _procesar_route_unassigned,
    "customs.held": _procesar_customs_held,
    "customs.cleared": _procesar_customs_cleared,
    "tracking.trip_started": _procesar_trip_started,
    "tracking.trip_arrived": _procesar_trip_arrived,
}


async def _on_message(message: aio_pika.IncomingMessage):
    async with message.process():
        payload = json.loads(message.body.decode())
        handler = _HANDLERS.get(message.routing_key)
        if handler:
            try:
                await handler(payload)
            except Exception as exc:
                print(f"[shipment] error procesando {message.routing_key}: {exc}")


async def iniciar_consumidor():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue("shipment_service.eventos", durable=True)
    for clave in _HANDLERS:
        await queue.bind(exchange, routing_key=clave)
    await queue.consume(_on_message)
    return connection