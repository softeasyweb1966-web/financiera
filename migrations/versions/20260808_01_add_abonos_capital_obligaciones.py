"""add abonos capital obligaciones

Revision ID: 20260808_01
Revises: 20260807_01
Create Date: 2026-08-08 09:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260808_01'
down_revision = '20260807_01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'abonos_capital_obligaciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('obligacion_id', sa.Integer(), nullable=False),
        sa.Column('fecha_abono', sa.Date(), nullable=False),
        sa.Column('valor_abono', sa.Numeric(14, 2), nullable=False),
        sa.Column('saldo_anterior', sa.Numeric(14, 2), nullable=True),
        sa.Column('saldo_nuevo', sa.Numeric(14, 2), nullable=True),
        sa.Column('opcion_recalculo', sa.String(length=20), nullable=False),
        sa.Column('cuotas_pendientes_antes', sa.Integer(), nullable=True),
        sa.Column('cuotas_pendientes_despues', sa.Integer(), nullable=True),
        sa.Column('cuota_anterior', sa.Numeric(14, 2), nullable=True),
        sa.Column('cuota_nueva', sa.Numeric(14, 2), nullable=True),
        sa.Column('observaciones', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['obligacion_id'], ['obligaciones.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('abonos_capital_obligaciones')
