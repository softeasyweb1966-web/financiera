"""Permite nombres de modalidad de crédito más descriptivos."""
from alembic import op
import sqlalchemy as sa

revision = '20261015_02'
down_revision = '20261015_01'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'obligaciones' in inspector.get_table_names():
        op.alter_column('obligaciones', 'modalidad',
                        existing_type=sa.String(length=30),
                        type_=sa.String(length=50),
                        existing_nullable=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'obligaciones' in inspector.get_table_names():
        op.alter_column('obligaciones', 'modalidad',
                        existing_type=sa.String(length=50),
                        type_=sa.String(length=30),
                        existing_nullable=False)
