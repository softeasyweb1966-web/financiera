"""add anticipo component to pagos obligaciones

Revision ID: 20260818_01
Revises: 20260814_01
Create Date: 2026-08-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260818_01'
down_revision = '20260814_01'
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
    if _has_table('pagos_obligaciones') and not _has_column('pagos_obligaciones', 'componente_anticipo'):
        op.add_column('pagos_obligaciones', sa.Column('componente_anticipo', sa.Numeric(14, 2), nullable=True))

    if _has_table('historial_pagos_obligaciones') and not _has_column('historial_pagos_obligaciones', 'componente_anticipo'):
        op.add_column('historial_pagos_obligaciones', sa.Column('componente_anticipo', sa.Numeric(14, 2), nullable=True))


def downgrade():
    if _has_table('historial_pagos_obligaciones') and _has_column('historial_pagos_obligaciones', 'componente_anticipo'):
        op.drop_column('historial_pagos_obligaciones', 'componente_anticipo')

    if _has_table('pagos_obligaciones') and _has_column('pagos_obligaciones', 'componente_anticipo'):
        op.drop_column('pagos_obligaciones', 'componente_anticipo')
