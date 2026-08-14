"""add amortizacion support for obligaciones

Revision ID: 20260814_01
Revises: 20260811_07
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '20260814_01'
down_revision = '20260811_07'
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
    if _has_table('obligaciones'):
        if not _has_column('obligaciones', 'fecha_inicio_amortizacion'):
            op.add_column('obligaciones', sa.Column('fecha_inicio_amortizacion', sa.Date(), nullable=True))
        if not _has_column('obligaciones', 'soporte_amortizacion_nombre'):
            op.add_column('obligaciones', sa.Column('soporte_amortizacion_nombre', sa.String(length=255), nullable=True))
        if not _has_column('obligaciones', 'soporte_amortizacion_mime'):
            op.add_column('obligaciones', sa.Column('soporte_amortizacion_mime', sa.String(length=120), nullable=True))
        if not _has_column('obligaciones', 'soporte_amortizacion_archivo'):
            op.add_column('obligaciones', sa.Column('soporte_amortizacion_archivo', sa.LargeBinary(), nullable=True))

    if not _has_table('amortizaciones_obligaciones'):
        op.create_table(
            'amortizaciones_obligaciones',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('obligacion_id', sa.Integer(), nullable=False),
            sa.Column('fecha_pago', sa.Date(), nullable=False),
            sa.Column('capital', sa.Numeric(14, 2), nullable=False),
            sa.Column('intereses', sa.Numeric(14, 2), nullable=False),
            sa.Column('seguro_vida', sa.Numeric(14, 2), nullable=True),
            sa.Column('otros', sa.Numeric(14, 2), nullable=True),
            sa.Column('tasa_namv', sa.Numeric(8, 4), nullable=True),
            sa.Column('saldo_capital', sa.Numeric(14, 2), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['obligacion_id'], ['obligaciones.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('obligacion_id', 'fecha_pago', name='uq_amortizacion_obligacion_fecha'),
        )

    if _has_table('pagos_obligaciones'):
        if not _has_column('pagos_obligaciones', 'componente_seguro_vida'):
            op.add_column('pagos_obligaciones', sa.Column('componente_seguro_vida', sa.Numeric(14, 2), nullable=True))
        if not _has_column('pagos_obligaciones', 'componente_otros'):
            op.add_column('pagos_obligaciones', sa.Column('componente_otros', sa.Numeric(14, 2), nullable=True))

    if _has_table('historial_pagos_obligaciones'):
        if not _has_column('historial_pagos_obligaciones', 'componente_seguro_vida'):
            op.add_column('historial_pagos_obligaciones', sa.Column('componente_seguro_vida', sa.Numeric(14, 2), nullable=True))
        if not _has_column('historial_pagos_obligaciones', 'componente_otros'):
            op.add_column('historial_pagos_obligaciones', sa.Column('componente_otros', sa.Numeric(14, 2), nullable=True))


def downgrade():
    if _has_table('historial_pagos_obligaciones'):
        if _has_column('historial_pagos_obligaciones', 'componente_otros'):
            op.drop_column('historial_pagos_obligaciones', 'componente_otros')
        if _has_column('historial_pagos_obligaciones', 'componente_seguro_vida'):
            op.drop_column('historial_pagos_obligaciones', 'componente_seguro_vida')

    if _has_table('pagos_obligaciones'):
        if _has_column('pagos_obligaciones', 'componente_otros'):
            op.drop_column('pagos_obligaciones', 'componente_otros')
        if _has_column('pagos_obligaciones', 'componente_seguro_vida'):
            op.drop_column('pagos_obligaciones', 'componente_seguro_vida')

    if _has_table('amortizaciones_obligaciones'):
        op.drop_table('amortizaciones_obligaciones')

    if _has_table('obligaciones'):
        if _has_column('obligaciones', 'soporte_amortizacion_archivo'):
            op.drop_column('obligaciones', 'soporte_amortizacion_archivo')
        if _has_column('obligaciones', 'soporte_amortizacion_mime'):
            op.drop_column('obligaciones', 'soporte_amortizacion_mime')
        if _has_column('obligaciones', 'soporte_amortizacion_nombre'):
            op.drop_column('obligaciones', 'soporte_amortizacion_nombre')
        if _has_column('obligaciones', 'fecha_inicio_amortizacion'):
            op.drop_column('obligaciones', 'fecha_inicio_amortizacion')
