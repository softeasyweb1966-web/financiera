"""Historial de modificaciones de causaciones de nomina."""
from alembic import op
import sqlalchemy as sa

revision = '20260917_05'
down_revision = '20260917_04'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('historial_causaciones_nomina'):
        op.create_table(
            'historial_causaciones_nomina',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('empleado_id', sa.Integer, sa.ForeignKey('empleados.id'), nullable=False),
            sa.Column('anio', sa.Integer, nullable=False),
            sa.Column('mes', sa.Integer, nullable=False),
            sa.Column('quincena', sa.Integer, nullable=False),
            sa.Column('accion', sa.String(30), nullable=False, server_default='modificacion'),
            sa.Column('motivo', sa.Text, nullable=False),
            sa.Column('valor_anterior', sa.Numeric(14, 2), nullable=False),
            sa.Column('valor_nuevo', sa.Numeric(14, 2), nullable=False),
            sa.Column('concepto_principal_id', sa.Integer, sa.ForeignKey('conceptos_nomina.id')),
            sa.Column('registros_antes', sa.Text),
            sa.Column('registros_despues', sa.Text),
            sa.Column('registrado_por', sa.String(100)),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_historial_causaciones_nomina_empleado_id', 'historial_causaciones_nomina', ['empleado_id'])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('historial_causaciones_nomina'):
        op.drop_table('historial_causaciones_nomina')
