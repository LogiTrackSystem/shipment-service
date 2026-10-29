"""prueba de entrega simulada

Revision ID: 280229b635b4
Revises: add9ab9c4d68
Create Date: 2026-10-11 19:40:17.794618

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '280229b635b4'
down_revision: Union[str, Sequence[str], None] = 'add9ab9c4d68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prueba_entrega",
        sa.Column("simulada", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("prueba_entrega", "simulada")