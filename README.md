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