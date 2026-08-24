"""add abonos compras y gastos

Revision ID: 20260824_02
Revises: 20260824_01
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260824_02'
down_revision = '20260824_01'
branch_labels = None
depends_on = None


def _has_table(table_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return inspector.has_table(table_name)


def upgrade():
    if not _has_table('abonos_compras'):
        op.create_table(
            'abonos_compras',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('compra_id', sa.Integer(), nullable=False),
            sa.Column('valor_abono', sa.Numeric(14, 2), nullable=False),
            sa.Column('fecha_pago', sa.Date(), nullable=False),
            sa.Column('medio_pago_id', sa.Integer(), nullable=True),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.Column('registrado_por', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['compra_id'], ['compras.id']),
            sa.ForeignKeyConstraint(['medio_pago_id'], ['medios_pago.id']),
            sa.PrimaryKeyConstraint('id')
        )

    if not _has_table('abonos_gastos'):
        op.create_table(
            'abonos_gastos',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('gasto_id', sa.Integer(), nullable=False),
            sa.Column('valor_abono', sa.Numeric(14, 2), nullable=False),
            sa.Column('fecha_pago', sa.Date(), nullable=False),
            sa.Column('medio_pago_id', sa.Integer(), nullable=True),
            sa.Column('descripcion', sa.Text(), nullable=True),
            sa.Column('registrado_por', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['gasto_id'], ['gastos.id']),
            sa.ForeignKeyConstraint(['medio_pago_id'], ['medios_pago.id']),
            sa.PrimaryKeyConstraint('id')
        )


def downgrade():
    if _has_table('abonos_gastos'):
        op.drop_table('abonos_gastos')

    if _has_table('abonos_compras'):
        op.drop_table('abonos_compras')
