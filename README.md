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

---

<!-- entrega-final -->

## Descripción

Clientes, cuentas (registro e inicio de sesión con JWT), cotización, envíos con sus estados, programación, pedidos divididos y prueba de entrega.

- **Puerto local:** 8001   ·   **Despliegue activo:** <https://logitrack-shipment.onrender.com> (`/health` y `/metrics` públicos)
- **Imagen Docker:** `<usuario-dockerhub>/logitrack-shipment`   ·   **Repositorio de CI/CD:** `LogiTrackSystem/pipelines`

## Variables de entorno

Copia `.env.example` como `.env` y completa los valores. El `.env` **no se sube** al repositorio.

| Variable | Para qué sirve |
|---|---|
| `DATABASE_URL` | Conexión a la base PostgreSQL del servicio (`postgresql://usuario:clave@host:5432/<base>`). Es un secreto. |
| `RABBITMQ_URL` | URL AMQP del bus de eventos RabbitMQ (CloudAMQP en producción). Es un secreto. |
| `JWT_SECRET` | Secreto para firmar y verificar los tokens (mínimo 16 caracteres; el mismo valor en Shipment y en el gateway). Es un secreto. |
| `ROUTING_SERVICE_URL` | URL base de Routing Service, sin barra final (en local `http://localhost:<puerto>`). |
| `ENTREGA_AUTOMATICA` | Si es `true`, el sistema registra solo la entrega al terminar la simulación del viaje. |
| `FLEET_SERVICE_URL` | URL base de Fleet Service, sin barra final (en local `http://localhost:<puerto>`). |
| `BILLING_SERVICE_URL` | URL base de Billing Service, sin barra final (en local `http://localhost:<puerto>`). |
| `INTERNAL_API_KEY` | Clave compartida entre el gateway y los servicios: exige la cabecera `X-Internal-Key` en todas las rutas salvo `/health` y `/metrics`. Vacía = sin restricción (solo local). Es un secreto. |
| `CODIGO_REGISTRO_PERSONAL` | Código del administrador para registrar operadores y gestores de flota (mínimo 8 caracteres). Es un secreto. |

## Documentación de la API

- **Local** (sin `INTERNAL_API_KEY`): <http://localhost:8001/docs> (Swagger) y `http://localhost:8001/openapi.json`.
- **Producción:** el servicio solo atiende peticiones que llegan por el gateway (con `INTERNAL_API_KEY` activa su `/docs` no es público); la documentación de todas las rutas está en <https://logitrack-gateway.onrender.com/docs>.

## Base de datos

- Migraciones con Alembic (`alembic/`): `alembic upgrade head` (el `Dockerfile` ya lo ejecuta al arrancar).
- `db/esquema.sql`: esquema completo de `shipment_db` generado desde las migraciones.
- `db/datos_ejemplo.sql`: datos de ejemplo ficticios para pruebas manuales.
- Respaldo y restauración: ver `db/README.md`.

## Pruebas

Con el entorno virtual activo y `pip install -r requirements-dev.txt`:

```
pytest tests/unit                    # 2 pruebas unitarias
pytest tests/integration             # 1 prueba de integración
pytest --cov=app --cov-report=term   # toda la suite con cobertura
```

| Prueba | Qué verifica |
|---|---|
| Unitaria 1 | `registro.validar_codigo_personal` |
| Unitaria 2 | `payloads.construir_payload_creado` |
| Integración | registro de un cliente, inicio de sesión y consulta de su perfil |

Archivos: `tests/unit/` y `tests/integration/` (test_codigo_personal.py, test_payload_creado.py, test_flujo_cuenta.py). Cobertura de `app/` medida: **≈ 76 %**; en cada push y Pull Request GitHub Actions la recalcula y guarda `coverage.xml` como artefacto (`cobertura-shipment`).

## Métricas y monitoreo

Expone `GET /metrics` (formato Prometheus: `http_requests_total` y `http_request_duration_*`). Prometheus y el dashboard de Grafana están en el repositorio `logitrack-monitoring`.

## CI/CD

- `.github/workflows/pr.yml`: en cada push (rama distinta de `main`) y en cada Pull Request a `main` ejecuta el CI reutilizable (lint, pruebas con cobertura, `docker build` y prueba de arranque).
- `.github/workflows/deploy.yml`: al fusionar en `main`, y solo con las pruebas en verde, publica la imagen en Docker Hub y despliega en Render (con verificación de `/health` y rollback manual).
- Detalle y estrategia de ramas: `CICD.md` en el repositorio `LogiTrackSystem/pipelines`.

