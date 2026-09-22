import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from .database import Base

class Envio(Base):
    __tablename__ = "envios"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cliente_id = Column(UUID(as_uuid=True), nullable=False)
    origen = Column(String(255), nullable=False)
    destino = Column(String(255), nullable=False)
    estado = Column(String(20), nullable=False, default="pendiente")
    fecha_limite_sla = Column(DateTime(timezone=True), nullable=True)
    es_internacional = Column(Boolean, nullable=False, default=False)
    peso_kg = Column(Numeric(10, 2), nullable=False)
    volumen_m3 = Column(Numeric(10, 2), nullable=True)
    vehiculo_id = Column(UUID(as_uuid=True), nullable=True)
    ruta_id = Column(UUID(as_uuid=True), nullable=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

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