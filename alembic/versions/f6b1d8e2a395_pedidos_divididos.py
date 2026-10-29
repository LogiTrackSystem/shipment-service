"""pedidos divididos: envio_padre_id, parte_numero, partes_total, partes_entregadas; codigo_envio a 20

Revision ID: f6b1d8e2a395
Revises: e3a9c5d7f1b4
Create Date: 2026-10-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6b1d8e2a395'
down_revision: Union[str, Sequence[str], None] = 'e3a9c5d7f1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Aditiva: los envíos existentes quedan sin padre ni partes (NULL)
    op.add_column('envios', sa.Column('envio_padre_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('envios', sa.Column('parte_numero', sa.Integer(), nullable=True))
    op.add_column('envios', sa.Column('partes_total', sa.Integer(), nullable=True))
    op.add_column('envios', sa.Column('partes_entregadas', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_envios_envio_padre', 'envios', 'envios', ['envio_padre_id'], ['id'])
    op.create_index('ix_envios_envio_padre_id', 'envios', ['envio_padre_id'])
    # 'ENV-00000032-P1' tiene 15 caracteres; ensanchar la columna no altera los códigos existentes
    op.alter_column('envios', 'codigo_envio', existing_type=sa.String(length=12), type_=sa.String(length=20),
                    existing_nullable=False)


def downgrade() -> None:
    # Solo es posible si no existen códigos de más de 12 caracteres (es decir, si no hay pedidos divididos)
    op.alter_column('envios', 'codigo_envio', existing_type=sa.String(length=20), type_=sa.String(length=12),
                    existing_nullable=False)
    op.drop_index('ix_envios_envio_padre_id', table_name='envios')
    op.drop_constraint('fk_envios_envio_padre', 'envios', type_='foreignkey')
    op.drop_column('envios', 'partes_entregadas')
    op.drop_column('envios', 'partes_total')
    op.drop_column('envios', 'parte_numero')
    op.drop_column('envios', 'envio_padre_id')
