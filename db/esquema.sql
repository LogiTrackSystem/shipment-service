-- Esquema de shipment_db (shipment-service): SQL generado por 'alembic upgrade head --sql' a partir de alembic/versions.
-- Crea todas las tablas, secuencias y restricciones. No contiene datos.
BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 54382e256ab0

CREATE TABLE envios (
    id UUID NOT NULL, 
    cliente_id UUID NOT NULL, 
    origen VARCHAR(255) NOT NULL, 
    destino VARCHAR(255) NOT NULL, 
    estado VARCHAR(20) NOT NULL, 
    fecha_limite_sla TIMESTAMP WITH TIME ZONE, 
    es_internacional BOOLEAN NOT NULL, 
    peso_kg NUMERIC(10, 2) NOT NULL, 
    volumen_m3 NUMERIC(10, 2), 
    vehiculo_id UUID, 
    ruta_id UUID, 
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT now(), 
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT now(), 
    PRIMARY KEY (id)
);

CREATE TABLE envio_eventos (
    id UUID NOT NULL, 
    envio_id UUID NOT NULL, 
    tipo_evento VARCHAR(30) NOT NULL, 
    notas TEXT, 
    fecha_hora TIMESTAMP WITH TIME ZONE DEFAULT now(), 
    PRIMARY KEY (id), 
    FOREIGN KEY(envio_id) REFERENCES envios (id)
);

CREATE TABLE prueba_entrega (
    id UUID NOT NULL, 
    envio_id UUID NOT NULL, 
    url_firma VARCHAR(500), 
    url_foto VARCHAR(500), 
    nombre_receptor VARCHAR(150) NOT NULL, 
    entregado_en TIMESTAMP WITH TIME ZONE DEFAULT now(), 
    PRIMARY KEY (id), 
    FOREIGN KEY(envio_id) REFERENCES envios (id), 
    UNIQUE (envio_id)
);

INSERT INTO alembic_version (version_num) VALUES ('54382e256ab0') RETURNING alembic_version.version_num;

-- Running upgrade 54382e256ab0 -> e9f61ff1aab3

CREATE SEQUENCE IF NOT EXISTS seq_codigo_cliente START WITH 1000000001 MINVALUE 1000000001 MAXVALUE 9999999999;

CREATE SEQUENCE IF NOT EXISTS seq_codigo_envio START WITH 1 MINVALUE 1 MAXVALUE 99999999;

CREATE TABLE clientes (
    id UUID NOT NULL, 
    codigo_cliente BIGINT DEFAULT nextval('seq_codigo_cliente') NOT NULL, 
    nombre VARCHAR(150) NOT NULL, 
    tipo_documento VARCHAR(10), 
    numero_documento VARCHAR(30), 
    email VARCHAR(150), 
    telefono VARCHAR(30), 
    direccion VARCHAR(255), 
    activo BOOLEAN DEFAULT true NOT NULL, 
    es_historico BOOLEAN DEFAULT false NOT NULL, 
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_clientes_codigo_cliente UNIQUE (codigo_cliente), 
    CONSTRAINT uq_clientes_documento UNIQUE (tipo_documento, numero_documento)
);

ALTER SEQUENCE seq_codigo_cliente OWNED BY clientes.codigo_cliente;

INSERT INTO clientes (id, nombre, es_historico)
        SELECT c.cliente_id, 'Cliente historico ' || left(c.cliente_id::text, 8), true
        FROM (SELECT cliente_id, min(creado_en) AS primero FROM envios GROUP BY cliente_id) c
        ORDER BY c.primero;

ALTER TABLE envios ADD COLUMN codigo_envio VARCHAR(12) DEFAULT 'ENV-' || lpad(nextval('seq_codigo_envio')::text, 8, '0') NOT NULL;

ALTER TABLE envios ADD CONSTRAINT uq_envios_codigo_envio UNIQUE (codigo_envio);

ALTER SEQUENCE seq_codigo_envio OWNED BY envios.codigo_envio;

ALTER TABLE envios ADD COLUMN tipo_carga VARCHAR(20) DEFAULT 'general' NOT NULL;

ALTER TABLE envios ADD COLUMN es_hazmat BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE envios ADD CONSTRAINT fk_envios_cliente_id FOREIGN KEY(cliente_id) REFERENCES clientes (id);

UPDATE alembic_version SET version_num='e9f61ff1aab3' WHERE alembic_version.version_num = '54382e256ab0';

-- Running upgrade e9f61ff1aab3 -> d5292dbc925e

ALTER TABLE envios ADD COLUMN origen_id UUID;

ALTER TABLE envios ADD COLUMN destino_id UUID;

ALTER TABLE envios ADD COLUMN codigo_pais_origen VARCHAR(2);

ALTER TABLE envios ADD COLUMN codigo_pais_destino VARCHAR(2);

ALTER TABLE envios ADD COLUMN ruta_maestra_id UUID;

ALTER TABLE envios ADD COLUMN codigo_ruta VARCHAR(12);

ALTER TABLE envios ADD COLUMN distancia_km NUMERIC(10, 2);

ALTER TABLE envios ADD COLUMN duracion_horas NUMERIC(8, 2);

UPDATE alembic_version SET version_num='d5292dbc925e' WHERE alembic_version.version_num = 'e9f61ff1aab3';

-- Running upgrade d5292dbc925e -> add9ab9c4d68

ALTER TABLE envios ADD COLUMN conductor_id UUID;

ALTER TABLE envios ADD COLUMN placa_vehiculo VARCHAR(20);

ALTER TABLE envios ADD COLUMN tipo_vehiculo VARCHAR(20);

ALTER TABLE envios ADD COLUMN conductor_nombre VARCHAR(150);

ALTER TABLE envios ADD COLUMN codigo_conductor BIGINT;

ALTER TABLE envios ADD COLUMN hora_estimada_llegada TIMESTAMP WITH TIME ZONE;

ALTER TABLE envios ADD COLUMN motivo_sin_asignacion TEXT;

ALTER TABLE envios ADD COLUMN estado_previo VARCHAR(20);

UPDATE alembic_version SET version_num='add9ab9c4d68' WHERE alembic_version.version_num = 'd5292dbc925e';

-- Running upgrade add9ab9c4d68 -> 280229b635b4

ALTER TABLE prueba_entrega ADD COLUMN simulada BOOLEAN DEFAULT false NOT NULL;

UPDATE alembic_version SET version_num='280229b635b4' WHERE alembic_version.version_num = 'add9ab9c4d68';

-- Running upgrade 280229b635b4 -> a7c3e91d2b40

CREATE TABLE usuarios (
    id UUID NOT NULL, 
    email VARCHAR(150) NOT NULL, 
    nombre VARCHAR(150) NOT NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    rol VARCHAR(20) NOT NULL, 
    cliente_id UUID, 
    activo BOOLEAN DEFAULT true NOT NULL, 
    ultimo_acceso TIMESTAMP WITH TIME ZONE, 
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    actualizado_en TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(cliente_id) REFERENCES clientes (id), 
    UNIQUE (email), 
    CONSTRAINT ck_usuarios_rol CHECK (rol IN ('cliente','operador','gestor_flota','administrador')), 
    CONSTRAINT ck_usuarios_cliente_requerido CHECK (rol <> 'cliente' OR cliente_id IS NOT NULL)
);

UPDATE alembic_version SET version_num='a7c3e91d2b40' WHERE alembic_version.version_num = '280229b635b4';

-- Running upgrade a7c3e91d2b40 -> b2e5f1a8c3d7

ALTER TABLE envios ADD COLUMN es_divisible BOOLEAN DEFAULT false NOT NULL;

UPDATE alembic_version SET version_num='b2e5f1a8c3d7' WHERE alembic_version.version_num = 'a7c3e91d2b40';

-- Running upgrade b2e5f1a8c3d7 -> d1f7a3b9e5c2

ALTER TABLE envios ADD COLUMN monto_cop NUMERIC(14, 2);

UPDATE alembic_version SET version_num='d1f7a3b9e5c2' WHERE alembic_version.version_num = 'b2e5f1a8c3d7';

-- Running upgrade d1f7a3b9e5c2 -> e3a9c5d7f1b4

ALTER TABLE envios ADD COLUMN fecha_programada TIMESTAMP WITH TIME ZONE;

ALTER TABLE envios ADD COLUMN pais_origen VARCHAR(100);

ALTER TABLE envios ADD COLUMN pais_destino VARCHAR(100);

CREATE INDEX ix_envios_fecha_programada ON envios (fecha_programada);

UPDATE alembic_version SET version_num='e3a9c5d7f1b4' WHERE alembic_version.version_num = 'd1f7a3b9e5c2';

-- Running upgrade e3a9c5d7f1b4 -> f6b1d8e2a395

ALTER TABLE envios ADD COLUMN envio_padre_id UUID;

ALTER TABLE envios ADD COLUMN parte_numero INTEGER;

ALTER TABLE envios ADD COLUMN partes_total INTEGER;

ALTER TABLE envios ADD COLUMN partes_entregadas INTEGER;

ALTER TABLE envios ADD CONSTRAINT fk_envios_envio_padre FOREIGN KEY(envio_padre_id) REFERENCES envios (id);

CREATE INDEX ix_envios_envio_padre_id ON envios (envio_padre_id);

ALTER TABLE envios ALTER COLUMN codigo_envio TYPE VARCHAR(20);

UPDATE alembic_version SET version_num='f6b1d8e2a395' WHERE alembic_version.version_num = 'e3a9c5d7f1b4';

COMMIT;

