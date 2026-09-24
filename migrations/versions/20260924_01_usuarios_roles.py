"""Usuarios y roles."""
from alembic import op
import sqlalchemy as sa

revision = '20260924_01'
down_revision = '20260917_05'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table('roles'):
        op.create_table(
            'roles',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('nombre', sa.String(50), nullable=False, unique=True),
            sa.Column('descripcion', sa.Text),
            sa.Column('created_at', sa.DateTime),
        )

    if not inspector.has_table('usuarios'):
        op.create_table(
            'usuarios',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('nombre', sa.String(100), nullable=False),
            sa.Column('email', sa.String(120), nullable=False, unique=True),
            sa.Column('password_hash', sa.String(255), nullable=False),
            sa.Column('activo', sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column('ultimo_acceso', sa.DateTime),
            sa.Column('created_at', sa.DateTime),
            sa.Column('updated_at', sa.DateTime),
        )
        op.create_index('ix_usuarios_email', 'usuarios', ['email'])

    if not inspector.has_table('usuario_roles'):
        op.create_table(
            'usuario_roles',
            sa.Column('usuario_id', sa.Integer, sa.ForeignKey('usuarios.id'), primary_key=True),
            sa.Column('rol_id', sa.Integer, sa.ForeignKey('roles.id'), primary_key=True),
        )

    if not inspector.has_table('usuario_permisos'):
        op.create_table(
            'usuario_permisos',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('usuario_id', sa.Integer, sa.ForeignKey('usuarios.id'), nullable=False),
            sa.Column('menu', sa.String(50), nullable=False),
            sa.Column('accion', sa.String(30), nullable=False),
            sa.Column('created_at', sa.DateTime),
            sa.UniqueConstraint('usuario_id', 'menu', 'accion', name='uq_usuario_permiso_menu_accion'),
        )
        op.create_index('ix_usuario_permisos_usuario_id', 'usuario_permisos', ['usuario_id'])

    op.execute("""
        INSERT INTO roles (nombre, descripcion)
        SELECT 'admin', 'Administrador del sistema'
        WHERE NOT EXISTS (SELECT 1 FROM roles WHERE nombre = 'admin')
    """)
    op.execute("""
        INSERT INTO roles (nombre, descripcion)
        SELECT 'operador', 'Puede registrar y consultar informacion operativa'
        WHERE NOT EXISTS (SELECT 1 FROM roles WHERE nombre = 'operador')
    """)
    op.execute("""
        INSERT INTO roles (nombre, descripcion)
        SELECT 'consulta', 'Puede consultar informacion sin administrar usuarios'
        WHERE NOT EXISTS (SELECT 1 FROM roles WHERE nombre = 'consulta')
    """)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table('usuario_permisos'):
        op.drop_index('ix_usuario_permisos_usuario_id', table_name='usuario_permisos')
        op.drop_table('usuario_permisos')
    if inspector.has_table('usuario_roles'):
        op.drop_table('usuario_roles')
    if inspector.has_table('usuarios'):
        op.drop_index('ix_usuarios_email', table_name='usuarios')
        op.drop_table('usuarios')
    if inspector.has_table('roles'):
        op.drop_table('roles')
