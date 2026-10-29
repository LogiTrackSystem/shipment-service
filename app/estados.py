ESTADOS_FINALES = ("entregado", "devuelto", "cancelado")

# Estados desde los que se puede cancelar un envío (todavía no tiene vehículo en camino)
ESTADOS_CANCELABLES = ("programado", "pendiente", "sin_asignacion")

# Cambios que un operador puede pedir a mano con PATCH /envios/{id}/estado:
# estado destino -> estados desde los que se permite.
TRANSICIONES_MANUALES = {
    "en_transito": ("asignado", "con_incidencia"),
    "con_incidencia": ("asignado", "en_transito"),
    "devuelto": (
        "pendiente", "sin_asignacion", "asignado",
        "en_transito", "con_incidencia", "retenido_aduana",
    ),
}

# Estados desde los que se puede registrar la prueba de entrega.
ESTADOS_ENTREGABLES = ("asignado", "en_transito", "con_incidencia")


# ---------- Pedidos divididos: el estado del pedido (padre) resume el de sus partes (hijos) ----------
_FINALES = ("entregado", "devuelto", "cancelado")
_PRIORIDAD = ("en_transito", "con_incidencia", "retenido_aduana", "asignado", "sin_asignacion", "pendiente", "programado")


def agregar_estado_padre(estados_hijos) -> str:
    """Estado del pedido a partir del de sus partes. Las partes canceladas no cuentan.
    - todas canceladas -> cancelado; todas entregadas -> entregado; todas devueltas -> devuelto.
    - todas terminadas pero mezcla de entregadas y devueltas -> con_incidencia (requiere atención).
    - avance parcial (alguna terminada y otra no) -> en_transito, o con_incidencia si alguna lo está.
    - en otro caso, el estado más avanzado entre las partes."""
    estados = list(estados_hijos)
    if not estados:
        return "pendiente"
    activos = [e for e in estados if e != "cancelado"]
    if not activos:
        return "cancelado"
    if all(e in _FINALES for e in activos):
        if all(e == "entregado" for e in activos):
            return "entregado"
        if all(e == "devuelto" for e in activos):
            return "devuelto"
        return "con_incidencia"
    if any(e in ("entregado", "devuelto") for e in activos):
        return "con_incidencia" if "con_incidencia" in activos else "en_transito"
    for e in _PRIORIDAD:
        if e in activos:
            return e
    return "pendiente"
