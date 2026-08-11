"""add payment day and receipt fields

Revision ID: 20260811_06
Revises: 20260811_05
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260811_06'
down_revision = '20260811_05'
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


def _add_pago_columns(table_name):
    if _has_table(table_name) and not _has_column(table_name, 'dia_pago_reportado'):
        op.add_column(table_name, sa.Column('dia_pago_reportado', sa.Integer(), nullable=True))
    if _has_table(table_name) and not _has_column(table_name, 'comprobante_nombre'):
        op.add_column(table_name, sa.Column('comprobante_nombre', sa.String(length=255), nullable=True))
    if _has_table(table_name) and not _has_column(table_name, 'comprobante_mime'):
        op.add_column(table_name, sa.Column('comprobante_mime', sa.String(length=120), nullable=True))
    if _has_table(table_name) and not _has_column(table_name, 'comprobante_archivo'):
        op.add_column(table_name, sa.Column('comprobante_archivo', sa.LargeBinary(), nullable=True))


def _drop_pago_columns(table_name):
    if _has_table(table_name) and _has_column(table_name, 'comprobante_archivo'):
        op.drop_column(table_name, 'comprobante_archivo')
    if _has_table(table_name) and _has_column(table_name, 'comprobante_mime'):
        op.drop_column(table_name, 'comprobante_mime')
    if _has_table(table_name) and _has_column(table_name, 'comprobante_nombre'):
        op.drop_column(table_name, 'comprobante_nombre')
    if _has_table(table_name) and _has_column(table_name, 'dia_pago_reportado'):
        op.drop_column(table_name, 'dia_pago_reportado')


def upgrade():
    _add_pago_columns('pagos_servicios')
    _add_pago_columns('pagos_obligaciones')


def downgrade():
    _drop_pago_columns('pagos_obligaciones')
    _drop_pago_columns('pagos_servicios')
