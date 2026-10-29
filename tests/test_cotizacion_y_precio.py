import asyncio
import uuid

import httpx
import pytest

from app import facturacion_client
from app.models import Cliente, Envio
from app.routers import envios as router_envios

from test_capacidad_y_divisibilidad import fleet, entorno, crear, RespuestaFalsa  # noqa: F401  (fixtures compartidas)


@pytest.fixture()
def billing(monkeypatch):
    """Billing simulado a nivel del router: calcula 20.000 + t × km × 280 (mínimo 50.000)."""
    estado = {"llamadas": [], "caido": False, "extra": 0}

    async def calcular(peso_kg, distancia_km, cliente_id=None):
        estado["llamadas"].append((float(peso_kg), float(distancia_km), cliente_id))
        monto = max(50000, round(20000 + float(peso_kg) / 1000 * float(distancia_km) * 280)) + estado["extra"]
        return {"cotizacion_id": str(uuid.uuid4()), "monto_cop": float(monto), "moneda": "COP", "desglose": {"base_cop": 20000.0}}

    monkeypatch.setattr(router_envios, "calcular_cotizacion", calcular)
    return estado


# ---------- POST /envios/cotizar ----------

def cotizar(api, entorno, **extra):
    cuerpo = {"codigo_cliente": entorno["cliente"].codigo_cliente, "origen_codigo": "MTR", "destino_codigo": "BOG", "peso_kg": 800, **extra}
    return api.post("/envios/cotizar", json=cuerpo)


def test_cotizar_devuelve_precio_viabilidad_y_no_crea_nada(api, db, entorno, fleet, billing):
    r = cotizar(api, entorno)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["monto_cop"] == 86528 and d["moneda"] == "COP" and d["distancia_km"] == 297
    assert d["viabilidad"]["viable"] is True and d["puede_crear"] is True and d["facturacion_activa"] is not None
    assert db.query(Envio).count() == 0 and entorno["publicados"] == []


def test_cotizar_carga_inviable_no_da_precio(api, entorno, fleet, billing):
    fleet["respuesta"] = {"viable": False, "causa": "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD", "mensaje": "no cabe",
                          "capacidad_maxima_kg": 1000, "requiere_division": True, "division_posible": True}
    d = cotizar(api, entorno, peso_kg=1200).json()
    assert d["viabilidad"]["viable"] is False and d["viabilidad"]["capacidad_maxima_kg"] == 1000
    assert d["monto_cop"] is None and d["puede_crear"] is False and billing["llamadas"] == []


def test_cotizar_carga_divisible_muestra_el_plan_y_el_precio_del_pedido_completo(api, entorno, fleet, billing):
    fleet["respuesta"] = {"viable": True, "requiere_division": True, "division_posible": True,
                          "partes": [{"parte": 1, "peso_kg": 1000}, {"parte": 2, "peso_kg": 200}]}
    d = cotizar(api, entorno, peso_kg=1200, es_divisible=True).json()
    assert d["monto_cop"] is not None and len(d["viabilidad"]["partes"]) == 2
    assert d["puede_crear"] is True and "2 envíos" in d["aviso"]
    assert billing["llamadas"][-1][0] == 1200.0     # el precio se calcula sobre el peso total


def test_cotizar_sin_billing_configurado_responde_sin_precio(api, entorno, fleet):
    d = cotizar(api, entorno).json()
    assert d["monto_cop"] is None and d["facturacion_activa"] is False and d["puede_crear"] is True


def test_cotizar_con_fleet_caido_no_bloquea(api, entorno, fleet, billing):
    fleet["falla"] = True
    d = cotizar(api, entorno).json()
    assert d["viabilidad"] is None and d["monto_cop"] == 86528 and d["puede_crear"] is True


# ---------- POST /envios con precio ----------

def test_crear_con_el_precio_aceptado_guarda_el_monto_y_lo_publica(api, db, entorno, fleet, billing):
    r = crear(api, entorno, monto_aceptado_cop=86528)
    assert r.status_code == 201, r.text
    assert float(r.json()["monto_cop"]) == 86528
    (clave, evento), = entorno["publicados"]
    assert clave == "shipment.created" and evento["monto_cop"] == 86528 and evento["moneda"] == "COP"
    assert db.query(Envio).one().monto_cop == 86528


def test_sin_precio_aceptado_se_rechaza(api, db, entorno, fleet, billing):
    r = crear(api, entorno)
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "PRECIO_NO_ACEPTADO"
    assert r.json()["detail"]["monto_actual_cop"] == 86528
    assert db.query(Envio).count() == 0 and entorno["publicados"] == []


def test_si_el_precio_cambio_responde_409_y_no_crea_nada(api, db, entorno, fleet, billing):
    billing["extra"] = 1000     # la tarifa subió entre la cotización y la creación
    r = crear(api, entorno, monto_aceptado_cop=86528)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["codigo"] == "PRECIO_CAMBIO" and d["monto_aceptado_cop"] == 86528 and d["monto_actual_cop"] == 87528
    assert db.query(Envio).count() == 0 and entorno["publicados"] == []


def test_precio_aceptado_de_menos_no_pasa(api, entorno, fleet, billing):
    assert crear(api, entorno, monto_aceptado_cop=50000).status_code == 409


def test_el_precio_se_calcula_con_el_peso_y_la_distancia_de_la_ruta(api, entorno, fleet, billing):
    crear(api, entorno, peso_kg=1000, monto_aceptado_cop=103_160)
    assert billing["llamadas"][-1][:2] == (1000.0, 297.0)


def test_sin_billing_configurado_el_envio_se_crea_sin_precio(api, db, entorno, fleet):
    r = crear(api, entorno)
    assert r.status_code == 201 and r.json()["monto_cop"] is None


def test_cuenta_cliente_cotiza_y_crea_a_su_nombre(api, db, entorno, fleet, billing):
    propio = entorno["cliente"]
    cab = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "cliente", "x-cliente-id": str(propio.id)}
    cuerpo = {"origen_codigo": "MTR", "destino_codigo": "BOG", "peso_kg": 800}
    assert api.post("/envios/cotizar", json=cuerpo, headers=cab).status_code == 200
    assert billing["llamadas"][-1][2] == propio.id
    r = api.post("/envios/", json={**cuerpo, "monto_aceptado_cop": 86528}, headers=cab)
    assert r.status_code == 201 and r.json()["cliente_id"] == str(propio.id)


# ---------- cliente HTTP de Billing ----------

class _Resp:
    def __init__(self, status, cuerpo=None): self.status_code, self._c = status, cuerpo or {}
    def json(self): return self._c


def _cliente_http(monkeypatch, comportamiento):
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None): return comportamiento(url, json)
    monkeypatch.setattr(facturacion_client, "BILLING_SERVICE_URL", "http://billing.test")
    monkeypatch.setattr(facturacion_client.httpx, "AsyncClient", C)


def test_cliente_billing_sin_url_devuelve_none(monkeypatch):
    monkeypatch.setattr(facturacion_client, "BILLING_SERVICE_URL", None)
    assert asyncio.run(facturacion_client.calcular_cotizacion(100, 10)) is None


def test_cliente_billing_envia_peso_distancia_y_cliente(monkeypatch):
    visto = {}
    def ok(url, cuerpo):
        visto.update(url=url, cuerpo=cuerpo); return _Resp(201, {"monto_cop": 50000})
    _cliente_http(monkeypatch, ok)
    cid = uuid.uuid4()
    assert asyncio.run(facturacion_client.calcular_cotizacion(800, 297, cid))["monto_cop"] == 50000
    assert visto["url"].endswith("/cotizaciones/calcular") and visto["cuerpo"] == {"peso_kg": 800.0, "distancia_km": 297.0, "cliente_id": str(cid)}


@pytest.mark.parametrize("falla", ["conexion", "http500"])
def test_si_billing_esta_configurado_pero_no_responde_se_rechaza_con_503(monkeypatch, falla):
    def comportamiento(url, cuerpo):
        if falla == "conexion":
            raise httpx.ConnectError("caído")
        return _Resp(500)
    _cliente_http(monkeypatch, comportamiento)
    with pytest.raises(Exception) as exc:
        asyncio.run(facturacion_client.calcular_cotizacion(100, 10))
    assert exc.value.status_code == 503 and exc.value.detail["codigo"] == "FACTURACION_NO_DISPONIBLE"
