"""add abonos nomina table

Revision ID: 20260824_01
Revises: 20260818_01
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260824_01'
down_revision = '20260818_01'
branch_labels = None
depends_on = None


def _has_table(table_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return inspector.has_table(table_name)


def upgrade():
    if _has_table('abonos_nomina'):
        return

    op.create_table(
        'abonos_nomina',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('empleado_id', sa.Integer(), nullable=False),
        sa.Column('saldo_anterior_nomina_id', sa.Integer(), nullable=True),
        sa.Column('anio', sa.Integer(), nullable=False),
        sa.Column('mes', sa.Integer(), nullable=False),
        sa.Column('quincena', sa.Integer(), nullable=False),
        sa.Column('valor_abono', sa.Numeric(14, 2), nullable=False),
        sa.Column('fecha_pago', sa.Date(), nullable=False),
        sa.Column('medio_pago_id', sa.Integer(), nullable=True),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('registrado_por', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['empleado_id'], ['empleados.id']),
        sa.ForeignKeyConstraint(['medio_pago_id'], ['medios_pago.id']),
        sa.ForeignKeyConstraint(['saldo_anterior_nomina_id'], ['saldos_anteriores_nomina.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    if _has_table('abonos_nomina'):
        op.drop_table('abonos_nomina')
