"""ubicaciones y ruta en envios

Revision ID: d5292dbc925e
Revises: e9f61ff1aab3
Create Date: 2026-10-07 21:09:29.891724

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd5292dbc925e'
down_revision: Union[str, Sequence[str], None] = 'e9f61ff1aab3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("envios", sa.Column("origen_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("envios", sa.Column("destino_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("envios", sa.Column("codigo_pais_origen", sa.String(length=2), nullable=True))
    op.add_column("envios", sa.Column("codigo_pais_destino", sa.String(length=2), nullable=True))
    op.add_column("envios", sa.Column("ruta_maestra_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("envios", sa.Column("codigo_ruta", sa.String(length=12), nullable=True))
    op.add_column("envios", sa.Column("distancia_km", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("envios", sa.Column("duracion_horas", sa.Numeric(precision=8, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column("envios", "duracion_horas")
    op.drop_column("envios", "distancia_km")
    op.drop_column("envios", "codigo_ruta")
    op.drop_column("envios", "ruta_maestra_id")
    op.drop_column("envios", "codigo_pais_destino")
    op.drop_column("envios", "codigo_pais_origen")
    op.drop_column("envios", "destino_id")
    op.drop_column("envios", "origen_id")