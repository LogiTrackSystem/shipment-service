"""usuarios y roles

Revision ID: a7c3e91d2b40
Revises: 280229b635b4
Create Date: 2026-10-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91d2b40'
down_revision: Union[str, Sequence[str], None] = '280229b635b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=150), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("ultimo_acceso", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.CheckConstraint("rol IN ('cliente','operador','gestor_flota','administrador')", name="ck_usuarios_rol"),
        sa.CheckConstraint("rol <> 'cliente' OR cliente_id IS NOT NULL", name="ck_usuarios_cliente_requerido"),
    )


def downgrade() -> None:
    op.drop_table("usuarios")
