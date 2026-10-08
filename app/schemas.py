import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# ---------- Clientes ----------

class ClienteCrear(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=150)
    tipo_documento: Literal["CC", "CE", "NIT", "PAS"]
    numero_documento: str = Field(..., min_length=3, max_length=30)
    email: Optional[str] = Field(None, max_length=150, pattern=EMAIL_PATTERN)
    telefono: Optional[str] = Field(None, max_length=30)
    direccion: Optional[str] = Field(None, max_length=255)

    @field_validator("nombre", "numero_documento")
    @classmethod
    def _limpiar(cls, v):
        return v.strip() if v else v


class ClienteActualizar(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=150)
    tipo_documento: Optional[Literal["CC", "CE", "NIT", "PAS"]] = None
    numero_documento: Optional[str] = Field(None, min_length=3, max_length=30)
    email: Optional[str] = Field(None, max_length=150, pattern=EMAIL_PATTERN)
    telefono: Optional[str] = Field(None, max_length=30)
    direccion: Optional[str] = Field(None, max_length=255)
    activo: Optional[bool] = None

    @field_validator("nombre", "numero_documento")
    @classmethod
    def _limpiar(cls, v):
        return v.strip() if v else v


class ClienteLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    codigo_cliente: int
    nombre: str
    tipo_documento: Optional[str] = None
    numero_documento: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    activo: bool
    es_historico: bool
    creado_en: datetime


# ---------- Envíos ----------

class EnvioCrear(BaseModel):
    cliente_id: Optional[uuid.UUID] = None
    codigo_cliente: Optional[int] = None
    origen_id: Optional[uuid.UUID] = None
    origen_codigo: Optional[str] = Field(None, max_length=12)
    destino_id: Optional[uuid.UUID] = None
    destino_codigo: Optional[str] = Field(None, max_length=12)
    fecha_limite_sla: Optional[datetime] = None
    es_internacional: Optional[bool] = None
    peso_kg: Decimal = Field(..., gt=0)
    volumen_m3: Optional[Decimal] = Field(None, ge=0)
    tipo_carga: Literal["general", "refrigerada"] = "general"
    es_hazmat: bool = False

    @model_validator(mode="after")
    def _referencias(self):
        if (self.cliente_id is None) == (self.codigo_cliente is None):
            raise ValueError("Debe enviar cliente_id o codigo_cliente (solo uno de los dos)")
        if (self.origen_id is None) == (self.origen_codigo is None):
            raise ValueError("Debe enviar origen_id o origen_codigo (solo uno de los dos)")
        if (self.destino_id is None) == (self.destino_codigo is None):
            raise ValueError("Debe enviar destino_id o destino_codigo (solo uno de los dos)")
        return self

class EnvioAsignar(BaseModel):
    vehiculo_id: uuid.UUID
    ruta_id: Optional[uuid.UUID] = None


class EnvioActualizarEstado(BaseModel):
    estado: Literal["en_transito", "con_incidencia", "devuelto"]
    notas: Optional[str] = None


class PruebaEntregaCrear(BaseModel):
    nombre_receptor: str = Field(..., max_length=150)
    url_firma: Optional[str] = None
    url_foto: Optional[str] = None


class EnvioEventoLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tipo_evento: str
    notas: Optional[str] = None
    fecha_hora: datetime


class EnvioLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    codigo_envio: str
    cliente_id: uuid.UUID
    codigo_cliente: Optional[int] = None
    origen: str
    destino: str
    origen_id: Optional[uuid.UUID] = None
    destino_id: Optional[uuid.UUID] = None
    codigo_pais_origen: Optional[str] = None
    codigo_pais_destino: Optional[str] = None
    estado: str
    fecha_limite_sla: Optional[datetime] = None
    es_internacional: bool
    tipo_carga: str
    es_hazmat: bool
    peso_kg: Decimal
    volumen_m3: Optional[Decimal] = None
    ruta_maestra_id: Optional[uuid.UUID] = None
    codigo_ruta: Optional[str] = None
    distancia_km: Optional[Decimal] = None
    duracion_horas: Optional[Decimal] = None
    vehiculo_id: Optional[uuid.UUID] = None
    ruta_id: Optional[uuid.UUID] = None
    creado_en: datetime
    actualizado_en: datetime

class PruebaEntregaLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    envio_id: uuid.UUID
    url_firma: Optional[str] = None
    url_foto: Optional[str] = None
    nombre_receptor: str
    entregado_en: datetime