"""Historial de anulaciones de compras."""
from alembic import op
import sqlalchemy as sa

revision = '20260917_03'
down_revision = '20260917_02'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('historial_compras'):
        op.create_table(
            'historial_compras',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('compra_id', sa.Integer, sa.ForeignKey('compras.id'), nullable=False),
            sa.Column('accion', sa.String(20), nullable=False),
            sa.Column('motivo', sa.Text, nullable=False),
            sa.Column('estado_anterior', sa.String(20)),
            sa.Column('valor_total', sa.Numeric(14, 2)),
            sa.Column('valor_abonado', sa.Numeric(14, 2)),
            sa.Column('saldo', sa.Numeric(14, 2)),
            sa.Column('observaciones', sa.Text),
            sa.Column('registrado_por', sa.String(100)),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_historial_compras_compra_id', 'historial_compras', ['compra_id'])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('historial_compras'):
        op.drop_table('historial_compras')
