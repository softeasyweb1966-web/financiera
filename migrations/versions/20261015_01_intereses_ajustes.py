"""Intereses anticipados/vencidos y anulaciones de deuda auditables."""
from alembic import op
import sqlalchemy as sa

revision = '20261015_01'
down_revision = '20260924_01'
branch_labels = None
depends_on = None


def upgrade():
    from app.models import AjusteObligacion
    columnas = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('obligaciones')}
    for columna in (sa.Column('tipo_interes', sa.String(12)),
                    sa.Column('fecha_pago_capital', sa.Date()),
                    sa.Column('interes_cierre', sa.Numeric(14, 2))):
        if columna.name not in columnas:
            op.add_column('obligaciones', columna)
    AjusteObligacion.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table('ajustes_obligaciones')
    for nombre in ('interes_cierre', 'fecha_pago_capital', 'tipo_interes'):
        op.drop_column('obligaciones', nombre)
