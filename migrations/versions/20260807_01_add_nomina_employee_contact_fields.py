"""add nomina employee contact fields

Revision ID: 20260807_01
Revises: 
Create Date: 2026-08-07 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260807_01'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('empleados', sa.Column('forma_pago', sa.String(length=20), nullable=True))
    op.add_column('empleados', sa.Column('whatsapp', sa.String(length=20), nullable=True))
    op.add_column('empleados', sa.Column('autoriza_whatsapp', sa.Boolean(), nullable=True))

    op.execute("UPDATE empleados SET forma_pago = 'quincenal' WHERE forma_pago IS NULL")
    op.execute("UPDATE empleados SET autoriza_whatsapp = false WHERE autoriza_whatsapp IS NULL")


def downgrade():
    op.drop_column('empleados', 'autoriza_whatsapp')
    op.drop_column('empleados', 'whatsapp')
    op.drop_column('empleados', 'forma_pago')
