"""envios.monto_cop

Revision ID: d1f7a3b9e5c2
Revises: b2e5f1a8c3d7
Create Date: 2026-10-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f7a3b9e5c2'
down_revision: Union[str, Sequence[str], None] = 'b2e5f1a8c3d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Aditiva: los envíos existentes quedan sin precio (NULL)
    op.add_column('envios', sa.Column('monto_cop', sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('envios', 'monto_cop')
