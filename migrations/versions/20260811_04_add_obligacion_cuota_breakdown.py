"""add obligacion cuota breakdown

Revision ID: 20260811_04
Revises: 20260811_03
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260811_04'
down_revision = '20260811_03'
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
    if _has_table('obligaciones') and not _has_column('obligaciones', 'valor_cuota_capital'):
        op.add_column('obligaciones', sa.Column('valor_cuota_capital', sa.Numeric(precision=14, scale=2), nullable=True))
    if _has_table('obligaciones') and not _has_column('obligaciones', 'valor_cuota_interes'):
        op.add_column('obligaciones', sa.Column('valor_cuota_interes', sa.Numeric(precision=14, scale=2), nullable=True))


def downgrade():
    if _has_table('obligaciones') and _has_column('obligaciones', 'valor_cuota_interes'):
        op.drop_column('obligaciones', 'valor_cuota_interes')
    if _has_table('obligaciones') and _has_column('obligaciones', 'valor_cuota_capital'):
        op.drop_column('obligaciones', 'valor_cuota_capital')
