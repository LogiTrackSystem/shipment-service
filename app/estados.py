ESTADOS_FINALES = ("entregado", "devuelto")

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