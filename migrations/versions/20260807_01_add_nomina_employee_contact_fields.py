"""add nomina employee contact fields

Revision ID: 20260807_01
Revises: 
Create Date: 2026-08-07 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from app import db
from app import models  # noqa: F401


# revision identifiers, used by Alembic.
revision = '20260807_01'
down_revision = None
branch_labels = None
depends_on = None


def _has_column(table_name, column_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return False
    return column_name in {col['name'] for col in inspector.get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Fresh databases in Railway start empty; bootstrap the full current schema first.
    if not inspector.has_table('tipo_tercero'):
        db.metadata.create_all(bind=bind)
        return

    if not _has_column('empleados', 'forma_pago'):
        op.add_column('empleados', sa.Column('forma_pago', sa.String(length=20), nullable=True))
    if not _has_column('empleados', 'whatsapp'):
        op.add_column('empleados', sa.Column('whatsapp', sa.String(length=20), nullable=True))
    if not _has_column('empleados', 'autoriza_whatsapp'):
        op.add_column('empleados', sa.Column('autoriza_whatsapp', sa.Boolean(), nullable=True))

    op.execute("UPDATE empleados SET forma_pago = 'quincenal' WHERE forma_pago IS NULL")
    op.execute("UPDATE empleados SET autoriza_whatsapp = false WHERE autoriza_whatsapp IS NULL")


def downgrade():
    if _has_column('empleados', 'autoriza_whatsapp'):
        op.drop_column('empleados', 'autoriza_whatsapp')
    if _has_column('empleados', 'whatsapp'):
        op.drop_column('empleados', 'whatsapp')
    if _has_column('empleados', 'forma_pago'):
        op.drop_column('empleados', 'forma_pago')
