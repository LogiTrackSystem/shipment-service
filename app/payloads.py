"""Contenido del evento que anuncia un pedido (shipment.created / shipment.scheduled)."""


def construir_payload_creado(envio) -> dict:
    return {
        "envio_id": str(envio.id),
        "codigo_envio": envio.codigo_envio,
        "envio_padre_id": str(envio.envio_padre_id) if envio.envio_padre_id else None,
        "parte_numero": envio.parte_numero,
        "cliente_id": str(envio.cliente_id),
        "codigo_cliente": envio.codigo_cliente,
        "origen": envio.origen,
        "destino": envio.destino,
        "origen_id": str(envio.origen_id),
        "destino_id": str(envio.destino_id),
        "pais_origen": envio.pais_origen or envio.codigo_pais_origen,
        "pais_destino": envio.pais_destino or envio.codigo_pais_destino,
        "codigo_pais_origen": envio.codigo_pais_origen,
        "codigo_pais_destino": envio.codigo_pais_destino,
        "ruta_maestra_id": str(envio.ruta_maestra_id),
        "codigo_ruta": envio.codigo_ruta,
        "distancia_km": float(envio.distancia_km),
        "duracion_horas": float(envio.duracion_horas),
        "es_internacional": envio.es_internacional,
        "tipo_carga": envio.tipo_carga,
        "es_hazmat": envio.es_hazmat,
        "peso_kg": float(envio.peso_kg),
        "volumen_m3": float(envio.volumen_m3) if envio.volumen_m3 is not None else None,
        "fecha_limite_sla": envio.fecha_limite_sla,
        "fecha_programada": envio.fecha_programada,
        "monto_cop": float(envio.monto_cop) if envio.monto_cop is not None else None,
        "moneda": "COP",
    }
