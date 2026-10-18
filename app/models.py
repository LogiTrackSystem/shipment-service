import uuid
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class Cliente(Base):
    __tablename__ = "clientes"
    __table_args__ = (UniqueConstraint("tipo_documento", "numero_documento", name="uq_clientes_documento"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo_cliente = Column(BigInteger, server_default=text("nextval('seq_codigo_cliente')"), unique=True, nullable=False)
    nombre = Column(String(150), nullable=False)
    tipo_documento = Column(String(10), nullable=True)
    numero_documento = Column(String(30), nullable=True)
    email = Column(String(150), nullable=True)
    telefono = Column(String(30), nullable=True)
    direccion = Column(String(255), nullable=True)
    activo = Column(Boolean, nullable=False, server_default=text("true"))
    es_historico = Column(Boolean, nullable=False, server_default=text("false"))
    creado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Envio(Base):
    __tablename__ = "envios"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo_envio = Column(
        String(20),  # 'ENV-00000032' o, para las partes de un pedido dividido, 'ENV-00000032-P1'
        
        server_default=text("'ENV-' || lpad(nextval('seq_codigo_envio')::text, 8, '0')"),
        unique=True,
        nullable=False,
    )
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=False)
    origen = Column(String(255), nullable=False)
    destino = Column(String(255), nullable=False)
    origen_id = Column(UUID(as_uuid=True), nullable=True)
    destino_id = Column(UUID(as_uuid=True), nullable=True)
    codigo_pais_origen = Column(String(2), nullable=True)
    codigo_pais_destino = Column(String(2), nullable=True)
    ruta_maestra_id = Column(UUID(as_uuid=True), nullable=True)
    codigo_ruta = Column(String(12), nullable=True)
    distancia_km = Column(Numeric(10, 2), nullable=True)
    duracion_horas = Column(Numeric(8, 2), nullable=True)
    estado = Column(String(20), nullable=False, default="pendiente")
    # Pedido dividido: el pedido (padre) no viaja; cada parte (hijo) es un envío completo e independiente
    envio_padre_id = Column(UUID(as_uuid=True), ForeignKey("envios.id"), nullable=True, index=True)
    parte_numero = Column(Integer, nullable=True)
    partes_total = Column(Integer, nullable=True)        # solo en el pedido
    partes_entregadas = Column(Integer, nullable=True)   # solo en el pedido; lo mantiene el sistema
    fecha_programada = Column(DateTime(timezone=True), nullable=True, index=True)  # si existe, el envío arranca a esa hora
    pais_origen = Column(String(100), nullable=True)
    pais_destino = Column(String(100), nullable=True)
    fecha_limite_sla = Column(DateTime(timezone=True), nullable=True)
    es_internacional = Column(Boolean, nullable=False, default=False)
    tipo_carga = Column(String(20), nullable=False, server_default="general")
    es_hazmat = Column(Boolean, nullable=False, server_default=text("false"))
    es_divisible = Column(Boolean, nullable=False, server_default=text("false"))
    peso_kg = Column(Numeric(10, 2), nullable=False)
    volumen_m3 = Column(Numeric(10, 2), nullable=True)
    monto_cop = Column(Numeric(14, 2), nullable=True)  # precio aceptado al crear el pedido (el cobro vive en Billing)
    vehiculo_id = Column(UUID(as_uuid=True), nullable=True)
    ruta_id = Column(UUID(as_uuid=True), nullable=True)
    conductor_id = Column(UUID(as_uuid=True), nullable=True)
    placa_vehiculo = Column(String(20), nullable=True)
    tipo_vehiculo = Column(String(20), nullable=True)
    conductor_nombre = Column(String(150), nullable=True)
    codigo_conductor = Column(BigInteger, nullable=True)
    hora_estimada_llegada = Column(DateTime(timezone=True), nullable=True)
    motivo_sin_asignacion = Column(Text, nullable=True)
    estado_previo = Column(String(20), nullable=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    cliente = relationship("Cliente", lazy="joined")

    @property
    def codigo_cliente(self):
        return self.cliente.codigo_cliente if self.cliente else None


class PruebaEntrega(Base):
    __tablename__ = "prueba_entrega"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envio_id = Column(UUID(as_uuid=True), ForeignKey("envios.id"), nullable=False, unique=True)
    url_firma = Column(String(500), nullable=True)
    url_foto = Column(String(500), nullable=True)
    nombre_receptor = Column(String(150), nullable=False)
    entregado_en = Column(DateTime(timezone=True), server_default=func.now())
    simulada = Column(Boolean, nullable=False, server_default=text("false"))


class EnvioEvento(Base):
    __tablename__ = "envio_eventos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envio_id = Column(UUID(as_uuid=True), ForeignKey("envios.id"), nullable=False)
    tipo_evento = Column(String(30), nullable=False)
    notas = Column(Text, nullable=True)
    fecha_hora = Column(DateTime(timezone=True), server_default=func.now())


class Usuario(Base):
    """Cuenta de acceso al sistema. Los clientes (rol 'cliente') quedan ligados a un registro de clientes."""
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint(
            "rol IN ('cliente','operador','gestor_flota','administrador')", name="ck_usuarios_rol"
        ),
        CheckConstraint("rol <> 'cliente' OR cliente_id IS NOT NULL", name="ck_usuarios_cliente_requerido"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(150), unique=True, nullable=False)
    nombre = Column(String(150), nullable=False)
    password_hash = Column(String(255), nullable=False)
    rol = Column(String(20), nullable=False)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=True)
    activo = Column(Boolean, nullable=False, server_default=text("true"))
    ultimo_acceso = Column(DateTime(timezone=True), nullable=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    cliente = relationship("Cliente", lazy="joined")

    @property
    def codigo_cliente(self):
        return self.cliente.codigo_cliente if self.cliente else None


# ---------- El estado del pedido dividido se recalcula solo cuando cambia el de una de sus partes ----------
from sqlalchemy import event, inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from .estados import agregar_estado_padre  # noqa: E402


@event.listens_for(Session, "before_flush")
def _sincronizar_pedidos(session, flush_context, instances):
    """Cada vez que una parte cambia de estado (o se crea), el pedido adopta el estado agregado de sus partes
    y actualiza su contador de partes entregadas. Bloquea la fila del pedido para que dos partes que cambian a
    la vez no se pisen (el orden de bloqueo siempre es parte -> pedido)."""
    pedidos = set()
    for obj in list(session.dirty) + list(session.new):
        if isinstance(obj, Envio) and obj.envio_padre_id is not None:
            if obj in session.new or inspect(obj).attrs.estado.history.has_changes():
                pedidos.add(obj.envio_padre_id)
    for padre_id in pedidos:
        with session.no_autoflush:
            padre = session.query(Envio).filter(Envio.id == padre_id).with_for_update(of=Envio).first()
            if padre is None:
                continue
            partes = set(session.query(Envio).filter(Envio.envio_padre_id == padre_id).all())
        partes |= {o for o in session.new if isinstance(o, Envio) and o.envio_padre_id == padre_id}
        estados = [p.estado for p in partes]
        nuevo = agregar_estado_padre(estados)
        if padre.estado != nuevo:
            padre.estado = nuevo
            padre.estado_previo = None
        padre.partes_entregadas = sum(1 for e in estados if e == "entregado")
