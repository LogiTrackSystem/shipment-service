"""Unitaria 1: registro.validar_codigo_personal acepta solo el código del administrador."""
import pytest
from fastapi import HTTPException

from app import registro


def test_validar_codigo_personal_acepta_el_correcto_y_rechaza_el_incorrecto(monkeypatch):
    monkeypatch.setenv("CODIGO_REGISTRO_PERSONAL", "codigo-secreto-del-admin")
    registro.reiniciar_limite()
    registro.validar_codigo_personal("codigo-secreto-del-admin")  # no lanza nada
    with pytest.raises(HTTPException) as error:
        registro.validar_codigo_personal("otro-codigo")
    assert error.value.status_code == 403
    registro.reiniciar_limite()
