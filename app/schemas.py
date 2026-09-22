import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

class EnvioCrear(BaseModel):
    cliente_id: uuid.UUID
    origen: str = Field(..., max_length=255)
    destino: str = Field(..., max_length=255)
    fecha_limite_sla: Optional[datetime] = None
    es_internacional: bool = False
    peso_kg: Decimal = Field(..., gt=0)
    volumen_m3: Optional[Decimal] = Field(None, ge=0)

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
    cliente_id: uuid.UUID
    origen: str
    destino: str
    estado: str
    fecha_limite_sla: Optional[datetime] = None
    es_internacional: bool
    peso_kg: Decimal
    volumen_m3: Optional[Decimal] = None
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