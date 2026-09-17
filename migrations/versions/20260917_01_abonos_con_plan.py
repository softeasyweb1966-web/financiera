"""Conservar el plan, descuento y reversión de los abonos."""
from alembic import op
import sqlalchemy as sa

revision = '20260917_01'
down_revision = '20260824_02'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('abonos_capital_obligaciones')}
    if 'datos_movimiento' not in columns:
        op.add_column('abonos_capital_obligaciones', sa.Column('datos_movimiento', sa.Text()))


def downgrade():
    op.drop_column('abonos_capital_obligaciones', 'datos_movimiento')
