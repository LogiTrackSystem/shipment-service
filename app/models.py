import uuid
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, text
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
        String(12),
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
    fecha_limite_sla = Column(DateTime(timezone=True), nullable=True)
    es_internacional = Column(Boolean, nullable=False, default=False)
    tipo_carga = Column(String(20), nullable=False, server_default="general")
    es_hazmat = Column(Boolean, nullable=False, server_default=text("false"))
    peso_kg = Column(Numeric(10, 2), nullable=False)
    volumen_m3 = Column(Numeric(10, 2), nullable=True)
    vehiculo_id = Column(UUID(as_uuid=True), nullable=True)
    ruta_id = Column(UUID(as_uuid=True), nullable=True)
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


class EnvioEvento(Base):
    __tablename__ = "envio_eventos"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    envio_id = Column(UUID(as_uuid=True), ForeignKey("envios.id"), nullable=False)
    tipo_evento = Column(String(30), nullable=False)
    notas = Column(Text, nullable=True)
    fecha_hora = Column(DateTime(timezone=True), server_default=func.now())