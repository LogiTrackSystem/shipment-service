"""Unitaria 2: payloads.construir_payload_creado arma el evento shipment.created."""
import uuid
from types import SimpleNamespace

from app.payloads import construir_payload_creado


def test_construir_payload_creado_convierte_ids_y_numeros():
    envio = SimpleNamespace(
        id=uuid.uuid4(), codigo_envio="ENV-00000001", envio_padre_id=None, parte_numero=None, cliente_id=uuid.uuid4(),
        codigo_cliente="CLI-1", origen="Bogotá", destino="Cali", origen_id=uuid.uuid4(), destino_id=uuid.uuid4(),
        pais_origen="Colombia", pais_destino="Colombia", codigo_pais_origen="CO", codigo_pais_destino="CO",
        ruta_maestra_id=uuid.uuid4(), codigo_ruta="RUT-1", distancia_km="300.5", duracion_horas="6", es_internacional=False,
        tipo_carga="general", es_hazmat=False, peso_kg="800", volumen_m3=None, fecha_limite_sla=None,
        fecha_programada=None, monto_cop="86528.00",
    )
    payload = construir_payload_creado(envio)
    assert payload["envio_id"] == str(envio.id) and payload["envio_padre_id"] is None
    assert payload["distancia_km"] == 300.5 and payload["peso_kg"] == 800.0
    assert payload["monto_cop"] == 86528.0 and payload["moneda"] == "COP"
