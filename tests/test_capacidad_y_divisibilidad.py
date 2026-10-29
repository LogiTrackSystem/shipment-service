import itertools
import uuid

import httpx
import pytest

from app import flota_client
from app.models import Cliente, Envio, Usuario
from app.routers import envios as router_envios


class RespuestaFalsa:
    def __init__(self, cuerpo, status=200):
        self._cuerpo, self.status_code = cuerpo, status

    def json(self):
        return self._cuerpo


@pytest.fixture()
def fleet(monkeypatch):
    """Fleet simulado: guarda lo que recibe y responde lo que el test indique."""
    estado = {"respuesta": {"viable": True}, "recibido": None, "falla": False}

    class ClienteFalso:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            estado["recibido"] = json
            if estado["falla"]:
                raise httpx.ConnectError("sin conexión")
            return RespuestaFalsa(estado["respuesta"])

    monkeypatch.setattr(flota_client, "FLEET_SERVICE_URL", "http://fleet.test")
    monkeypatch.setattr(flota_client.httpx, "AsyncClient", ClienteFalso)
    return estado


@pytest.fixture()
def entorno(api, db, monkeypatch):
    ubic_o = {"id": str(uuid.uuid4()), "codigo_pais": "CO", "pais": "Colombia", "etiqueta": "Montería"}
    ubic_d = {"id": str(uuid.uuid4()), "codigo_pais": "CO", "pais": "Colombia", "etiqueta": "Bogotá"}

    async def ruta_falsa(*a, **k):
        return {"id": str(uuid.uuid4()), "codigo_ruta": "RUT-1", "distancia_km": 297, "duracion_horas": 5,
                "origen": ubic_o, "destino": ubic_d}

    publicados = []

    async def publicar_falso(clave, cuerpo):
        publicados.append((clave, cuerpo))

    monkeypatch.setattr(router_envios, "obtener_ruta_maestra", ruta_falsa)
    monkeypatch.setattr(router_envios, "publish_event", publicar_falso)
    cliente = Cliente(id=uuid.uuid4(), codigo_cliente=7001, nombre="Cliente Prueba")
    db.add(cliente); db.commit()
    return {"cliente": cliente, "publicados": publicados}


def crear(api, entorno, **extra):
    cuerpo = {"codigo_cliente": entorno["cliente"].codigo_cliente, "origen_codigo": "MTR", "destino_codigo": "BOG",
              "peso_kg": 800, **extra}
    return api.post("/envios/", json=cuerpo)


def test_envio_normal_se_crea_indivisible_por_defecto_y_publica_el_evento(api, entorno, fleet):
    r = crear(api, entorno)
    assert r.status_code == 201, r.text
    assert r.json()["es_divisible"] is False
    assert [c for c, _ in entorno["publicados"]] == ["shipment.created"]
    assert fleet["recibido"]["es_divisible"] is False and fleet["recibido"]["peso_kg"] == 800


def test_es_divisible_viaja_a_fleet_y_se_guarda(api, entorno, fleet):
    r = crear(api, entorno, es_divisible=True)
    assert r.status_code == 201 and r.json()["es_divisible"] is True
    assert fleet["recibido"]["es_divisible"] is True


def test_carga_indivisible_que_excede_se_rechaza_con_el_codigo_y_sin_crear_nada(api, db, entorno, fleet):
    fleet["respuesta"] = {"viable": False, "causa": "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD",
                          "mensaje": "no cabe", "capacidad_maxima_kg": 1000, "requiere_division": True, "division_posible": True}
    r = crear(api, entorno, peso_kg=1200)
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["codigo"] == "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD"
    assert d["capacidad_maxima_kg"] == 1000 and d["requiere_division"] is True and d["division_posible"] is True
    assert db.query(Envio).count() == 0 and entorno["publicados"] == []


def test_carga_divisible_que_requiere_division_crea_el_pedido_con_sus_partes(api, db, entorno, fleet):
    fleet["respuesta"] = {"viable": True, "requiere_division": True,
                          "partes": [{"parte": 1, "peso_kg": 1000, "volumen_m3": None}, {"parte": 2, "peso_kg": 200, "volumen_m3": None}]}
    r = crear(api, entorno, peso_kg=1200, es_divisible=True)
    assert r.status_code == 201, r.text
    assert r.json()["partes_total"] == 2 and db.query(Envio).count() == 3   # el pedido y sus dos partes


def test_si_fleet_no_responde_el_envio_se_acepta(api, entorno, fleet):
    fleet["falla"] = True
    assert crear(api, entorno).status_code == 201


def test_otras_causas_de_fleet_siguen_rechazando(api, entorno, fleet):
    fleet["respuesta"] = {"viable": False, "causa": "SIN_REFRIGERACION", "mensaje": "sin frío"}
    r = crear(api, entorno, tipo_carga="refrigerada")
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "SIN_REFRIGERACION"


def test_cuenta_cliente_crea_envios_siempre_a_su_nombre_aunque_pida_otro_cliente(api, db, entorno, fleet):
    ajeno = Cliente(id=uuid.uuid4(), codigo_cliente=7002, nombre="Otro Cliente")
    db.add(ajeno); db.commit()
    propio = entorno["cliente"]
    cab = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "cliente", "x-cliente-id": str(propio.id)}
    cuerpo = {"codigo_cliente": ajeno.codigo_cliente, "origen_codigo": "MTR", "destino_codigo": "BOG", "peso_kg": 100}
    r = api.post("/envios/", json=cuerpo, headers=cab)
    assert r.status_code == 201 and r.json()["cliente_id"] == str(propio.id)
    # sin indicar cliente también funciona para una cuenta de cliente
    cuerpo.pop("codigo_cliente")
    assert api.post("/envios/", json=cuerpo, headers=cab).status_code == 201
    # el personal sí debe indicar a qué cliente pertenece
    op = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "operador"}
    assert api.post("/envios/", json=cuerpo, headers=op).status_code == 422
