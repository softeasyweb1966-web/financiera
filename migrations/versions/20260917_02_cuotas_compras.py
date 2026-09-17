"""Condición de pago y calendario de cuotas de compras."""
from alembic import op
import sqlalchemy as sa

revision = '20260917_02'
down_revision = '20260917_01'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'condicion_pago' not in {c['name'] for c in inspector.get_columns('compras')}:
        op.add_column('compras', sa.Column('condicion_pago', sa.String(20)))
    if not inspector.has_table('cuotas_compras'):
        op.create_table('cuotas_compras',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('compra_id', sa.Integer, sa.ForeignKey('compras.id'), nullable=False),
            sa.Column('fecha_vencimiento', sa.Date, nullable=False),
            sa.Column('valor', sa.Numeric(14, 2), nullable=False),
            sa.Column('es_inicial', sa.Boolean, nullable=False, server_default=sa.false()))
        op.create_index('ix_cuotas_compras_compra_id', 'cuotas_compras', ['compra_id'])


def downgrade():
    op.drop_table('cuotas_compras')
    op.drop_column('compras', 'condicion_pago')
