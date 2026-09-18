"""Historial de anulaciones de pagos de nomina."""
from alembic import op
import sqlalchemy as sa

revision = '20260917_04'
down_revision = '20260917_03'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table('historial_pagos_nomina'):
        op.create_table(
            'historial_pagos_nomina',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('empleado_id', sa.Integer, sa.ForeignKey('empleados.id'), nullable=False),
            sa.Column('registro_nomina_id', sa.Integer, sa.ForeignKey('registros_nomina.id')),
            sa.Column('abono_nomina_id', sa.Integer),
            sa.Column('saldo_anterior_nomina_id', sa.Integer, sa.ForeignKey('saldos_anteriores_nomina.id')),
            sa.Column('anio', sa.Integer, nullable=False),
            sa.Column('mes', sa.Integer, nullable=False),
            sa.Column('quincena', sa.Integer, nullable=False),
            sa.Column('tipo_pago', sa.String(30), nullable=False),
            sa.Column('accion', sa.String(20), nullable=False, server_default='anulacion'),
            sa.Column('motivo', sa.Text, nullable=False),
            sa.Column('valor_pagado', sa.Numeric(14, 2)),
            sa.Column('fecha_pago', sa.Date),
            sa.Column('medio_pago_id', sa.Integer, sa.ForeignKey('medios_pago.id')),
            sa.Column('descripcion', sa.Text),
            sa.Column('observaciones', sa.Text),
            sa.Column('registrado_por', sa.String(100)),
            sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_historial_pagos_nomina_empleado_id', 'historial_pagos_nomina', ['empleado_id'])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('historial_pagos_nomina'):
        op.drop_table('historial_pagos_nomina')
