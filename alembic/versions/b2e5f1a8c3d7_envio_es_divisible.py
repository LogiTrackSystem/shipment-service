"""envios.es_divisible

Revision ID: b2e5f1a8c3d7
Revises: a7c3e91d2b40
Create Date: 2026-10-18 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2e5f1a8c3d7'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91d2b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Aditiva: los envíos existentes quedan como indivisibles (false)
    op.add_column('envios', sa.Column('es_divisible', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('envios', 'es_divisible')
