"""Programación de envíos: validación de fechas y arranque automático a la hora indicada.

Un envío 'programado' no reserva ningún vehículo. A su hora, el vigilante publica shipment.created y
el envío pasa a 'pendiente': desde ahí sigue la Saga normal de asignación (Routing + Fleet).
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from .database import SessionLocal
from .events import publish_event
from .models import Envio, EnvioEvento
from .payloads import construir_payload_creado

INTERVALO_S = int(os.getenv("PROGRAMACION_INTERVALO_S", "30"))
LOTE = 50
ANTICIPACION_MINIMA = timedelta(minutes=1)
HORIZONTE_MAXIMO = timedelta(days=365)
HORA_COLOMBIA = timezone(timedelta(hours=-5))  # Colombia no tiene horario de verano


def normalizar_fecha(valor: datetime) -> datetime:
    """Sin zona horaria se interpreta como hora de Colombia; el resultado siempre trae zona."""
    return valor.replace(tzinfo=HORA_COLOMBIA) if valor.tzinfo is None else valor


def validar_fecha_programada(valor: Optional[datetime], fecha_limite_sla: Optional[datetime] = None,
                             ahora: Optional[datetime] = None) -> Optional[datetime]:
    if valor is None:
        return None
    ahora = ahora or datetime.now(timezone.utc)
    fecha = normalizar_fecha(valor)
    if fecha < ahora + ANTICIPACION_MINIMA:
        raise HTTPException(status_code=422, detail={
            "codigo": "FECHA_PROGRAMADA_PASADA",
            "mensaje": "La fecha programada debe ser futura (al menos un minuto desde ahora)",
        })
    if fecha > ahora + HORIZONTE_MAXIMO:
        raise HTTPException(status_code=422, detail={
            "codigo": "FECHA_PROGRAMADA_LEJANA",
            "mensaje": "La fecha programada no puede superar un año desde hoy",
        })
    if fecha_limite_sla is not None and normalizar_fecha(fecha_limite_sla) < fecha:
        raise HTTPException(status_code=422, detail={
            "codigo": "FECHA_POSTERIOR_AL_SLA",
            "mensaje": "La fecha programada es posterior a la fecha límite (SLA) del envío",
        })
    return fecha


async def activar_vencidos(fabrica_sesion=SessionLocal, publicar=publish_event, ahora: Optional[datetime] = None) -> int:
    """Arranca los envíos programados cuya hora ya llegó. Devuelve cuántos activó.
    Publica ANTES de confirmar el cambio de estado: si RabbitMQ falla, el envío sigue 'programado' y se
    reintenta en el siguiente ciclo (a lo sumo se publica dos veces; Routing ignora el duplicado)."""
    ahora = ahora or datetime.now(timezone.utc)
    db = fabrica_sesion()
    try:
        ids = [
            fila[0] for fila in db.query(Envio.id)
            .filter(Envio.estado == "programado", Envio.fecha_programada <= ahora, Envio.partes_total.is_(None))
            .order_by(Envio.fecha_programada.asc(), Envio.peso_kg.desc()).limit(LOTE).all()
        ]
    finally:
        db.close()

    activados = 0
    for envio_id in ids:
        db = fabrica_sesion()
        try:
            envio = (
                db.query(Envio)
                .filter(Envio.id == envio_id, Envio.estado == "programado")
                .with_for_update(skip_locked=True, of=Envio)
                .first()
            )
            if envio is None:
                continue  # lo canceló o reprogramó alguien, o lo está activando otro proceso
            await publicar("shipment.created", construir_payload_creado(envio))
            envio.estado = "pendiente"
            db.add(EnvioEvento(
                envio_id=envio.id, tipo_evento="activado_programacion",
                notas="llegó la hora programada: se inicia la asignación de vehículo",
            ))
            db.commit()
            activados += 1
        except Exception as exc:
            db.rollback()
            print(f"[shipment] no se pudo activar el envío programado {envio_id}: {exc}")
        finally:
            db.close()
    return activados


async def bucle_programacion() -> None:
    while True:
        await asyncio.sleep(INTERVALO_S)
        try:
            await activar_vencidos()
        except Exception as exc:
            print(f"[shipment] error en el ciclo de programación: {exc}")
