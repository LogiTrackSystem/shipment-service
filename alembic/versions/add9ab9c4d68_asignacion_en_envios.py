"""asignacion en envios

Revision ID: add9ab9c4d68
Revises: d5292dbc925e
Create Date: 2026-10-08 18:08:28.087015

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'add9ab9c4d68'
down_revision: Union[str, Sequence[str], None] = 'd5292dbc925e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("envios", sa.Column("conductor_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("envios", sa.Column("placa_vehiculo", sa.String(length=20), nullable=True))
    op.add_column("envios", sa.Column("tipo_vehiculo", sa.String(length=20), nullable=True))
    op.add_column("envios", sa.Column("conductor_nombre", sa.String(length=150), nullable=True))
    op.add_column("envios", sa.Column("codigo_conductor", sa.BigInteger(), nullable=True))
    op.add_column("envios", sa.Column("hora_estimada_llegada", sa.DateTime(timezone=True), nullable=True))
    op.add_column("envios", sa.Column("motivo_sin_asignacion", sa.Text(), nullable=True))
    op.add_column("envios", sa.Column("estado_previo", sa.String(length=20), nullable=True))


def downgrade() -> None:
    for columna in ("estado_previo", "motivo_sin_asignacion", "hora_estimada_llegada",
                    "codigo_conductor", "conductor_nombre", "tipo_vehiculo",
                    "placa_vehiculo", "conductor_id"):
        op.drop_column("envios", columna)