"""add vigencia to historial estados

Revision ID: 20260811_01
Revises: 20260808_02
Create Date: 2026-08-11 13:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = '20260811_01'
down_revision = '20260808_02'
branch_labels = None
depends_on = None


def _has_table(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(table_name)


def _has_column(table_name, column_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {col['name'] for col in inspector.get_columns(table_name)}


def upgrade():
    if not _has_table('historial_estados'):
        op.create_table(
            'historial_estados',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('entidad', sa.String(length=50), nullable=False),
            sa.Column('entidad_id', sa.Integer(), nullable=False),
            sa.Column('estado_anterior', sa.String(length=20), nullable=True),
            sa.Column('estado_nuevo', sa.String(length=20), nullable=False),
            sa.Column('fecha_cambio', sa.DateTime(), nullable=False),
            sa.Column('vigencia_desde', sa.Date(), nullable=True),
            sa.Column('motivo', sa.Text(), nullable=True),
            sa.Column('registrado_por', sa.String(length=100), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
    elif not _has_column('historial_estados', 'vigencia_desde'):
        op.add_column('historial_estados', sa.Column('vigencia_desde', sa.Date(), nullable=True))


def downgrade():
    if _has_table('historial_estados') and _has_column('historial_estados', 'vigencia_desde'):
        op.drop_column('historial_estados', 'vigencia_desde')
