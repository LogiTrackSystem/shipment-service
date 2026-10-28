import os
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..facturacion_client import calcular_cotizacion, facturacion_activa
from ..flota_client import verificar_viabilidad
from ..estados import ESTADOS_CANCELABLES, ESTADOS_ENTREGABLES, TRANSICIONES_MANUALES
from ..events import _publicar_con_reintentos, publish_event
from ..models import Cliente, Envio, EnvioEvento, PruebaEntrega
from ..payloads import construir_payload_creado
from ..programacion import normalizar_fecha, validar_fecha_programada
from ..routing_client import obtener_ruta_maestra, reintentar_asignacion
from ..seguridad import Contexto, obtener_contexto, requerir_roles
from ..schemas import (
    EnvioActualizarEstado, EnvioCancelar, EnvioCrear, EnvioEventoLeer, EnvioLeer, EnvioReprogramar,
    PruebaEntregaCrear, PruebaEntregaLeer,
)

router = APIRouter(prefix="/envios", tags=["envios"])

MAX_PARTES = int(os.getenv("MAX_PARTES_PEDIDO", "10"))


def _obtener_envio_o_404(db: Session, envio_id: uuid.UUID, ctx: Optional[Contexto] = None) -> Envio:
    """Una cuenta de cliente solo ve sus envíos; los ajenos responden 404 (no se revela que existen)."""
    envio = db.query(Envio).filter(Envio.id == envio_id).first()
    if envio is None or (ctx is not None and ctx.es_cliente and envio.cliente_id != ctx.cliente_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Envío no encontrado")
    return envio


def _bloquear_envio_o_404(db: Session, envio_id: uuid.UUID) -> Envio:
    """Como _obtener_envio_o_404 pero bloqueando la fila: evita que la activación programada y una
    cancelación/reprogramación simultáneas se pisen."""
    envio = db.query(Envio).filter(Envio.id == envio_id).with_for_update(of=Envio).first()
    if envio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Envío no encontrado")
    return envio


def _bloquear_pedido(db: Session, envio_id: uuid.UUID):
    """Devuelve (envio, partes) bloqueando las filas. Para un pedido dividido bloquea primero las partes y
    luego el pedido (el mismo orden que usan los procesos de eventos), para evitar bloqueos cruzados."""
    envio = db.query(Envio).filter(Envio.id == envio_id).first()
    if envio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Envío no encontrado")
    if not envio.partes_total:
        return _bloquear_envio_o_404(db, envio_id), []
    partes = (
        db.query(Envio).filter(Envio.envio_padre_id == envio_id)
        .order_by(Envio.parte_numero.asc()).with_for_update(of=Envio).all()
    )
    return _bloquear_envio_o_404(db, envio_id), partes


def _payload_devolucion(db: Session, envio: Envio, notas: Optional[str]) -> dict:
    """Contenido de shipment.returned. Además de lo que usa Routing (envio_id), indica a qué pedido pertenece
    y si el pedido completo quedó devuelto: Billing solo prepara el reembolso cuando el pedido entero se devolvió
    (una parte devuelta mientras otras se entregan no se reembolsa sola)."""
    pedido = envio
    if envio.envio_padre_id is not None:
        pedido = db.query(Envio).filter(Envio.id == envio.envio_padre_id).first() or envio
        db.refresh(pedido)
    return {
        "envio_id": str(envio.id),
        "codigo_envio": envio.codigo_envio,
        "cliente_id": str(envio.cliente_id),
        "notas": notas,
        "envio_padre_id": str(envio.envio_padre_id) if envio.envio_padre_id else None,
        "pedido_id": str(pedido.id),
        "pedido_codigo": pedido.codigo_envio,
        "pedido_devuelto": pedido.estado == "devuelto",
        "pedido_monto_cop": float(pedido.monto_cop) if pedido.monto_cop is not None else None,
    }


def _rechazar_si_es_parte(envio: Envio) -> None:
    if envio.envio_padre_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "codigo": "PARTE_DE_PEDIDO",
            "mensaje": "Este envío es una parte de un pedido dividido: la operación se hace sobre el pedido completo.",
            "envio_padre_id": str(envio.envio_padre_id),
        })


def _rechazar_si_es_pedido(envio: Envio) -> None:
    if envio.partes_total:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "codigo": "ENVIO_DIVIDIDO",
            "mensaje": "Este pedido está dividido en partes: la operación se hace sobre cada parte.",
            "partes_total": envio.partes_total,
        })


def _registrar_evento(db: Session, envio_id: uuid.UUID, tipo_evento: str, notas: Optional[str] = None) -> None:
    db.add(EnvioEvento(envio_id=envio_id, tipo_evento=tipo_evento, notas=notas))


def _rechazar_transicion(envio: Envio, destino: str, permitidos) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "codigo": "TRANSICION_INVALIDA",
            "mensaje": (
                f"Un envío en estado '{envio.estado}' no puede pasar a '{destino}'. "
                f"Solo se permite desde: {', '.join(permitidos)}."
            ),
        },
    )


def _validar_internacional(payload: EnvioCrear, origen: dict, destino: dict) -> bool:
    """Nacional / internacional se deduce de los países de las ubicaciones."""
    es_internacional = origen["codigo_pais"] != destino["codigo_pais"]
    if payload.es_internacional is not None and payload.es_internacional != es_internacional:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"es_internacional={str(payload.es_internacional).lower()} contradice las ubicaciones: "
                f"origen en {origen['pais']}, destino en {destino['pais']}. "
                "Puede omitir el campo: el sistema lo deduce."
            ),
        )
    return es_internacional


@router.post("/cotizar")
async def cotizar_envio(payload: EnvioCrear, ctx: Contexto = Depends(obtener_contexto)):
    """Precio (COP), viabilidad y plan de división de un pedido, SIN crearlo. El cliente revisa el precio
    y, si lo acepta, crea el envío con POST /envios enviando ese valor en `monto_aceptado_cop`."""
    ruta = await obtener_ruta_maestra(
        payload.origen_id, payload.origen_codigo, payload.destino_id, payload.destino_codigo
    )
    origen, destino = ruta["origen"], ruta["destino"]
    es_internacional = _validar_internacional(payload, origen, destino)
    fecha_programada = validar_fecha_programada(payload.fecha_programada, payload.fecha_limite_sla)

    viab = await verificar_viabilidad(
        payload.peso_kg, payload.volumen_m3, payload.tipo_carga, payload.es_hazmat, payload.es_divisible, lanzar=False
    )
    viable = None if viab is None else bool(viab.get("viable", True))
    requiere_division = bool(viab and viab.get("requiere_division"))

    cotizacion = None
    if viable is not False:
        cotizacion = await calcular_cotizacion(
            payload.peso_kg, ruta["distancia_km"], ctx.cliente_id if ctx.es_cliente else None
        )

    n_partes = len((viab or {}).get("partes") or [])
    puede_crear = viable is not False and not (requiere_division and n_partes > MAX_PARTES)
    respuesta = {
        "origen": origen["etiqueta"],
        "destino": destino["etiqueta"],
        "codigo_ruta": ruta["codigo_ruta"],
        "distancia_km": float(ruta["distancia_km"]),
        "duracion_horas": float(ruta["duracion_horas"]),
        "es_internacional": es_internacional,
        "peso_kg": float(payload.peso_kg),
        "es_divisible": payload.es_divisible,
        "fecha_programada": fecha_programada,
        "viabilidad": None if viab is None else {
            "viable": viable,
            "causa": viab.get("causa"),
            "mensaje": viab.get("mensaje"),
            "requiere_division": requiere_division,
            "division_posible": viab.get("division_posible", False),
            "capacidad_maxima_kg": viab.get("capacidad_maxima_kg"),
            "partes": viab.get("partes"),
            "desperdicio_kg": viab.get("desperdicio_kg"),
        },
        "facturacion_activa": facturacion_activa(),
        "cotizacion": cotizacion,
        "monto_cop": cotizacion["monto_cop"] if cotizacion else None,
        "moneda": "COP",
        "puede_crear": puede_crear,
    }
    if requiere_division and viable and n_partes > MAX_PARTES:
        respuesta["aviso"] = f"La carga requiere {n_partes} vehículos y el máximo por pedido es {MAX_PARTES}"
    elif requiere_division and viable:
        respuesta["aviso"] = f"La carga se dividirá en {n_partes} envíos (uno por vehículo); el precio es el del pedido completo"
    return respuesta


@router.post("/", response_model=EnvioLeer, status_code=status.HTTP_201_CREATED)
async def crear_envio(payload: EnvioCrear, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    # 1) Cliente (falla rápida, es una consulta local). Una cuenta de cliente SIEMPRE crea envíos a su nombre.
    if ctx.es_cliente:
        cliente = db.query(Cliente).filter(Cliente.id == ctx.cliente_id).first()
    elif payload.codigo_cliente is not None:
        cliente = db.query(Cliente).filter(Cliente.codigo_cliente == payload.codigo_cliente).first()
    elif payload.cliente_id is not None:
        cliente = db.query(Cliente).filter(Cliente.id == payload.cliente_id).first()
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe indicar cliente_id o codigo_cliente",
        )
    if cliente is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El cliente no existe. Regístrelo primero en POST /clientes/",
        )
    if not cliente.activo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El cliente {cliente.codigo_cliente} está inactivo",
        )

    # 2) Origen, destino y ruta: una sola consulta a Routing los valida y calcula
    ruta = await obtener_ruta_maestra(
        payload.origen_id, payload.origen_codigo, payload.destino_id, payload.destino_codigo
    )
    origen, destino = ruta["origen"], ruta["destino"]

    # 3) Nacional / internacional se deduce de los países de las ubicaciones
    es_internacional = _validar_internacional(payload, origen, destino)

    # 3a) Programación: fecha futura (el envío no reserva vehículo hasta esa hora)
    fecha_programada = validar_fecha_programada(payload.fecha_programada, payload.fecha_limite_sla)

    # 3b) Falla rápida: si ningún vehículo de la flota podría transportar esta carga, se rechaza ya
    viabilidad = await verificar_viabilidad(
        payload.peso_kg, payload.volumen_m3, payload.tipo_carga, payload.es_hazmat, payload.es_divisible
    )
    partes_plan = _plan_de_partes(viabilidad, payload.peso_kg)

    # 3c) Precio: Billing lo recalcula y debe coincidir con el que el cliente aceptó
    monto_cop = None
    cotizacion = await calcular_cotizacion(payload.peso_kg, ruta["distancia_km"], cliente.id)
    if cotizacion is not None:
        monto_cop = Decimal(str(cotizacion["monto_cop"]))
        if payload.monto_aceptado_cop is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "codigo": "PRECIO_NO_ACEPTADO",
                    "mensaje": "Cotice con POST /envios/cotizar y envíe el valor aceptado en monto_aceptado_cop",
                    "monto_actual_cop": float(monto_cop),
                },
            )
        if payload.monto_aceptado_cop != monto_cop:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "codigo": "PRECIO_CAMBIO",
                    "mensaje": "El precio cambió desde la cotización; revíselo y acéptelo de nuevo",
                    "monto_aceptado_cop": float(payload.monto_aceptado_cop),
                    "monto_actual_cop": float(monto_cop),
                },
            )

    # 4) Se guarda como 'pendiente' (o 'programado'); la asignación de vehículo y conductor ocurre después, por eventos
    datos = payload.model_dump(exclude={
        "cliente_id", "codigo_cliente", "origen_id", "origen_codigo",
        "destino_id", "destino_codigo", "es_internacional", "monto_aceptado_cop", "fecha_programada",
    })
    comunes = dict(
        cliente_id=cliente.id,
        origen=origen["etiqueta"],
        destino=destino["etiqueta"],
        origen_id=uuid.UUID(origen["id"]),
        destino_id=uuid.UUID(destino["id"]),
        codigo_pais_origen=origen["codigo_pais"],
        codigo_pais_destino=destino["codigo_pais"],
        es_internacional=es_internacional,
        ruta_maestra_id=uuid.UUID(ruta["id"]),
        codigo_ruta=ruta["codigo_ruta"],
        distancia_km=ruta["distancia_km"],
        duracion_horas=ruta["duracion_horas"],
        pais_origen=origen["pais"],
        pais_destino=destino["pais"],
        fecha_programada=fecha_programada,
        estado="programado" if fecha_programada else "pendiente",
    )
    if partes_plan:
        return await _crear_pedido_dividido(db, datos, comunes, partes_plan, monto_cop, fecha_programada)

    envio = Envio(monto_cop=monto_cop, **comunes, **datos)
    db.add(envio)
    db.commit()
    db.refresh(envio)
    _registrar_evento(db, envio.id, "creado", notas=f"ruta {envio.codigo_ruta}, {envio.distancia_km} km")
    if fecha_programada:
        _registrar_evento(db, envio.id, "programado", notas=f"programado para {fecha_programada.isoformat()}")
    db.commit()
    db.refresh(envio)

    if fecha_programada:
        # No arranca la Saga: el vigilante publica shipment.created a la hora programada. Este aviso
        # permite a Billing registrar el pago aceptado desde ahora.
        await publish_event("shipment.scheduled", construir_payload_creado(envio))
    else:
        await publish_event("shipment.created", construir_payload_creado(envio))
    return envio


def _plan_de_partes(viabilidad: Optional[dict], peso_total) -> Optional[list]:
    """Si la carga no cabe en un solo vehículo y es divisible, devuelve el plan de partes de Fleet
    (de la más pesada a la más liviana); si cabe, None. Valida que el plan sea coherente."""
    if not viabilidad or not viabilidad.get("requiere_division"):
        return None
    partes = sorted(viabilidad.get("partes") or [], key=lambda p: -float(p["peso_kg"]))
    if len(partes) < 2:
        raise HTTPException(status_code=502, detail={
            "codigo": "PLAN_DIVISION_INVALIDO", "mensaje": "Fleet no devolvió un plan de división utilizable",
        })
    if len(partes) > MAX_PARTES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={
            "codigo": "DEMASIADAS_PARTES",
            "mensaje": f"La carga requeriría {len(partes)} vehículos y el máximo por pedido es {MAX_PARTES}. "
                       "Divídala en varios pedidos.",
            "partes_necesarias": len(partes),
        })
    total = sum(Decimal(str(p["peso_kg"])) for p in partes)
    if abs(total - Decimal(str(peso_total))) > Decimal("0.01"):
        raise HTTPException(status_code=502, detail={
            "codigo": "PLAN_DIVISION_INVALIDO",
            "mensaje": f"El plan de Fleet suma {total} kg y el pedido pesa {peso_total} kg",
        })
    return partes


async def _crear_pedido_dividido(db: Session, datos: dict, comunes: dict, partes_plan: list,
                                 monto_cop, fecha_programada):
    """Crea el pedido (padre, no viaja) y una parte (hijo) por cada vehículo del plan. Cada parte es un
    envío completo: pasa por la Saga de asignación, el seguimiento y la aduana como cualquier otro. El precio
    y el pago pertenecen al pedido. Las partes se publican de la más pesada a la más liviana."""
    n = len(partes_plan)
    datos_pedido = {**datos, "es_divisible": True}
    datos_parte = {k: v for k, v in datos.items() if k not in ("peso_kg", "volumen_m3", "es_divisible")}

    padre = Envio(monto_cop=monto_cop, partes_total=n, partes_entregadas=0, **comunes, **datos_pedido)
    db.add(padre)
    db.flush()
    db.refresh(padre)  # trae el código ENV-xxxxxxxx asignado por la base de datos

    partes = []
    for i, plan in enumerate(partes_plan, start=1):
        partes.append(Envio(
            envio_padre_id=padre.id, parte_numero=i, codigo_envio=f"{padre.codigo_envio}-P{i}",
            peso_kg=Decimal(str(plan["peso_kg"])),
            volumen_m3=Decimal(str(plan["volumen_m3"])) if plan.get("volumen_m3") is not None else None,
            es_divisible=False, monto_cop=None, **comunes, **datos_parte,
        ))
    db.add_all(partes)
    resumen = " + ".join(f"{float(p.peso_kg):g}" for p in partes)
    _registrar_evento(db, padre.id, "creado", notas=f"ruta {padre.codigo_ruta}, {padre.distancia_km} km")
    _registrar_evento(db, padre.id, "dividido", notas=f"{n} partes (kg): {resumen}")
    if fecha_programada:
        _registrar_evento(db, padre.id, "programado", notas=f"programado para {fecha_programada.isoformat()}")
    db.flush()
    for p in partes:
        _registrar_evento(db, p.id, "creado", notas=f"parte {p.parte_numero} de {n} del pedido {padre.codigo_envio}")
        if fecha_programada:
            _registrar_evento(db, p.id, "programado", notas=f"programado para {fecha_programada.isoformat()}")
    db.commit()
    db.refresh(padre)

    # El pedido anuncia el pago aceptado (Billing); no inicia ninguna asignación: eso lo hacen sus partes.
    await publish_event("shipment.split", {
        **construir_payload_creado(padre),
        "partes": [{"envio_id": str(p.id), "codigo_envio": p.codigo_envio, "peso_kg": float(p.peso_kg)} for p in partes],
    })
    if not fecha_programada:
        for p in partes:  # de la más pesada a la más liviana
            await publish_event("shipment.created", construir_payload_creado(p))
    return padre


@router.get("/programados", response_model=list[EnvioLeer])
def calendario_programados(
    desde: Optional[datetime] = None,
    hasta: Optional[datetime] = None,
    incluir_activados: bool = False,
    limite: int = 200,
    db: Session = Depends(get_db),
    ctx: Contexto = Depends(requerir_roles("operador", "gestor_flota", "administrador")),
):
    """Calendario de envíos programados, ordenados por fecha (un pedido dividido aparece una vez, no por parte).
    Por defecto solo los que aún esperan su hora;
    con incluir_activados=true también los que ya arrancaron (o se cancelaron) y tuvieron fecha programada."""
    consulta = db.query(Envio).filter(Envio.fecha_programada.isnot(None), Envio.envio_padre_id.is_(None))
    if not incluir_activados:
        consulta = consulta.filter(Envio.estado == "programado")
    if desde:
        consulta = consulta.filter(Envio.fecha_programada >= normalizar_fecha(desde))
    if hasta:
        consulta = consulta.filter(Envio.fecha_programada <= normalizar_fecha(hasta))
    return consulta.order_by(Envio.fecha_programada.asc()).limit(max(1, min(limite, 500))).all()


@router.patch("/{envio_id}/reprogramar", response_model=EnvioLeer)
def reprogramar_envio(
    envio_id: uuid.UUID,
    payload: EnvioReprogramar,
    db: Session = Depends(get_db),
    ctx: Contexto = Depends(requerir_roles("gestor_flota", "administrador")),
):
    """Cambia la fecha de un envío que todavía no arrancó (estado 'programado'). En un pedido dividido se
    reprograma el pedido completo (todas sus partes deben seguir programadas)."""
    envio, partes = _bloquear_pedido(db, envio_id)
    _rechazar_si_es_parte(envio)
    if envio.estado != "programado" or any(p.estado != "programado" for p in partes):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": "NO_ESTA_PROGRAMADO",
                "mensaje": f"El envío está '{envio.estado}'; solo se reprograma si está 'programado'.",
            },
        )
    nueva = validar_fecha_programada(payload.fecha_programada, envio.fecha_limite_sla)
    anterior = envio.fecha_programada
    envio.fecha_programada = nueva
    notas = f"de {anterior.isoformat() if anterior else 'sin fecha'} a {nueva.isoformat()}"
    if payload.motivo:
        notas += f" · motivo: {payload.motivo}"
    _registrar_evento(db, envio.id, "reprogramado", notas=notas)
    for parte in partes:
        parte.fecha_programada = nueva
        _registrar_evento(db, parte.id, "reprogramado", notas=notas)
    db.commit()
    db.refresh(envio)
    return envio


@router.post("/{envio_id}/cancelar", response_model=EnvioLeer)
async def cancelar_envio(
    envio_id: uuid.UUID,
    payload: Optional[EnvioCancelar] = None,
    db: Session = Depends(get_db),
    ctx: Contexto = Depends(requerir_roles("gestor_flota", "administrador")),
):
    """Cancela un envío que todavía no tiene vehículo en camino (programado, pendiente o sin_asignacion).
    Un pedido dividido se cancela completo y solo si ninguna de sus partes tiene ya vehículo asignado."""
    envio, partes = _bloquear_pedido(db, envio_id)
    _rechazar_si_es_parte(envio)
    bloqueantes = [p for p in partes if p.estado not in ESTADOS_CANCELABLES and p.estado != "cancelado"]
    if envio.estado == "cancelado" or (not partes and envio.estado not in ESTADOS_CANCELABLES) or bloqueantes:
        detalle = {
            "codigo": "NO_SE_PUEDE_CANCELAR",
            "mensaje": f"El envío está '{envio.estado}'; solo se cancela si está: {', '.join(ESTADOS_CANCELABLES)}.",
        }
        if bloqueantes:
            detalle["mensaje"] = (
                "El pedido ya tiene partes en curso y no puede cancelarse completo: "
                + ", ".join(f"{p.codigo_envio} ({p.estado})" for p in bloqueantes)
            )
            detalle["partes_en_curso"] = [p.codigo_envio for p in bloqueantes]
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detalle)

    motivo = payload.motivo if payload else None
    estado_anterior = envio.estado
    cancelados = []
    for unidad in (partes if partes else [envio]):
        if unidad.estado == "cancelado":
            continue
        cancelados.append((unidad, unidad.estado))
        unidad.estado = "cancelado"
        unidad.estado_previo = None
        unidad.motivo_sin_asignacion = None
        _registrar_evento(db, unidad.id, "cancelado", notas=motivo or f"cancelado desde '{cancelados[-1][1]}'")
    if partes:
        _registrar_evento(db, envio.id, "cancelado", notas=motivo or f"pedido cancelado ({len(cancelados)} partes)")
    db.commit()
    db.refresh(envio)

    # Routing escucha este evento por cada envío: abandona la solicitud o libera la reserva si justo se alcanzó
    # a asignar. Billing lo usará para devolver el pago del pedido.
    for unidad, anterior in cancelados + ([(envio, estado_anterior)] if partes else []):
        await _publicar_con_reintentos("shipment.cancelled", {
            "envio_id": str(unidad.id),
            "codigo_envio": unidad.codigo_envio,
            "cliente_id": str(unidad.cliente_id),
            "estado_anterior": anterior,
            "motivo": motivo,
            "monto_cop": float(unidad.monto_cop) if unidad.monto_cop is not None else None,
            "es_pedido_dividido": bool(partes) and unidad is envio,
        })
    return envio


@router.get("/{envio_id}/partes", response_model=list[EnvioLeer])
def partes_del_pedido(envio_id: uuid.UUID, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    """Partes (envíos hijos) de un pedido dividido, de la más pesada a la más liviana. Vacío si no está dividido."""
    _obtener_envio_o_404(db, envio_id, ctx)
    return db.query(Envio).filter(Envio.envio_padre_id == envio_id).order_by(Envio.parte_numero.asc()).all()


@router.get("/codigo/{codigo_envio}", response_model=EnvioLeer)
def obtener_envio_por_codigo(codigo_envio: str, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    envio = db.query(Envio).filter(Envio.codigo_envio == codigo_envio.strip().upper()).first()
    if envio is None or (ctx.es_cliente and envio.cliente_id != ctx.cliente_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Envío no encontrado")
    return envio


@router.get("/", response_model=list[EnvioLeer])
def listar_envios(
    estado: Optional[str] = None,
    cliente_id: Optional[uuid.UUID] = None,
    envio_padre_id: Optional[uuid.UUID] = None,
    solo_pedidos: bool = False,
    db: Session = Depends(get_db),
    ctx: Contexto = Depends(obtener_contexto),
):
    """solo_pedidos=true oculta las partes de los pedidos divididos (se ven con /envios/{id}/partes)."""
    query = db.query(Envio)
    if estado:
        query = query.filter(Envio.estado == estado)
    if envio_padre_id:
        query = query.filter(Envio.envio_padre_id == envio_padre_id)
    if solo_pedidos:
        query = query.filter(Envio.envio_padre_id.is_(None))
    if ctx.es_cliente:
        cliente_id = ctx.cliente_id  # una cuenta de cliente solo lista lo suyo, sin importar lo que pida
    if cliente_id:
        query = query.filter(Envio.cliente_id == cliente_id)
    return query.order_by(Envio.creado_en.desc()).all()


@router.get("/{envio_id}", response_model=EnvioLeer)
def obtener_envio(envio_id: uuid.UUID, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    return _obtener_envio_o_404(db, envio_id, ctx)


@router.get("/{envio_id}/eventos", response_model=list[EnvioEventoLeer])
def obtener_eventos_envio(envio_id: uuid.UUID, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    _obtener_envio_o_404(db, envio_id, ctx)
    return (
        db.query(EnvioEvento)
        .filter(EnvioEvento.envio_id == envio_id)
        .order_by(EnvioEvento.fecha_hora.asc())
        .all()
    )


@router.get("/{envio_id}/prueba-entrega", response_model=PruebaEntregaLeer)
def obtener_prueba_entrega(envio_id: uuid.UUID, db: Session = Depends(get_db), ctx: Contexto = Depends(obtener_contexto)):
    _obtener_envio_o_404(db, envio_id, ctx)
    prueba = db.query(PruebaEntrega).filter(PruebaEntrega.envio_id == envio_id).first()
    if prueba is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este envío aún no tiene prueba de entrega")
    return prueba

@router.post("/{envio_id}/reintentar-asignacion")
async def reintentar_asignacion_envio(envio_id: uuid.UUID, db: Session = Depends(get_db)):
    """Pide a Routing reintentar ahora la asignación de un envío que está esperando vehículo.
    En un pedido dividido se reintenta cada parte que esté esperando, de la más pesada a la más liviana."""
    envio = _obtener_envio_o_404(db, envio_id)
    if envio.partes_total:
        esperando = (
            db.query(Envio)
            .filter(Envio.envio_padre_id == envio.id, Envio.estado.in_(("pendiente", "sin_asignacion")))
            .order_by(Envio.peso_kg.desc(), Envio.parte_numero.asc()).all()
        )
        if not esperando:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                "codigo": "NO_ESTA_EN_ESPERA", "mensaje": "Ninguna parte del pedido está esperando vehículo.",
            })
        resultados = []
        for parte in esperando:
            ruta = await reintentar_asignacion(parte.id)
            resultados.append({
                "envio_id": str(parte.id), "codigo_envio": parte.codigo_envio,
                "estado_asignacion": ruta.get("estado"), "detalle": ruta.get("ultimo_error"),
            })
        return {
            "envio_id": str(envio.id), "codigo_envio": envio.codigo_envio, "partes": resultados,
            "nota": "Si alguna quedó asignada, el estado se actualiza en unos segundos.",
        }
    if envio.estado not in ("pendiente", "sin_asignacion"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "codigo": "NO_ESTA_EN_ESPERA",
                "mensaje": f"El envío está '{envio.estado}'; solo se reintenta si está 'pendiente' o 'sin_asignacion'.",
            },
        )
    ruta = await reintentar_asignacion(envio.id)
    return {
        "envio_id": str(envio.id),
        "codigo_envio": envio.codigo_envio,
        "estado_asignacion": ruta.get("estado"),
        "detalle": ruta.get("ultimo_error"),
        "nota": "Si quedó asignada, el estado del envío se actualiza en unos segundos.",
    }


@router.patch("/{envio_id}/estado", response_model=EnvioLeer)
async def actualizar_estado_envio(envio_id: uuid.UUID, payload: EnvioActualizarEstado, db: Session = Depends(get_db)):
    envio = _obtener_envio_o_404(db, envio_id)
    _rechazar_si_es_pedido(envio)
    permitidos = TRANSICIONES_MANUALES[payload.estado]
    if envio.estado not in permitidos:
        _rechazar_transicion(envio, payload.estado, permitidos)

    envio.estado = payload.estado
    envio.estado_previo = None
    _registrar_evento(db, envio.id, payload.estado, notas=payload.notas)
    db.commit()
    db.refresh(envio)

    if payload.estado == "con_incidencia":
        await publish_event("shipment.incident", {"envio_id": str(envio.id), "notas": payload.notas})
    elif payload.estado == "devuelto":
        # Routing escucha este evento: libera la reserva en Fleet (vehículo y conductor)
        await publish_event("shipment.returned", _payload_devolucion(db, envio, payload.notas))
    return envio


@router.post("/{envio_id}/prueba-entrega", response_model=PruebaEntregaLeer, status_code=status.HTTP_201_CREATED)
async def registrar_prueba_entrega(envio_id: uuid.UUID, payload: PruebaEntregaCrear, db: Session = Depends(get_db)):
    envio = _obtener_envio_o_404(db, envio_id)
    _rechazar_si_es_pedido(envio)
    existente = db.query(PruebaEntrega).filter(PruebaEntrega.envio_id == envio_id).first()
    if existente is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este envío ya tiene una prueba de entrega registrada")
    if envio.estado not in ESTADOS_ENTREGABLES:
        _rechazar_transicion(envio, "entregado", ESTADOS_ENTREGABLES)

    prueba = PruebaEntrega(envio_id=envio_id, **payload.model_dump())
    db.add(prueba)
    envio.estado = "entregado"
    envio.estado_previo = None
    _registrar_evento(db, envio.id, "entregado", notas=f"receptor={payload.nombre_receptor}")
    db.commit()
    db.refresh(prueba)
    db.refresh(envio)

    # Routing escucha este evento: libera la reserva en Fleet y reasigna a los envíos en espera
    await publish_event("shipment.delivered", {
        "envio_id": str(envio.id),
        "entregado_en": prueba.entregado_en,
        "nombre_receptor": prueba.nombre_receptor,
    })
    return prueba