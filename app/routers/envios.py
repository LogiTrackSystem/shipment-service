import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..flota_client import verificar_viabilidad
from ..estados import ESTADOS_ENTREGABLES, TRANSICIONES_MANUALES
from ..events import publish_event
from ..models import Cliente, Envio, EnvioEvento, PruebaEntrega
from ..routing_client import obtener_ruta_maestra, reintentar_asignacion
from ..schemas import (
    EnvioActualizarEstado, EnvioCrear, EnvioEventoLeer, EnvioLeer,
    PruebaEntregaCrear, PruebaEntregaLeer,
)

router = APIRouter(prefix="/envios", tags=["envios"])


def _obtener_envio_o_404(db: Session, envio_id: uuid.UUID) -> Envio:
    envio = db.query(Envio).filter(Envio.id == envio_id).first()
    if envio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Envío no encontrado")
    return envio


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


@router.post("/", response_model=EnvioLeer, status_code=status.HTTP_201_CREATED)
async def crear_envio(payload: EnvioCrear, db: Session = Depends(get_db)):
    # 1) Cliente (falla rápida, es una consulta local)
    if payload.codigo_cliente is not None:
        cliente = db.query(Cliente).filter(Cliente.codigo_cliente == payload.codigo_cliente).first()
    else:
        cliente = db.query(Cliente).filter(Cliente.id == payload.cliente_id).first()
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
    
    # 3b) Falla rápida: si ningún vehículo de la flota podría transportar esta carga, se rechaza ya
    await verificar_viabilidad(payload.peso_kg, payload.volumen_m3, payload.tipo_carga, payload.es_hazmat)

    # 4) Se guarda como 'pendiente'; la asignación de vehículo y conductor ocurre después, por eventos
    datos = payload.model_dump(exclude={
        "cliente_id", "codigo_cliente", "origen_id", "origen_codigo",
        "destino_id", "destino_codigo", "es_internacional",
    })
    envio = Envio(
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
        **datos,
    )
    db.add(envio)
    db.commit()
    db.refresh(envio)
    _registrar_evento(db, envio.id, "creado", notas=f"ruta {envio.codigo_ruta}, {envio.distancia_km} km")
    db.commit()
    db.refresh(envio)

    await publish_event("shipment.created", {
        "envio_id": str(envio.id),
        "codigo_envio": envio.codigo_envio,
        "cliente_id": str(envio.cliente_id),
        "codigo_cliente": cliente.codigo_cliente,
        "origen": envio.origen,
        "destino": envio.destino,
        "origen_id": str(envio.origen_id),
        "destino_id": str(envio.destino_id),
        "pais_origen": origen["pais"],
        "pais_destino": destino["pais"],
        "codigo_pais_origen": envio.codigo_pais_origen,
        "codigo_pais_destino": envio.codigo_pais_destino,
        "ruta_maestra_id": str(envio.ruta_maestra_id),
        "codigo_ruta": envio.codigo_ruta,
        "distancia_km": float(envio.distancia_km),
        "duracion_horas": float(envio.duracion_horas),
        "es_internacional": envio.es_internacional,
        "tipo_carga": envio.tipo_carga,
        "es_hazmat": envio.es_hazmat,
        "peso_kg": float(envio.peso_kg),
        "volumen_m3": float(envio.volumen_m3) if envio.volumen_m3 is not None else None,
        "fecha_limite_sla": envio.fecha_limite_sla,
    })
    return envio


@router.get("/codigo/{codigo_envio}", response_model=EnvioLeer)
def obtener_envio_por_codigo(codigo_envio: str, db: Session = Depends(get_db)):
    envio = db.query(Envio).filter(Envio.codigo_envio == codigo_envio.strip().upper()).first()
    if envio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Envío no encontrado")
    return envio


@router.get("/", response_model=list[EnvioLeer])
def listar_envios(estado: Optional[str] = None, cliente_id: Optional[uuid.UUID] = None, db: Session = Depends(get_db)):
    query = db.query(Envio)
    if estado:
        query = query.filter(Envio.estado == estado)
    if cliente_id:
        query = query.filter(Envio.cliente_id == cliente_id)
    return query.order_by(Envio.creado_en.desc()).all()


@router.get("/{envio_id}", response_model=EnvioLeer)
def obtener_envio(envio_id: uuid.UUID, db: Session = Depends(get_db)):
    return _obtener_envio_o_404(db, envio_id)


@router.get("/{envio_id}/eventos", response_model=list[EnvioEventoLeer])
def obtener_eventos_envio(envio_id: uuid.UUID, db: Session = Depends(get_db)):
    _obtener_envio_o_404(db, envio_id)
    return (
        db.query(EnvioEvento)
        .filter(EnvioEvento.envio_id == envio_id)
        .order_by(EnvioEvento.fecha_hora.asc())
        .all()
    )


@router.get("/{envio_id}/prueba-entrega", response_model=PruebaEntregaLeer)
def obtener_prueba_entrega(envio_id: uuid.UUID, db: Session = Depends(get_db)):
    _obtener_envio_o_404(db, envio_id)
    prueba = db.query(PruebaEntrega).filter(PruebaEntrega.envio_id == envio_id).first()
    if prueba is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este envío aún no tiene prueba de entrega")
    return prueba

@router.post("/{envio_id}/reintentar-asignacion")
async def reintentar_asignacion_envio(envio_id: uuid.UUID, db: Session = Depends(get_db)):
    """Pide a Routing reintentar ahora la asignación de un envío que está esperando vehículo."""
    envio = _obtener_envio_o_404(db, envio_id)
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
        await publish_event("shipment.returned", {"envio_id": str(envio.id), "notas": payload.notas})
    return envio


@router.post("/{envio_id}/prueba-entrega", response_model=PruebaEntregaLeer, status_code=status.HTTP_201_CREATED)
async def registrar_prueba_entrega(envio_id: uuid.UUID, payload: PruebaEntregaCrear, db: Session = Depends(get_db)):
    envio = _obtener_envio_o_404(db, envio_id)
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