"""add fecha_finalizacion to obligaciones

Revision ID: 20260811_07
Revises: 20260811_06
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260811_07'
down_revision = '20260811_06'
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
    if _has_table('obligaciones') and not _has_column('obligaciones', 'fecha_finalizacion'):
        op.add_column('obligaciones', sa.Column('fecha_finalizacion', sa.Date(), nullable=True))


def downgrade():
    if _has_table('obligaciones') and _has_column('obligaciones', 'fecha_finalizacion'):
        op.drop_column('obligaciones', 'fecha_finalizacion')
