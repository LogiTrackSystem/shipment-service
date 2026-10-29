"""Pruebas del Shipment Service con SQLite en memoria (no tocan PostgreSQL ni RabbitMQ).

Las columnas con valores por defecto de PostgreSQL (secuencias) se rellenan a mano en las pruebas.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "secreto-de-pruebas-0123456789"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database
from app.database import Base, get_db
from app.main import app
from app import models  # noqa: F401


# SQLite no tiene secuencias: se quitan solo en las pruebas los defaults 'nextval' (los códigos se asignan a mano)
import itertools
from sqlalchemy.schema import ColumnDefault

_contador = itertools.count(5000)
for _tabla in Base.metadata.tables.values():
    for _col in _tabla.columns:
        if _col.server_default is not None and "nextval" in str(getattr(_col.server_default, "arg", "")):
            _col.server_default = None
            if _col.name == "codigo_envio":
                ColumnDefault(lambda: f"ENV-{next(_contador):08d}")._set_parent_with_dispatch(_col)
            else:
                ColumnDefault(lambda: next(_contador))._set_parent_with_dispatch(_col)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Sesion = sessionmaker(bind=engine, autoflush=False)
    sesion = Sesion()
    yield sesion
    sesion.close()
    engine.dispose()


@pytest.fixture()
def api(db):
    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
