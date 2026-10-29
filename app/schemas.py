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
    es_divisible: bool = False  # solo importa si la carga no cabe en un solo vehículo
    monto_aceptado_cop: Optional[Decimal] = Field(None, ge=0)  # precio de POST /envios/cotizar que el cliente aceptó
    fecha_programada: Optional[datetime] = None  # futura; sin zona horaria se interpreta como hora de Colombia (UTC-5)

    @model_validator(mode="after")
    def _referencias(self):
        if self.cliente_id is not None and self.codigo_cliente is not None:
            raise ValueError("Envíe cliente_id o codigo_cliente, no ambos (una cuenta de cliente puede omitirlos)")
        if (self.origen_id is None) == (self.origen_codigo is None):
            raise ValueError("Debe enviar origen_id o origen_codigo (solo uno de los dos)")
        if (self.destino_id is None) == (self.destino_codigo is None):
            raise ValueError("Debe enviar destino_id o destino_codigo (solo uno de los dos)")
        return self


class EnvioActualizarEstado(BaseModel):
    estado: Literal["en_transito", "con_incidencia", "devuelto"]
    notas: Optional[str] = None


class EnvioReprogramar(BaseModel):
    fecha_programada: datetime
    motivo: Optional[str] = Field(None, max_length=300)


class EnvioCancelar(BaseModel):
    motivo: Optional[str] = Field(None, max_length=300)


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
    envio_padre_id: Optional[uuid.UUID] = None   # si es una parte de un pedido dividido
    parte_numero: Optional[int] = None
    partes_total: Optional[int] = None           # si es un pedido dividido
    partes_entregadas: Optional[int] = None
    fecha_programada: Optional[datetime] = None
    fecha_limite_sla: Optional[datetime] = None
    es_internacional: bool
    tipo_carga: str
    es_hazmat: bool
    es_divisible: bool = False
    peso_kg: Decimal
    volumen_m3: Optional[Decimal] = None
    monto_cop: Optional[Decimal] = None
    ruta_maestra_id: Optional[uuid.UUID] = None
    codigo_ruta: Optional[str] = None
    distancia_km: Optional[Decimal] = None
    duracion_horas: Optional[Decimal] = None
    vehiculo_id: Optional[uuid.UUID] = None
    ruta_id: Optional[uuid.UUID] = None
    placa_vehiculo: Optional[str] = None
    tipo_vehiculo: Optional[str] = None
    conductor_id: Optional[uuid.UUID] = None
    conductor_nombre: Optional[str] = None
    codigo_conductor: Optional[int] = None
    hora_estimada_llegada: Optional[datetime] = None
    motivo_sin_asignacion: Optional[str] = None
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
    simulada: bool = False


# ---------- Usuarios y sesión ----------

ROL = Literal["cliente", "operador", "gestor_flota", "administrador"]


class LoginSolicitud(BaseModel):
    email: str = Field(..., max_length=150, pattern=EMAIL_PATTERN)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return v.strip().lower()


class UsuarioCrear(BaseModel):
    email: str = Field(..., max_length=150, pattern=EMAIL_PATTERN)
    nombre: str = Field(..., min_length=2, max_length=150)
    password: str = Field(..., min_length=8, max_length=128)
    rol: ROL
    cliente_id: Optional[uuid.UUID] = None
    codigo_cliente: Optional[int] = None

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return v.strip().lower()


class UsuarioActualizar(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=150)
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    activo: Optional[bool] = None


class UsuarioLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    nombre: str
    rol: str
    cliente_id: Optional[uuid.UUID] = None
    codigo_cliente: Optional[int] = None
    activo: bool
    ultimo_acceso: Optional[datetime] = None
    creado_en: datetime


ROLES_REGISTRO = ("cliente", "operador", "gestor_flota")


class RegistroSolicitud(BaseModel):
    """Alta pública de cuenta. rol='cliente' (por defecto) crea además el registro de cliente con su código;
    'operador' y 'gestor_flota' exigen el código de acceso que conoce el administrador."""
    nombre: str = Field(..., min_length=2, max_length=150)
    email: str = Field(..., max_length=150, pattern=EMAIL_PATTERN)
    password: str = Field(..., min_length=8, max_length=128)
    rol: str = "cliente"
    # Datos del cliente (solo rol 'cliente')
    tipo_documento: Optional[Literal["CC", "CE", "NIT", "PAS"]] = None
    numero_documento: Optional[str] = Field(None, min_length=3, max_length=30)
    telefono: Optional[str] = Field(None, max_length=30)
    direccion: Optional[str] = Field(None, max_length=255)
    # Solo roles de trabajo
    codigo_acceso: Optional[str] = Field(None, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return v.strip().lower()

    @field_validator("nombre", "numero_documento")
    @classmethod
    def _limpiar(cls, v):
        return v.strip() if v else v

    @field_validator("rol")
    @classmethod
    def _rol(cls, v):
        v = (v or "").strip().lower()
        if v == "administrador":
            raise ValueError("El rol administrador no se puede crear por registro")
        if v not in ROLES_REGISTRO:
            raise ValueError("Rol no válido: use cliente, operador o gestor_flota")
        return v

    @model_validator(mode="after")
    def _segun_rol(self):
        if self.rol == "cliente":
            if not self.tipo_documento or not self.numero_documento:
                raise ValueError("Un cliente debe indicar tipo_documento y numero_documento")
        elif not self.codigo_acceso:
            raise ValueError("Los roles de trabajo requieren el código de acceso del administrador")
        return self


class TokenRespuesta(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    usuario: UsuarioLeer
