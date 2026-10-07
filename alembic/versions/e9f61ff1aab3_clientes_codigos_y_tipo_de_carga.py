"""clientes codigos y tipo de carga

Revision ID: e9f61ff1aab3
Revises: 54382e256ab0
Create Date: 2026-10-06 23:39:08.398677

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e9f61ff1aab3'
down_revision: Union[str, Sequence[str], None] = '54382e256ab0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS seq_codigo_cliente START WITH 1000000001 MINVALUE 1000000001 MAXVALUE 9999999999")
    op.execute("CREATE SEQUENCE IF NOT EXISTS seq_codigo_envio START WITH 1 MINVALUE 1 MAXVALUE 99999999")

    op.create_table(
        "clientes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("codigo_cliente", sa.BigInteger(), server_default=sa.text("nextval('seq_codigo_cliente')"), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("tipo_documento", sa.String(length=10), nullable=True),
        sa.Column("numero_documento", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=150), nullable=True),
        sa.Column("telefono", sa.String(length=30), nullable=True),
        sa.Column("direccion", sa.String(length=255), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("es_historico", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("codigo_cliente", name="uq_clientes_codigo_cliente"),
        sa.UniqueConstraint("tipo_documento", "numero_documento", name="uq_clientes_documento"),
    )
    op.execute("ALTER SEQUENCE seq_codigo_cliente OWNED BY clientes.codigo_cliente")

    # Un cliente historico por cada cliente_id que ya existe en envios (no se borra ni invalida nada)
    op.execute("""
        INSERT INTO clientes (id, nombre, es_historico)
        SELECT c.cliente_id, 'Cliente historico ' || left(c.cliente_id::text, 8), true
        FROM (SELECT cliente_id, min(creado_en) AS primero FROM envios GROUP BY cliente_id) c
        ORDER BY c.primero
    """)

    op.add_column("envios", sa.Column(
        "codigo_envio", sa.String(length=12),
        server_default=sa.text("'ENV-' || lpad(nextval('seq_codigo_envio')::text, 8, '0')"),
        nullable=False,
    ))
    op.create_unique_constraint("uq_envios_codigo_envio", "envios", ["codigo_envio"])
    op.execute("ALTER SEQUENCE seq_codigo_envio OWNED BY envios.codigo_envio")
    op.add_column("envios", sa.Column("tipo_carga", sa.String(length=20), server_default="general", nullable=False))
    op.add_column("envios", sa.Column("es_hazmat", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_foreign_key("fk_envios_cliente_id", "envios", "clientes", ["cliente_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_envios_cliente_id", "envios", type_="foreignkey")
    op.drop_column("envios", "es_hazmat")
    op.drop_column("envios", "tipo_carga")
    op.drop_constraint("uq_envios_codigo_envio", "envios", type_="unique")
    op.drop_column("envios", "codigo_envio")
    op.drop_table("clientes")
    op.execute("DROP SEQUENCE IF EXISTS seq_codigo_envio")
    op.execute("DROP SEQUENCE IF EXISTS seq_codigo_cliente")