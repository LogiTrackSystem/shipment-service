import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app import programacion
from app.models import Envio, EnvioEvento
from app.programacion import HORA_COLOMBIA, activar_vencidos, normalizar_fecha, validar_fecha_programada

from test_capacidad_y_divisibilidad import fleet, entorno, crear  # noqa: F401  (fixtures compartidas)

AHORA = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)
GESTOR = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "gestor_flota"}
OPERADOR = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "operador"}
ADMIN = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "administrador"}


def en(horas=0, dias=0):
    return (datetime.now(timezone.utc) + timedelta(hours=horas, days=dias)).isoformat()


# ---------- validación de fechas ----------

def test_fecha_sin_zona_se_interpreta_como_hora_de_colombia():
    f = normalizar_fecha(datetime(2026, 10, 20, 8, 0))
    assert f.utcoffset() == timedelta(hours=-5) and f.astimezone(timezone.utc).hour == 13


def test_fecha_pasada_o_casi_ahora_se_rechaza():
    for f in (AHORA - timedelta(hours=1), AHORA + timedelta(seconds=30)):
        with pytest.raises(Exception) as exc:
            validar_fecha_programada(f, ahora=AHORA)
        assert exc.value.detail["codigo"] == "FECHA_PROGRAMADA_PASADA"


def test_fecha_demasiado_lejana_y_posterior_al_sla_se_rechazan():
    with pytest.raises(Exception) as exc:
        validar_fecha_programada(AHORA + timedelta(days=400), ahora=AHORA)
    assert exc.value.detail["codigo"] == "FECHA_PROGRAMADA_LEJANA"
    with pytest.raises(Exception) as exc:
        validar_fecha_programada(AHORA + timedelta(days=2), fecha_limite_sla=AHORA + timedelta(days=1), ahora=AHORA)
    assert exc.value.detail["codigo"] == "FECHA_POSTERIOR_AL_SLA"


def test_sin_fecha_no_hay_programacion():
    assert validar_fecha_programada(None) is None


# ---------- crear programado ----------

def test_crear_programado_no_inicia_la_saga_pero_avisa_a_billing(api, db, entorno, fleet):
    r = crear(api, entorno, fecha_programada=en(dias=2))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["estado"] == "programado" and d["fecha_programada"] is not None
    assert [c for c, _ in entorno["publicados"]] == ["shipment.scheduled"]   # NO shipment.created
    assert entorno["publicados"][0][1]["fecha_programada"] is not None
    eventos = [e.tipo_evento for e in db.query(EnvioEvento).all()]
    assert eventos == ["creado", "programado"]


def test_crear_sin_fecha_sigue_igual(api, entorno, fleet):
    r = crear(api, entorno)
    assert r.json()["estado"] == "pendiente" and r.json()["fecha_programada"] is None
    assert [c for c, _ in entorno["publicados"]] == ["shipment.created"]


def test_crear_con_fecha_pasada_se_rechaza_sin_crear_nada(api, db, entorno, fleet):
    r = crear(api, entorno, fecha_programada=en(horas=-2))
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "FECHA_PROGRAMADA_PASADA"
    assert db.query(Envio).count() == 0 and entorno["publicados"] == []


def test_el_evento_trae_los_paises_para_aduanas(api, entorno, fleet):
    crear(api, entorno)
    ev = entorno["publicados"][0][1]
    assert ev["pais_origen"] == "Colombia" and ev["pais_destino"] == "Colombia"


def test_cotizar_valida_la_fecha(api, entorno, fleet):
    cuerpo = {"codigo_cliente": entorno["cliente"].codigo_cliente, "origen_codigo": "MTR", "destino_codigo": "BOG", "peso_kg": 100}
    assert api.post("/envios/cotizar", json={**cuerpo, "fecha_programada": en(horas=-1)}).status_code == 422
    assert api.post("/envios/cotizar", json={**cuerpo, "fecha_programada": en(dias=3)}).status_code == 200


# ---------- calendario ----------

def test_calendario_ordenado_filtrado_y_solo_programados_por_defecto(api, db, entorno, fleet):
    for dias in (5, 1, 3):
        crear(api, entorno, fecha_programada=en(dias=dias))
    crear(api, entorno)  # inmediato: no aparece
    r = api.get("/envios/programados", headers=GESTOR)
    fechas = [e["fecha_programada"] for e in r.json()]
    assert len(fechas) == 3 and fechas == sorted(fechas)
    r = api.get("/envios/programados", params={"desde": en(dias=2), "hasta": en(dias=4)}, headers=OPERADOR)
    assert len(r.json()) == 1


def test_calendario_incluye_activados_si_se_pide(api, db, entorno, fleet):
    crear(api, entorno, fecha_programada=en(dias=1))
    envio = db.query(Envio).one(); envio.estado = "pendiente"; db.commit()
    assert api.get("/envios/programados", headers=ADMIN).json() == []
    assert len(api.get("/envios/programados?incluir_activados=true", headers=ADMIN).json()) == 1


def test_el_calendario_no_es_para_clientes_ni_para_llamadas_sin_identidad(api, entorno):
    cab = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "cliente", "x-cliente-id": str(entorno["cliente"].id)}
    assert api.get("/envios/programados", headers=cab).status_code == 403
    assert api.get("/envios/programados").status_code == 403


# ---------- reprogramar ----------

def test_reprogramar_cambia_la_fecha_y_deja_rastro(api, db, entorno, fleet):
    eid = crear(api, entorno, fecha_programada=en(dias=1)).json()["id"]
    nueva = en(dias=4)
    r = api.patch(f"/envios/{eid}/reprogramar", json={"fecha_programada": nueva, "motivo": "pidió el cliente"}, headers=GESTOR)
    assert r.status_code == 200 and r.json()["estado"] == "programado"
    assert datetime.fromisoformat(r.json()["fecha_programada"]).date() == datetime.fromisoformat(nueva).date()
    ev = db.query(EnvioEvento).filter_by(tipo_evento="reprogramado").one()
    assert "pidió el cliente" in ev.notas


def test_reprogramar_exige_futuro_estado_programado_y_rol(api, db, entorno, fleet):
    eid = crear(api, entorno, fecha_programada=en(dias=1)).json()["id"]
    assert api.patch(f"/envios/{eid}/reprogramar", json={"fecha_programada": en(horas=-1)}, headers=GESTOR).status_code == 422
    assert api.patch(f"/envios/{eid}/reprogramar", json={"fecha_programada": en(dias=2)}, headers=OPERADOR).status_code == 403
    inmediato = crear(api, entorno).json()["id"]
    r = api.patch(f"/envios/{inmediato}/reprogramar", json={"fecha_programada": en(dias=2)}, headers=GESTOR)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "NO_ESTA_PROGRAMADO"
    assert api.patch(f"/envios/{uuid.uuid4()}/reprogramar", json={"fecha_programada": en(dias=2)}, headers=GESTOR).status_code == 404


# ---------- cancelar ----------

@pytest.mark.parametrize("estado", ["programado", "pendiente", "sin_asignacion"])
def test_cancelar_estados_permitidos_publica_el_aviso(api, db, entorno, fleet, monkeypatch, estado):
    publicados = []

    async def publicar(clave, cuerpo):
        publicados.append((clave, cuerpo))

    from app.routers import envios as router_envios
    monkeypatch.setattr(router_envios, "_publicar_con_reintentos", publicar)
    eid = crear(api, entorno, fecha_programada=en(dias=1)).json()["id"]
    envio = db.query(Envio).one(); envio.estado = estado; db.commit()

    r = api.post(f"/envios/{eid}/cancelar", json={"motivo": "cliente desistió"}, headers=GESTOR)
    assert r.status_code == 200 and r.json()["estado"] == "cancelado"
    assert publicados[0][0] == "shipment.cancelled" and publicados[0][1]["estado_anterior"] == estado
    assert db.query(EnvioEvento).filter_by(tipo_evento="cancelado").one().notas == "cliente desistió"


@pytest.mark.parametrize("estado", ["asignado", "en_transito", "entregado", "devuelto", "retenido_aduana", "cancelado", "con_incidencia"])
def test_no_se_cancela_lo_que_ya_tiene_vehiculo_o_termino(api, db, entorno, fleet, estado):
    eid = crear(api, entorno).json()["id"]
    envio = db.query(Envio).one(); envio.estado = estado; db.commit()
    r = api.post(f"/envios/{eid}/cancelar", headers=ADMIN)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "NO_SE_PUEDE_CANCELAR"
    assert db.query(Envio).one().estado == estado


def test_cancelar_solo_gestor_y_administrador(api, entorno, fleet):
    eid = crear(api, entorno).json()["id"]
    cab_cliente = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "cliente", "x-cliente-id": str(entorno["cliente"].id)}
    for cab in (OPERADOR, cab_cliente, {}):
        assert api.post(f"/envios/{eid}/cancelar", headers=cab).status_code == 403


def test_un_envio_cancelado_ignora_una_asignacion_tardia(api, db, entorno, fleet, monkeypatch):
    """Si Routing alcanzó a asignar justo antes de la cancelación, el aviso de asignación no lo revive."""
    from app import events
    eid = crear(api, entorno).json()["id"]
    envio = db.query(Envio).one(); envio.estado = "cancelado"; db.commit()
    fabrica = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(events, "SessionLocal", fabrica)
    asyncio.run(events._procesar_route_assigned({"envio_id": eid, "ruta_id": str(uuid.uuid4()), "placa": "AAA111"}))
    db2 = fabrica()
    try:
        assert db2.query(Envio).one().estado == "cancelado" and db2.query(Envio).one().ruta_id is None
    finally:
        db2.close()


# ---------- vigilante: arranque a la hora ----------

def _programar(api, entorno, db, **extra):
    eid = crear(api, entorno, fecha_programada=en(dias=1), **extra).json()["id"]
    entorno["publicados"].clear()
    return eid


def _fabrica(db):
    return sessionmaker(bind=db.get_bind())


def test_el_vigilante_activa_solo_lo_vencido_y_publica_shipment_created(api, db, entorno, fleet):
    vencido = _programar(api, entorno, db)
    futuro = crear(api, entorno, fecha_programada=en(dias=10)).json()["id"]
    entorno["publicados"].clear()
    publicados = []

    async def publicar(clave, cuerpo):
        publicados.append((clave, cuerpo))

    ahora = datetime.now(timezone.utc) + timedelta(days=2)       # ya pasó la hora del primero
    n = asyncio.run(activar_vencidos(_fabrica(db), publicar, ahora))
    assert n == 1
    assert [c for c, _ in publicados] == ["shipment.created"] and publicados[0][1]["envio_id"] == vencido
    db.expire_all()
    estados = {str(e.id): e.estado for e in db.query(Envio).all()}
    assert estados[vencido] == "pendiente" and estados[futuro] == "programado"
    assert db.query(EnvioEvento).filter_by(tipo_evento="activado_programacion").count() == 1


def test_el_evento_diferido_es_igual_al_de_un_envio_normal(api, db, entorno, fleet):
    inmediato = crear(api, entorno)
    ev_normal = entorno["publicados"][0][1]
    programado = _programar(api, entorno, db)
    publicados = []

    async def publicar(clave, cuerpo):
        publicados.append(cuerpo)

    asyncio.run(activar_vencidos(_fabrica(db), publicar, datetime.now(timezone.utc) + timedelta(days=2)))
    ev = publicados[0]
    claves = lambda d: set(d) - {"envio_id", "codigo_envio", "fecha_programada"}
    assert claves(ev) == claves(ev_normal)
    for k in ("pais_origen", "pais_destino", "ruta_maestra_id", "peso_kg", "monto_cop", "cliente_id", "distancia_km"):
        assert k in ev


def test_si_falla_la_publicacion_el_envio_sigue_programado_y_se_reintenta(api, db, entorno, fleet):
    eid = _programar(api, entorno, db)
    intentos = []

    async def falla(clave, cuerpo):
        intentos.append(1)
        raise ConnectionError("RabbitMQ caído")

    futuro = datetime.now(timezone.utc) + timedelta(days=2)
    assert asyncio.run(activar_vencidos(_fabrica(db), falla, futuro)) == 0
    db.expire_all()
    assert db.query(Envio).one().estado == "programado" and db.query(EnvioEvento).filter_by(tipo_evento="activado_programacion").count() == 0

    publicados = []

    async def bien(clave, cuerpo):
        publicados.append(clave)

    assert asyncio.run(activar_vencidos(_fabrica(db), bien, futuro)) == 1 and publicados == ["shipment.created"]


def test_un_envio_cancelado_o_ya_activo_no_se_vuelve_a_activar(api, db, entorno, fleet):
    a = _programar(api, entorno, db)
    envio = db.query(Envio).one(); envio.estado = "cancelado"; db.commit()
    publicados = []

    async def publicar(clave, cuerpo):
        publicados.append(clave)

    futuro = datetime.now(timezone.utc) + timedelta(days=2)
    assert asyncio.run(activar_vencidos(_fabrica(db), publicar, futuro)) == 0 and publicados == []


def test_activar_dos_veces_no_duplica(api, db, entorno, fleet):
    _programar(api, entorno, db)
    publicados = []

    async def publicar(clave, cuerpo):
        publicados.append(clave)

    futuro = datetime.now(timezone.utc) + timedelta(days=2)
    f = _fabrica(db)
    assert asyncio.run(activar_vencidos(f, publicar, futuro)) == 1
    assert asyncio.run(activar_vencidos(f, publicar, futuro)) == 0 and publicados == ["shipment.created"]
