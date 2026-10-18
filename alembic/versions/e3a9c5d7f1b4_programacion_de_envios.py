"""programación de envíos: fecha_programada y países en texto

Revision ID: e3a9c5d7f1b4
Revises: d1f7a3b9e5c2
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3a9c5d7f1b4'
down_revision: Union[str, Sequence[str], None] = 'd1f7a3b9e5c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Aditiva: los envíos existentes quedan con NULL (sin programación)
    op.add_column('envios', sa.Column('fecha_programada', sa.DateTime(timezone=True), nullable=True))
    op.add_column('envios', sa.Column('pais_origen', sa.String(length=100), nullable=True))
    op.add_column('envios', sa.Column('pais_destino', sa.String(length=100), nullable=True))
    op.create_index('ix_envios_fecha_programada', 'envios', ['fecha_programada'])


def downgrade() -> None:
    op.drop_index('ix_envios_fecha_programada', table_name='envios')
    op.drop_column('envios', 'pais_destino')
    op.drop_column('envios', 'pais_origen')
    op.drop_column('envios', 'fecha_programada')
