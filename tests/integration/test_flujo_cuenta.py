"""Integración: registro de un cliente -> inicio de sesión -> consulta de su perfil."""


def test_cliente_se_registra_inicia_sesion_y_consulta_su_perfil(api):
    cuerpo = {"nombre": "Transportes Sol SAS", "email": "sol@empresa.co", "password": "Clave-1234",
              "tipo_documento": "NIT", "numero_documento": "900123456"}
    registro = api.post("/auth/registro", json=cuerpo)
    login = api.post("/auth/login", json={"email": "sol@empresa.co", "password": "Clave-1234"})
    usuario = login.json()["usuario"]
    # el gateway reenvía la identidad en cabeceras; aquí se simulan
    perfil = api.get("/auth/me", headers={"X-User-Id": usuario["id"], "X-User-Rol": "cliente", "X-Cliente-Id": usuario["cliente_id"]})
    assert registro.status_code == 201 and login.status_code == 200
    assert perfil.status_code == 200 and perfil.json()["email"] == "sol@empresa.co"
    assert api.post("/auth/login", json={"email": "sol@empresa.co", "password": "mala"}).status_code == 401
