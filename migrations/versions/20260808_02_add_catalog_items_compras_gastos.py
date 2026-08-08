"""add catalog items for compras y gastos

Revision ID: 20260808_02
Revises: 20260808_01
Create Date: 2026-08-08 10:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = '20260808_02'
down_revision = '20260808_01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'productos_compras',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('concepto_compra_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=150), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['concepto_compra_id'], ['conceptos_compras.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('concepto_compra_id', 'nombre', name='uq_producto_compra_concepto_nombre')
    )

    op.create_table(
        'items_gastos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('concepto_gasto_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(length=150), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['concepto_gasto_id'], ['conceptos_gastos.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('concepto_gasto_id', 'nombre', name='uq_item_gasto_concepto_nombre')
    )

    op.add_column('compras', sa.Column('producto_compra_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_compras_producto_compra_id',
        'compras', 'productos_compras',
        ['producto_compra_id'], ['id']
    )

    op.add_column('gastos', sa.Column('item_gasto_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_gastos_item_gasto_id',
        'gastos', 'items_gastos',
        ['item_gasto_id'], ['id']
    )


def downgrade():
    op.drop_constraint('fk_gastos_item_gasto_id', 'gastos', type_='foreignkey')
    op.drop_column('gastos', 'item_gasto_id')
    op.drop_constraint('fk_compras_producto_compra_id', 'compras', type_='foreignkey')
    op.drop_column('compras', 'producto_compra_id')
    op.drop_table('items_gastos')
    op.drop_table('productos_compras')
