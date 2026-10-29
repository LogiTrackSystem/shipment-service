"""Registro público: los clientes se dan de alta solos; operadores y gestores necesitan el código del administrador."""
import pytest

from app import registro
from app.models import Cliente, Usuario
from app.seguridad import hashear_password

CODIGO = "codigo-secreto-del-admin"


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setenv("CODIGO_REGISTRO_PERSONAL", CODIGO)
    monkeypatch.delenv("REGISTRO_MAX_FALLOS", raising=False)
    monkeypatch.delenv("REGISTRO_VENTANA_S", raising=False)
    registro.reiniciar_limite()
    yield
    registro.reiniciar_limite()


def _cliente(**cambios):
    cuerpo = {"nombre": "Transportes Sol SAS", "email": "Sol@Empresa.co", "password": "Clave-1234",
              "tipo_documento": "NIT", "numero_documento": "900123456"}
    cuerpo.update(cambios)
    return cuerpo


def _personal(rol="operador", codigo=CODIGO, **cambios):
    cuerpo = {"nombre": "Ana Operadora", "email": "ana@logitrack.co", "password": "Clave-1234", "rol": rol}
    if codigo is not None:
        cuerpo["codigo_acceso"] = codigo
    cuerpo.update(cambios)
    return cuerpo


# ---------- cliente ----------

def test_un_cliente_se_registra_sin_credenciales_ni_codigo_y_recibe_su_codigo(api, db):
    r = api.post("/auth/registro", json=_cliente())
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    usuario = cuerpo["usuario"]
    assert cuerpo["access_token"] and usuario["rol"] == "cliente" and usuario["email"] == "sol@empresa.co"
    assert usuario["codigo_cliente"] and usuario["cliente_id"]  # asignados por el sistema, no digitados
    c = db.query(Cliente).one()
    assert str(c.id) == usuario["cliente_id"] and c.numero_documento == "900123456" and c.email == "sol@empresa.co"


def test_el_cliente_puede_iniciar_sesion_despues_de_registrarse(api):
    api.post("/auth/registro", json=_cliente())
    r = api.post("/auth/login", json={"email": "sol@empresa.co", "password": "Clave-1234"})
    assert r.status_code == 200 and r.json()["usuario"]["rol"] == "cliente"


def test_cada_cliente_recibe_un_codigo_distinto(api):
    a = api.post("/auth/registro", json=_cliente()).json()["usuario"]["codigo_cliente"]
    b = api.post("/auth/registro", json=_cliente(email="otro@empresa.co", numero_documento="900999999")).json()["usuario"]["codigo_cliente"]
    assert a != b


def test_el_cliente_ignora_cualquier_codigo_de_acceso_enviado(api):
    r = api.post("/auth/registro", json=_cliente(codigo_acceso="loquesea"))
    assert r.status_code == 201


def test_cliente_sin_documento_se_rechaza(api):
    r = api.post("/auth/registro", json={"nombre": "Pedro", "email": "p@x.co", "password": "Clave-1234"})
    assert r.status_code == 422


def test_correo_repetido_da_409_y_no_deja_un_cliente_huerfano(api, db):
    api.post("/auth/registro", json=_cliente())
    r = api.post("/auth/registro", json=_cliente(numero_documento="900777777"))
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "CORREO_YA_REGISTRADO"
    assert db.query(Cliente).count() == 1 and db.query(Usuario).count() == 1


def test_un_documento_ya_registrado_no_se_liga_a_la_cuenta_nueva(api, db):
    existente = Cliente(codigo_cliente=1000, nombre="Cliente viejo", tipo_documento="NIT", numero_documento="900123456")
    db.add(existente); db.commit()
    r = api.post("/auth/registro", json=_cliente())
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "CLIENTE_YA_REGISTRADO"
    assert db.query(Usuario).count() == 0  # nadie hereda el historial de otro cliente


def test_la_clave_se_guarda_con_hash(api, db):
    api.post("/auth/registro", json=_cliente())
    assert db.query(Usuario).one().password_hash.startswith("pbkdf2_sha256$")


def test_clave_corta_se_rechaza(api):
    assert api.post("/auth/registro", json=_cliente(password="corta")).status_code == 422


# ---------- roles de trabajo ----------

@pytest.mark.parametrize("rol", ["operador", "gestor_flota"])
def test_personal_con_el_codigo_correcto_se_registra_sin_cliente(api, db, rol):
    r = api.post("/auth/registro", json=_personal(rol))
    assert r.status_code == 201, r.text
    u = r.json()["usuario"]
    assert u["rol"] == rol and u["cliente_id"] is None and u["codigo_cliente"] is None
    assert db.query(Cliente).count() == 0


@pytest.mark.parametrize("rol", ["operador", "gestor_flota"])
def test_personal_con_codigo_incorrecto_da_403_y_no_crea_nada(api, db, rol):
    r = api.post("/auth/registro", json=_personal(rol, codigo="adivinando-123"))
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "CODIGO_ACCESO_INVALIDO"
    assert db.query(Usuario).count() == 0


def test_personal_sin_codigo_se_rechaza(api, db):
    assert api.post("/auth/registro", json=_personal(codigo=None)).status_code == 422
    assert db.query(Usuario).count() == 0


def test_el_administrador_no_se_puede_crear_por_registro_ni_con_el_codigo(api, db):
    r = api.post("/auth/registro", json=_personal("administrador"))
    assert r.status_code == 422 and db.query(Usuario).count() == 0
    r = api.post("/auth/registro", json=_personal("Administrador "))
    assert r.status_code == 422


def test_rol_desconocido_se_rechaza(api):
    assert api.post("/auth/registro", json=_personal("superusuario")).status_code == 422


def test_si_el_administrador_no_definio_el_codigo_el_registro_de_personal_queda_cerrado(api, db, monkeypatch):
    monkeypatch.delenv("CODIGO_REGISTRO_PERSONAL")
    r = api.post("/auth/registro", json=_personal())
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "REGISTRO_PERSONAL_DESHABILITADO"
    monkeypatch.setenv("CODIGO_REGISTRO_PERSONAL", "corto")  # menos de 8 caracteres: no cuenta
    assert api.post("/auth/registro", json=_personal(codigo="corto")).status_code == 403
    assert db.query(Usuario).count() == 0
    assert api.post("/auth/registro", json=_cliente()).status_code == 201  # los clientes no dependen del código


def test_el_codigo_no_se_compara_en_minusculas(api):
    assert api.post("/auth/registro", json=_personal(codigo=CODIGO.upper())).status_code == 403


def test_tras_demasiados_fallos_se_bloquea_incluso_el_codigo_correcto(api, monkeypatch):
    monkeypatch.setenv("REGISTRO_MAX_FALLOS", "3")
    for _ in range(3):
        assert api.post("/auth/registro", json=_personal(codigo="mal-codigo-1")).status_code == 403
    r = api.post("/auth/registro", json=_personal())
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert r.json()["detail"]["codigo"] == "DEMASIADOS_INTENTOS"


def test_los_clientes_no_se_ven_afectados_por_el_bloqueo(api, monkeypatch):
    monkeypatch.setenv("REGISTRO_MAX_FALLOS", "1")
    api.post("/auth/registro", json=_personal(codigo="mal-codigo-1"))
    assert api.post("/auth/registro", json=_personal()).status_code == 429
    assert api.post("/auth/registro", json=_cliente()).status_code == 201


def test_el_bloqueo_expira_con_la_ventana(api, monkeypatch):
    monkeypatch.setenv("REGISTRO_MAX_FALLOS", "1")
    monkeypatch.setenv("REGISTRO_VENTANA_S", "1")
    api.post("/auth/registro", json=_personal(codigo="mal-codigo-1"))
    assert api.post("/auth/registro", json=_personal()).status_code == 429
    registro._fallos.clear(); registro._fallos.append(registro.time.monotonic() - 5)  # un fallo viejo
    assert api.post("/auth/registro", json=_personal()).status_code == 201


def test_la_cuenta_de_personal_creada_por_registro_funciona_en_el_login(api):
    api.post("/auth/registro", json=_personal("gestor_flota"))
    r = api.post("/auth/login", json={"email": "ana@logitrack.co", "password": "Clave-1234"})
    assert r.status_code == 200 and r.json()["usuario"]["rol"] == "gestor_flota"


def test_el_registro_no_abre_nada_mas(api, db):
    """El alta por administrador sigue exigiendo rol administrador."""
    r = api.post("/usuarios/", json={"email": "x@x.co", "nombre": "Xx", "password": "Clave-1234", "rol": "operador"},
                 headers={"x-user-id": "00000000-0000-0000-0000-000000000001", "x-user-rol": "operador"})
    assert r.status_code == 403
