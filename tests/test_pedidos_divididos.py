import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app import events, programacion
from app.estados import agregar_estado_padre
from app.models import Cliente, Envio, EnvioEvento
from app.routers import envios as router_envios

from test_capacidad_y_divisibilidad import fleet, entorno, crear  # noqa: F401  (fixtures compartidas)

GESTOR = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "gestor_flota"}
OPERADOR = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "operador"}
PLAN_1200 = [{"parte": 1, "peso_kg": 1000, "volumen_m3": 10.0}, {"parte": 2, "peso_kg": 200, "volumen_m3": 2.0}]


def en(dias=0, horas=0):
    return (datetime.now(timezone.utc) + timedelta(days=dias, hours=horas)).isoformat()


@pytest.fixture()
def plan(fleet):
    fleet["respuesta"] = {"viable": True, "requiere_division": True, "division_posible": True, "partes": PLAN_1200}
    return fleet


def pedido(api, entorno, **extra):
    r = crear(api, entorno, peso_kg=1200, volumen_m3=12, es_divisible=True, **extra)
    assert r.status_code == 201, r.text
    return r.json()


def partes_de(db, padre_id):
    return db.query(Envio).filter(Envio.envio_padre_id == uuid.UUID(padre_id)).order_by(Envio.parte_numero).all()


def cambiar(db, envio, estado):
    envio.estado = estado
    db.commit()
    db.expire_all()


# ---------- agregación (función pura) ----------

@pytest.mark.parametrize("hijos,esperado", [
    (["pendiente", "pendiente"], "pendiente"),
    (["programado", "programado"], "programado"),
    (["asignado", "sin_asignacion"], "asignado"),
    (["sin_asignacion", "pendiente"], "sin_asignacion"),
    (["en_transito", "asignado"], "en_transito"),
    (["entregado", "en_transito"], "en_transito"),
    (["entregado", "sin_asignacion"], "en_transito"),          # avance parcial
    (["entregado", "con_incidencia"], "con_incidencia"),
    (["asignado", "retenido_aduana"], "retenido_aduana"),
    (["entregado", "entregado"], "entregado"),
    (["devuelto", "devuelto"], "devuelto"),
    (["entregado", "devuelto"], "con_incidencia"),             # mezcla terminada: requiere atención
    (["cancelado", "cancelado"], "cancelado"),
    (["cancelado", "entregado"], "entregado"),                 # las canceladas no cuentan
    (["cancelado", "pendiente"], "pendiente"),
    ([], "pendiente"),
])
def test_estado_del_pedido_segun_sus_partes(hijos, esperado):
    assert agregar_estado_padre(hijos) == esperado


# ---------- creación ----------

def test_crea_el_pedido_y_una_parte_por_vehiculo_de_la_mas_pesada_a_la_mas_liviana(api, db, entorno, plan):
    p = pedido(api, entorno)
    assert p["partes_total"] == 2 and p["partes_entregadas"] == 0 and p["estado"] == "pendiente"
    assert p["envio_padre_id"] is None and float(p["peso_kg"]) == 1200 and p["es_divisible"] is True
    partes = partes_de(db, p["id"])
    assert [x.codigo_envio for x in partes] == [f"{p['codigo_envio']}-P1", f"{p['codigo_envio']}-P2"]
    assert [float(x.peso_kg) for x in partes] == [1000, 200]
    assert [float(x.volumen_m3) for x in partes] == [10, 2]
    assert all(x.es_divisible is False and x.monto_cop is None and x.cliente_id == entorno["cliente"].id for x in partes)
    assert all(x.origen == p["origen"] and x.destino == p["destino"] and x.ruta_maestra_id == uuid.UUID(p["ruta_maestra_id"]) for x in partes)


def test_eventos_el_pedido_anuncia_el_pago_y_las_partes_inician_la_saga_en_orden(api, db, entorno, plan):
    p = pedido(api, entorno)
    claves = [c for c, _ in entorno["publicados"]]
    assert claves == ["shipment.split", "shipment.created", "shipment.created"]
    split, c1, c2 = (e for _, e in entorno["publicados"])
    assert split["envio_id"] == p["id"] and len(split["partes"]) == 2 and split["monto_cop"] is None   # sin Billing configurado
    assert [c1["peso_kg"], c2["peso_kg"]] == [1000, 200]                 # de la más pesada a la más liviana
    assert [c1["parte_numero"], c2["parte_numero"]] == [1, 2] and c1["envio_padre_id"] == p["id"]
    assert c1["monto_cop"] is None and c2["monto_cop"] is None
    assert c1["pais_origen"] == "Colombia"
    assert p["id"] not in {e["envio_id"] for c, e in entorno["publicados"] if c == "shipment.created"}   # el pedido no viaja


def test_el_precio_y_el_pago_son_del_pedido(api, db, entorno, plan, monkeypatch):
    async def calcular(peso, km, cid=None):
        return {"monto_cop": 103160.0, "moneda": "COP"}
    monkeypatch.setattr(router_envios, "calcular_cotizacion", calcular)
    p = pedido(api, entorno, monto_aceptado_cop=103160)
    assert float(p["monto_cop"]) == 103160
    split = entorno["publicados"][0][1]
    assert split["monto_cop"] == 103160 and all(e["monto_cop"] is None for c, e in entorno["publicados"] if c == "shipment.created")
    assert all(x.monto_cop is None for x in partes_de(db, p["id"]))


def test_historial_del_pedido_y_de_las_partes(api, db, entorno, plan):
    p = pedido(api, entorno)
    ev = {e.tipo_evento: e.notas for e in db.query(EnvioEvento).filter_by(envio_id=uuid.UUID(p["id"])).all()}
    assert "2 partes (kg): 1000 + 200" in ev["dividido"]
    parte1 = partes_de(db, p["id"])[0]
    assert "parte 1 de 2" in db.query(EnvioEvento).filter_by(envio_id=parte1.id, tipo_evento="creado").one().notas


def test_programado_y_dividido_las_partes_esperan_su_hora(api, db, entorno, plan):
    p = pedido(api, entorno, fecha_programada=en(dias=2))
    assert p["estado"] == "programado"
    assert [x.estado for x in partes_de(db, p["id"])] == ["programado", "programado"]
    assert [c for c, _ in entorno["publicados"]] == ["shipment.split"]          # la Saga no arranca todavía


def test_el_vigilante_activa_las_partes_de_la_mas_pesada_a_la_mas_liviana(api, db, entorno, plan):
    p = pedido(api, entorno, fecha_programada=en(dias=1))
    publicados = []

    async def publicar(clave, cuerpo):
        publicados.append(cuerpo["peso_kg"])

    n = asyncio.run(programacion.activar_vencidos(sessionmaker(bind=db.get_bind()), publicar,
                                                  datetime.now(timezone.utc) + timedelta(days=2)))
    db.expire_all()
    assert n == 2 and publicados == [1000, 200]
    assert db.query(Envio).filter_by(id=uuid.UUID(p["id"])).one().estado == "pendiente"


def test_demasiadas_partes_se_rechaza(api, db, entorno, fleet):
    fleet["respuesta"] = {"viable": True, "requiere_division": True,
                          "partes": [{"parte": i, "peso_kg": 100} for i in range(1, 12)]}
    r = crear(api, entorno, peso_kg=1100, es_divisible=True)
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "DEMASIADAS_PARTES"
    assert db.query(Envio).count() == 0 and entorno["publicados"] == []


def test_plan_incoherente_se_rechaza(api, db, entorno, fleet):
    fleet["respuesta"] = {"viable": True, "requiere_division": True,
                          "partes": [{"parte": 1, "peso_kg": 1000}, {"parte": 2, "peso_kg": 100}]}
    r = crear(api, entorno, peso_kg=1200, es_divisible=True)
    assert r.status_code == 502 and r.json()["detail"]["codigo"] == "PLAN_DIVISION_INVALIDO" and db.query(Envio).count() == 0


def test_carga_indivisible_sigue_rechazada_y_divisible_que_cabe_no_se_divide(api, db, entorno, fleet):
    fleet["respuesta"] = {"viable": False, "causa": "CARGA_INDIVISIBLE_EXCEDE_CAPACIDAD", "mensaje": "no cabe"}
    assert crear(api, entorno, peso_kg=1200).status_code == 422
    fleet["respuesta"] = {"viable": True, "requiere_division": False}
    r = crear(api, entorno, peso_kg=500, es_divisible=True)
    assert r.status_code == 201 and r.json()["partes_total"] is None and db.query(Envio).count() == 1


# ---------- el estado del pedido sigue a sus partes ----------

def test_el_pedido_sigue_el_estado_de_sus_partes_hasta_entregarse(api, db, entorno, plan):
    p = pedido(api, entorno)
    p1, p2 = partes_de(db, p["id"])
    estado = lambda: api.get(f"/envios/{p['id']}", headers=GESTOR).json()
    cambiar(db, p1, "asignado");       assert estado()["estado"] == "asignado"
    cambiar(db, p2, "sin_asignacion"); assert estado()["estado"] == "asignado"
    cambiar(db, p1, "en_transito");    assert estado()["estado"] == "en_transito"
    cambiar(db, p1, "entregado");      assert estado()["estado"] == "en_transito" and estado()["partes_entregadas"] == 1
    cambiar(db, p2, "entregado")
    assert estado()["estado"] == "entregado" and estado()["partes_entregadas"] == 2 and estado()["partes_total"] == 2


def test_una_asignacion_real_de_routing_mueve_al_pedido(api, db, entorno, plan, monkeypatch):
    p = pedido(api, entorno)
    p1, _ = partes_de(db, p["id"])
    monkeypatch.setattr(events, "SessionLocal", sessionmaker(bind=db.get_bind()))
    asyncio.run(events._procesar_route_assigned({
        "envio_id": str(p1.id), "ruta_id": str(uuid.uuid4()), "placa": "AAA111", "conductor_nombre": "Ana",
    }))
    db.expire_all()
    assert db.query(Envio).filter_by(id=p1.id).one().estado == "asignado"
    assert db.query(Envio).filter_by(id=uuid.UUID(p["id"])).one().estado == "asignado"


def test_el_pedido_no_se_toca_a_mano(api, db, entorno, plan):
    p = pedido(api, entorno)
    r = api.patch(f"/envios/{p['id']}/estado", json={"estado": "devuelto"}, headers=GESTOR)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "ENVIO_DIVIDIDO"
    r = api.post(f"/envios/{p['id']}/prueba-entrega", json={"nombre_receptor": "Ana"}, headers=GESTOR)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "ENVIO_DIVIDIDO"


def test_una_parte_si_se_gestiona_a_mano_y_el_pedido_la_refleja(api, db, entorno, plan):
    p = pedido(api, entorno)
    p1, _ = partes_de(db, p["id"])
    cambiar(db, p1, "asignado")
    r = api.patch(f"/envios/{p1.id}/estado", json={"estado": "con_incidencia", "notas": "llanta"}, headers=GESTOR)
    assert r.status_code == 200
    assert api.get(f"/envios/{p['id']}", headers=GESTOR).json()["estado"] == "con_incidencia"


def test_reintentar_asignacion_del_pedido_recorre_las_partes_en_espera(api, db, entorno, plan, monkeypatch):
    p = pedido(api, entorno)
    visto = []

    async def reintentar(envio_id):
        visto.append(envio_id)
        return {"estado": "sin_asignacion", "ultimo_error": "SIN_DISPONIBILIDAD"}

    monkeypatch.setattr(router_envios, "reintentar_asignacion", reintentar)
    partes = partes_de(db, p["id"])
    r = api.post(f"/envios/{p['id']}/reintentar-asignacion", headers=GESTOR)
    assert r.status_code == 200 and visto == [partes[0].id, partes[1].id]       # la más pesada primero
    for x in partes:
        cambiar(db, x, "asignado")
    assert api.post(f"/envios/{p['id']}/reintentar-asignacion", headers=GESTOR).status_code == 409


# ---------- consulta ----------

def test_partes_del_pedido_y_filtros_del_listado(api, db, entorno, plan):
    p = pedido(api, entorno)
    partes = api.get(f"/envios/{p['id']}/partes", headers=GESTOR).json()
    assert [x["parte_numero"] for x in partes] == [1, 2] and all(x["envio_padre_id"] == p["id"] for x in partes)
    assert api.get(f"/envios/{partes[0]['id']}/partes", headers=GESTOR).json() == []
    todos = api.get("/envios/", headers=GESTOR).json()
    assert len(todos) == 3
    assert [e["id"] for e in api.get("/envios/?solo_pedidos=true", headers=GESTOR).json()] == [p["id"]]
    assert len(api.get(f"/envios/?envio_padre_id={p['id']}", headers=GESTOR).json()) == 2


def test_un_cliente_solo_ve_las_partes_de_sus_pedidos(api, db, entorno, plan):
    p = pedido(api, entorno)
    ajeno = Cliente(id=uuid.uuid4(), codigo_cliente=7099, nombre="Otro Cliente"); db.add(ajeno); db.commit()
    propio = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "cliente", "x-cliente-id": str(entorno["cliente"].id)}
    otro = {"x-user-id": str(uuid.uuid4()), "x-user-rol": "cliente", "x-cliente-id": str(ajeno.id)}
    assert len(api.get(f"/envios/{p['id']}/partes", headers=propio).json()) == 2
    assert api.get(f"/envios/{p['id']}/partes", headers=otro).status_code == 404
    assert api.get("/envios/", headers=otro).json() == []


# ---------- cancelar ----------

@pytest.fixture()
def avisos(monkeypatch):
    publicados = []

    async def publicar(clave, cuerpo):
        publicados.append((clave, cuerpo))

    monkeypatch.setattr(router_envios, "_publicar_con_reintentos", publicar)
    return publicados


def test_cancelar_el_pedido_cancela_todas_las_partes_y_avisa_por_cada_una(api, db, entorno, plan, avisos):
    p = pedido(api, entorno, fecha_programada=en(dias=2))
    r = api.post(f"/envios/{p['id']}/cancelar", json={"motivo": "ya no lo necesita"}, headers=GESTOR)
    assert r.status_code == 200 and r.json()["estado"] == "cancelado"
    db.expire_all()
    assert [x.estado for x in partes_de(db, p["id"])] == ["cancelado", "cancelado"]
    ids = [e["envio_id"] for c, e in avisos if c == "shipment.cancelled"]
    assert len(ids) == 3 and p["id"] in ids
    assert [e["es_pedido_dividido"] for c, e in avisos if e["envio_id"] == p["id"]] == [True]


def test_no_se_cancela_un_pedido_con_una_parte_en_curso(api, db, entorno, plan, avisos):
    p = pedido(api, entorno)
    p1, p2 = partes_de(db, p["id"])
    cambiar(db, p1, "asignado")
    r = api.post(f"/envios/{p['id']}/cancelar", headers=GESTOR)
    assert r.status_code == 409 and r.json()["detail"]["partes_en_curso"] == [p1.codigo_envio]
    db.expire_all()
    assert db.query(Envio).filter_by(id=p2.id).one().estado == "pendiente" and avisos == []


def test_cancelar_dos_veces_y_cancelar_una_parte(api, db, entorno, plan, avisos):
    p = pedido(api, entorno)
    parte = partes_de(db, p["id"])[0]
    r = api.post(f"/envios/{parte.id}/cancelar", headers=GESTOR)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "PARTE_DE_PEDIDO"
    assert api.post(f"/envios/{p['id']}/cancelar", headers=GESTOR).status_code == 200
    assert api.post(f"/envios/{p['id']}/cancelar", headers=GESTOR).status_code == 409


# ---------- reprogramar ----------

def test_reprogramar_el_pedido_mueve_todas_las_partes(api, db, entorno, plan):
    p = pedido(api, entorno, fecha_programada=en(dias=1))
    nueva = en(dias=5)
    r = api.patch(f"/envios/{p['id']}/reprogramar", json={"fecha_programada": nueva}, headers=GESTOR)
    assert r.status_code == 200
    db.expire_all()
    fechas = {x.fecha_programada.date() for x in partes_de(db, p["id"])}
    assert fechas == {datetime.fromisoformat(nueva).date()}


def test_reprogramar_una_parte_o_un_pedido_ya_iniciado_se_rechaza(api, db, entorno, plan):
    p = pedido(api, entorno, fecha_programada=en(dias=1))
    parte = partes_de(db, p["id"])[0]
    r = api.patch(f"/envios/{parte.id}/reprogramar", json={"fecha_programada": en(dias=3)}, headers=GESTOR)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "PARTE_DE_PEDIDO"
    cambiar(db, parte, "pendiente")
    r = api.patch(f"/envios/{p['id']}/reprogramar", json={"fecha_programada": en(dias=3)}, headers=GESTOR)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "NO_ESTA_PROGRAMADO"


def test_el_calendario_muestra_el_pedido_una_sola_vez(api, db, entorno, plan):
    p = pedido(api, entorno, fecha_programada=en(dias=2))
    r = api.get("/envios/programados", headers=GESTOR).json()
    assert [e["id"] for e in r] == [p["id"]] and r[0]["partes_total"] == 2


# ---------- devolución: el evento dice si el pedido completo se devolvió (Billing prepara el reembolso) ----------

def _devolver(api, envio_id):
    return api.patch(f"/envios/{envio_id}/estado", json={"estado": "devuelto", "notas": "dirección cerrada"}, headers=GESTOR)


def test_devolver_un_envio_normal_avisa_que_el_pedido_se_devolvio(api, db, entorno, fleet):
    fleet["respuesta"] = {"viable": True, "requiere_division": False}
    e = crear(api, entorno, peso_kg=500)
    assert e.status_code == 201, e.text
    eid = e.json()["id"]
    cambiar(db, db.query(Envio).one(), "en_transito")
    entorno["publicados"].clear()
    assert _devolver(api, eid).status_code == 200
    clave, cuerpo = entorno["publicados"][-1]
    assert clave == "shipment.returned"
    assert cuerpo["envio_id"] == eid and cuerpo["pedido_id"] == eid and cuerpo["pedido_devuelto"] is True
    assert cuerpo["envio_padre_id"] is None and cuerpo["cliente_id"] == str(entorno["cliente"].id)


def test_devolver_una_parte_solo_marca_el_pedido_devuelto_cuando_todas_lo_estan(api, db, entorno, plan):
    p = pedido(api, entorno)
    p1, p2 = partes_de(db, p["id"])
    cambiar(db, p1, "en_transito"); cambiar(db, p2, "en_transito")
    entorno["publicados"].clear()

    assert _devolver(api, p1.id).status_code == 200
    clave, primero = entorno["publicados"][-1]
    assert clave == "shipment.returned" and primero["envio_id"] == str(p1.id)
    assert primero["pedido_id"] == p["id"] and primero["envio_padre_id"] == p["id"]
    assert primero["pedido_devuelto"] is False          # la otra parte sigue en camino

    assert _devolver(api, p2.id).status_code == 200
    _, segundo = entorno["publicados"][-1]
    assert segundo["envio_id"] == str(p2.id) and segundo["pedido_id"] == p["id"] and segundo["pedido_devuelto"] is True
    assert api.get(f"/envios/{p['id']}", headers=GESTOR).json()["estado"] == "devuelto"


def test_una_parte_devuelta_y_otra_entregada_no_marca_el_pedido_devuelto(api, db, entorno, plan):
    p = pedido(api, entorno)
    p1, p2 = partes_de(db, p["id"])
    cambiar(db, p1, "en_transito"); cambiar(db, p2, "en_transito")
    cambiar(db, p1, "entregado")
    assert _devolver(api, p2.id).status_code == 200
    assert entorno["publicados"][-1][1]["pedido_devuelto"] is False
    assert api.get(f"/envios/{p['id']}", headers=GESTOR).json()["estado"] == "con_incidencia"
