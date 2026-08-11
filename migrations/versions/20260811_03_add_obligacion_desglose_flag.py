"""add obligacion desglose flag

Revision ID: 20260811_03
Revises: 20260811_02
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260811_03'
down_revision = '20260811_02'
branch_labels = None
depends_on = None


def _has_table(table_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return inspector.has_table(table_name)


def _has_column(table_name, column_name):
    bind = op.get_bind()
    inspector = inspect(bind)
    return column_name in {col['name'] for col in inspector.get_columns(table_name)}


def upgrade():
    if _has_table('obligaciones') and not _has_column('obligaciones', 'requiere_desglose_pago'):
        op.add_column('obligaciones', sa.Column('requiere_desglose_pago', sa.Boolean(), nullable=True))
        op.execute('UPDATE obligaciones SET requiere_desglose_pago = FALSE WHERE requiere_desglose_pago IS NULL')


def downgrade():
    if _has_table('obligaciones') and _has_column('obligaciones', 'requiere_desglose_pago'):
        op.drop_column('obligaciones', 'requiere_desglose_pago')
