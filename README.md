# Shipment Service

Microservicio de LogiTrack, corazón transaccional del ciclo de vida de un envío. Publica eventos a RabbitMQ (`shipment.created`, `shipment.delivered`, `shipment.incident`, `shipment.returned`).

## Stack
FastAPI + SQLAlchemy + Alembic + PostgreSQL + RabbitMQ (aio-pika).

## Levantar en local
1. `python -m venv venv && venv\Scripts\activate`
2. `pip install -r requirements.txt`
3. Copiar `.env.example` a `.env` y completar con tus credenciales locales (incluye RabbitMQ).
4. Crear la base de datos `shipment_db` en tu PostgreSQL local.
5. `alembic upgrade head`
6. `uvicorn app.main:app --reload --port 8001`

## Endpoints
- `POST /envios/` — crear envío
- `GET /envios/` — listar envíos (filtros opcionales `estado`, `cliente_id`)
- `GET /envios/{id}` — obtener envío
- `GET /envios/{id}/eventos` — historial de eventos del envío
- `PATCH /envios/{id}/asignar` — asignar vehículo y ruta
- `PATCH /envios/{id}/estado` — actualizar estado
- `POST /envios/{id}/prueba-entrega` — registrar prueba de entrega
- `POST /auth/login` — iniciar sesión (devuelve token Bearer)
- `POST /auth/registro` — alta pública de cuenta (devuelve token, igual que el login)

## Registro de cuentas (`POST /auth/registro`)
- **Cliente** (por defecto): envía `nombre`, `email`, `password`, `tipo_documento` y `numero_documento`. No necesita credenciales de nadie. El sistema crea el cliente y su cuenta, y le asigna el **código de cliente** (`usuario.codigo_cliente`, desde 1000000001); no se digita.
- **Operador / gestor de flota**: `rol` + `codigo_acceso`, que es el valor de la variable `CODIGO_REGISTRO_PERSONAL`, conocido solo por el administrador. Sin esa variable (o con menos de 8 caracteres) este registro queda cerrado. Tras `REGISTRO_MAX_FALLOS` intentos fallidos en `REGISTRO_VENTANA_S` segundos responde 429.
- **Administrador**: nunca por registro; lo crea otro administrador (`POST /usuarios`) o, el primero, `python -m app.crear_usuario`.
- Si el documento ya pertenece a un cliente existente, el registro responde 409 y NO liga la cuenta nueva a ese cliente (quien ya es cliente pide al administrador que le cree el acceso).
