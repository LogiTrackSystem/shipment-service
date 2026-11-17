# Base de datos `shipment_db`

| Archivo | Contenido |
|---|---|
| `esquema.sql` | Tablas, secuencias y restricciones (SQL generado con `alembic upgrade head --sql`); no contiene datos |
| `datos_ejemplo.sql` | Datos ficticios para pruebas manuales |

## Crear la base desde cero

1. Crea la base vacía `shipment_db` en PostgreSQL.
2. **Esquema:** `psql "<URL_DE_LA_BASE>" -f db/esquema.sql` (o bien `alembic upgrade head` con `DATABASE_URL` apuntando a ella; el resultado es el mismo).
3. **Datos de ejemplo** (opcional): `psql "<URL_DE_LA_BASE>" -f db/datos_ejemplo.sql`.

## Respaldo y restauración

```
# Respaldo (formato comprimido)
pg_dump -Fc --no-owner --no-privileges -f shipment_db.dump "<URL_EXTERNA_DE_LA_BASE>"

# Restauración en otra base (vacía o existente)
pg_restore --no-owner --no-privileges --clean --if-exists -d "<URL_DE_DESTINO>" shipment_db.dump
```

> Este respaldo incluye la tabla `usuarios` (contraseñas en hash): trátalo como confidencial. Para excluir sus datos agrega `--exclude-table-data=usuarios` a `pg_dump`.

`<URL_...>` es la cadena de conexión real; **no la guardes en el repositorio** ni la pegues en chats o documentos. Los archivos `*.dump` no se suben a GitHub.
