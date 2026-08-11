"""add obligacion fields for cadena and references

Revision ID: 20260811_02
Revises: 20260811_01
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260811_02'
down_revision = '20260811_01'
branch_labels = None
depends_on = None


def _has_table(table_name):
    bind = op.get_bind()
    return inspect(bind).has_table(table_name)


def _has_column(table_name, column_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(col['name'] == column_name for col in inspector.get_columns(table_name))


def upgrade():
    if not _has_table('obligaciones'):
        return

    if not _has_column('obligaciones', 'fecha_recibe'):
        op.add_column('obligaciones', sa.Column('fecha_recibe', sa.Date(), nullable=True))
    if not _has_column('obligaciones', 'referencia'):
        op.add_column('obligaciones', sa.Column('referencia', sa.String(length=50), nullable=True))
    if not _has_column('obligaciones', 'frecuencia_pago'):
        op.add_column('obligaciones', sa.Column('frecuencia_pago', sa.String(length=20), nullable=True))
        op.execute("UPDATE obligaciones SET frecuencia_pago = 'mensual' WHERE frecuencia_pago IS NULL")


def downgrade():
    if _has_table('obligaciones') and _has_column('obligaciones', 'frecuencia_pago'):
        op.drop_column('obligaciones', 'frecuencia_pago')
    if _has_table('obligaciones') and _has_column('obligaciones', 'referencia'):
        op.drop_column('obligaciones', 'referencia')
    if _has_table('obligaciones') and _has_column('obligaciones', 'fecha_recibe'):
        op.drop_column('obligaciones', 'fecha_recibe')
