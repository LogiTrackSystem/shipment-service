-- Datos de ejemplo de shipment_db: 2 clientes ficticios. Aplicar DESPUÉS de esquema.sql.
-- No incluye usuarios (cuentas con contraseña): se crean con POST /auth/registro o 'python -m app.crear_usuario'.
BEGIN;

INSERT INTO clientes (id, nombre, tipo_documento, numero_documento, email, telefono, direccion)
VALUES
 ('33333333-cccc-4ccc-8ccc-000000000001', 'Transportes Ejemplo SAS', 'NIT', '900000001', 'contacto@ejemplo-uno.test', '3000000001', 'Calle 1 # 2-3, Montería'),
 ('33333333-cccc-4ccc-8ccc-000000000002', 'Comercial Muestra Ltda',  'NIT', '900000002', 'ventas@ejemplo-dos.test',   '3000000002', 'Carrera 4 # 5-6, Bogotá');

COMMIT;
