import itertools
import uuid

from app.models import Cliente, Envio, Usuario
from app.seguridad import hashear_password

_cod = itertools.count(1)


def crear_cliente(db, nombre="Cliente"):
    n = next(_cod)
    c = Cliente(id=uuid.uuid4(), codigo_cliente=1000 + n, nombre=nombre, email=f"c{n}@x.co")
    db.add(c); db.commit()
    return c


def crear_envio(db, cliente):
    n = next(_cod)
    e = Envio(id=uuid.uuid4(), codigo_envio=f"ENV-{n:08d}", cliente_id=cliente.id, origen="A", destino="B",
              peso_kg=10, estado="pendiente")
    db.add(e); db.commit()
    return e


def crear_usuario(db, email, rol, password="Clave-1234", cliente=None):
    u = Usuario(email=email, nombre=email, password_hash=hashear_password(password), rol=rol,
                cliente_id=cliente.id if cliente else None)
    db.add(u); db.commit()
    return u


def cab(u, rol, cliente=None):
    h = {"x-user-id": str(u.id), "x-user-rol": rol}
    if cliente:
        h["x-cliente-id"] = str(cliente.id)
    return h


# ---------- login ----------

def test_login_correcto_devuelve_token_y_perfil(api, db):
    crear_usuario(db, "admin@x.co", "administrador")
    r = api.post("/auth/login", json={"email": "admin@x.co", "password": "Clave-1234"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["access_token"] and cuerpo["usuario"]["rol"] == "administrador"


def test_login_clave_incorrecta_y_usuario_inexistente_dan_el_mismo_error(api, db):
    crear_usuario(db, "admin@x.co", "administrador")
    a = api.post("/auth/login", json={"email": "admin@x.co", "password": "mala-clave-1"})
    b = api.post("/auth/login", json={"email": "nadie@x.co", "password": "mala-clave-1"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()
    assert a.json()["detail"]["codigo"] == "CREDENCIALES_INVALIDAS"


def test_login_cuenta_inactiva_rechazada(api, db):
    u = crear_usuario(db, "off@x.co", "operador")
    u.activo = False; db.commit()
    assert api.post("/auth/login", json={"email": "off@x.co", "password": "Clave-1234"}).status_code == 401


def test_me_sin_identidad_es_401(api):
    assert api.get("/auth/me").status_code == 401


def test_me_con_identidad(api, db):
    u = crear_usuario(db, "op@x.co", "operador")
    r = api.get("/auth/me", headers=cab(u, "operador"))
    assert r.status_code == 200 and r.json()["email"] == "op@x.co"


# ---------- usuarios (solo administrador) ----------

def test_usuarios_solo_administrador(api, db):
    op = crear_usuario(db, "op@x.co", "operador")
    adm = crear_usuario(db, "adm@x.co", "administrador")
    cuerpo = {"email": "nuevo@x.co", "nombre": "Nuevo", "password": "Clave-1234", "rol": "gestor_flota"}
    assert api.post("/usuarios/", json=cuerpo).status_code == 403                       # sin identidad
    assert api.post("/usuarios/", json=cuerpo, headers=cab(op, "operador")).status_code == 403
    r = api.post("/usuarios/", json=cuerpo, headers=cab(adm, "administrador"))
    assert r.status_code == 201, r.text
    assert "password" not in r.json() and "password_hash" not in r.json()
    assert api.post("/usuarios/", json=cuerpo, headers=cab(adm, "administrador")).status_code == 409


def test_usuario_cliente_requiere_cliente_existente_y_otros_roles_no_lo_llevan(api, db):
    adm = crear_usuario(db, "adm@x.co", "administrador")
    h = cab(adm, "administrador")
    base = {"nombre": "Nombre Prueba", "password": "Clave-1234"}
    assert api.post("/usuarios/", json={**base, "email": "a@x.co", "rol": "cliente"}, headers=h).status_code in (400, 422)
    c = crear_cliente(db)
    r = api.post("/usuarios/", json={**base, "email": "b@x.co", "rol": "cliente", "codigo_cliente": c.codigo_cliente}, headers=h)
    assert r.status_code == 201, r.text
    r = api.post("/usuarios/", json={**base, "email": "c@x.co", "rol": "operador", "codigo_cliente": c.codigo_cliente}, headers=h)
    assert r.status_code in (400, 422)


def test_contrasena_corta_rechazada(api, db):
    adm = crear_usuario(db, "adm@x.co", "administrador")
    r = api.post("/usuarios/", json={"email": "z@x.co", "nombre": "Z", "password": "corta", "rol": "operador"},
                 headers=cab(adm, "administrador"))
    assert r.status_code == 422


# ---------- propiedad de los datos del cliente ----------

def test_cliente_solo_ve_sus_envios(api, db):
    c1, c2 = crear_cliente(db), crear_cliente(db)
    u1 = crear_usuario(db, "c1@x.co", "cliente", cliente=c1)
    e1, e2 = crear_envio(db, c1), crear_envio(db, c2)
    h = cab(u1, "cliente", c1)

    ids = {e["id"] for e in api.get("/envios/", headers=h).json()}
    assert ids == {str(e1.id)}
    # aunque pida los de otro cliente, solo recibe los suyos
    ids = {e["id"] for e in api.get(f"/envios/?cliente_id={c2.id}", headers=h).json()}
    assert ids == {str(e1.id)}

    assert api.get(f"/envios/{e1.id}", headers=h).status_code == 200
    assert api.get(f"/envios/{e2.id}", headers=h).status_code == 404
    assert api.get(f"/envios/{e2.id}/eventos", headers=h).status_code == 404
    assert api.get(f"/envios/{e2.id}/prueba-entrega", headers=h).status_code == 404
    assert api.get(f"/envios/codigo/{e2.codigo_envio}", headers=h).status_code == 404
    assert api.get(f"/envios/codigo/{e1.codigo_envio}", headers=h).status_code == 200


def test_personal_ve_todos_los_envios(api, db):
    c1, c2 = crear_cliente(db), crear_cliente(db)
    op = crear_usuario(db, "op@x.co", "operador")
    crear_envio(db, c1); crear_envio(db, c2)
    assert len(api.get("/envios/", headers=cab(op, "operador")).json()) == 2


def test_llamada_interna_sin_cabeceras_no_se_restringe(api, db):
    c1, c2 = crear_cliente(db), crear_cliente(db)
    crear_envio(db, c1); crear_envio(db, c2)
    assert len(api.get("/envios/").json()) == 2


def test_cliente_solo_ve_su_registro_y_no_puede_escribir(api, db):
    c1, c2 = crear_cliente(db), crear_cliente(db)
    u1 = crear_usuario(db, "c1@x.co", "cliente", cliente=c1)
    h = cab(u1, "cliente", c1)
    assert [c["id"] for c in api.get("/clientes/", headers=h).json()] == [str(c1.id)]
    assert api.get(f"/clientes/{c1.id}", headers=h).status_code == 200
    assert api.get(f"/clientes/{c2.id}", headers=h).status_code == 404
    assert api.get(f"/clientes/codigo/{c2.codigo_cliente}", headers=h).status_code == 404
    assert api.patch(f"/clientes/{c1.id}", json={"nombre": "Otro"}, headers=h).status_code == 403
    assert api.post("/clientes/", json={"nombre": "Cliente Nuevo", "tipo_documento": "CC", "numero_documento": "123456"}, headers=h).status_code == 403


def test_cabecera_de_cliente_sin_cliente_id_es_403(api, db):
    c1 = crear_cliente(db)
    u = crear_usuario(db, "c1@x.co", "cliente", cliente=c1)
    assert api.get("/envios/", headers={"x-user-id": str(u.id), "x-user-rol": "cliente"}).status_code == 403


def test_rol_desconocido_es_403(api):
    assert api.get("/envios/", headers={"x-user-rol": "superusuario"}).status_code == 403
