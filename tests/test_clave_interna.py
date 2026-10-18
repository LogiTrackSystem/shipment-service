"""Clave interna (INTERNAL_API_KEY): el servicio solo atiende peticiones que traen la clave."""
from fastapi.testclient import TestClient

from app.main import app

CLIENTE = TestClient(app)  # sin 'with': no se ejecuta el arranque (conexiones a RabbitMQ)
RUTA = "/ruta-que-no-existe"


def test_sin_clave_configurada_no_se_exige_nada(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    assert CLIENTE.get(RUTA).status_code == 404


def test_con_clave_configurada_se_rechaza_si_falta_o_es_incorrecta(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "clave-de-prueba-123")
    sin = CLIENTE.get(RUTA)
    assert sin.status_code == 403
    assert sin.json()["detail"]["codigo"] == "ACCESO_DIRECTO_NO_PERMITIDO"
    mala = CLIENTE.get(RUTA, headers={"X-Internal-Key": "otra"})
    assert mala.status_code == 403


def test_con_la_clave_correcta_pasa(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "clave-de-prueba-123")
    assert CLIENTE.get(RUTA, headers={"X-Internal-Key": "clave-de-prueba-123"}).status_code == 404


def test_health_queda_abierto(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "clave-de-prueba-123")
    assert CLIENTE.get("/health").status_code != 403


def test_las_llamadas_salientes_llevan_la_clave(monkeypatch):
    from app.interno import cabeceras_internas
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    assert cabeceras_internas() == {}
    monkeypatch.setenv("INTERNAL_API_KEY", "abc")
    assert cabeceras_internas() == {"X-Internal-Key": "abc"}
