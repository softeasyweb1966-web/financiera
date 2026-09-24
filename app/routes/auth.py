from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import db
from app.models import Rol, Usuario, UsuarioPermiso
from app.permissions import ACCION_LABELS, MENU_PERMISOS, PERMISSION_ACTIONS, PERMISSION_MENUS
from app.security import roles_required

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

DEFAULT_ROLES = {
    'admin': 'Administrador del sistema',
    'operador': 'Puede registrar y consultar informacion operativa',
    'consulta': 'Puede consultar informacion sin administrar usuarios',
}


def ensure_default_roles():
    for nombre, descripcion in DEFAULT_ROLES.items():
        if not Rol.query.filter_by(nombre=nombre).first():
            db.session.add(Rol(nombre=nombre, descripcion=descripcion))
    db.session.commit()


def _selected_roles():
    role_ids = [int(role_id) for role_id in request.form.getlist('roles') if role_id.isdigit()]
    return Rol.query.filter(Rol.id.in_(role_ids)).all() if role_ids else []


def _selected_permissions():
    permisos = set()
    for raw in request.form.getlist('permisos'):
        if ':' not in raw:
            continue
        menu, accion = raw.split(':', 1)
        if menu in PERMISSION_MENUS and accion in PERMISSION_ACTIONS:
            permisos.add((menu, accion))
    return permisos


def _default_permissions_for_roles(roles):
    role_names = {rol.nombre for rol in roles}
    permisos = set()
    if 'admin' in role_names:
        for menu in MENU_PERMISOS:
            permisos.update((menu['key'], accion) for accion in menu['acciones'])
    elif 'operador' in role_names:
        for menu in MENU_PERMISOS:
            if menu['key'] != 'admin':
                permisos.update((menu['key'], accion) for accion in menu['acciones'])
    elif 'consulta' in role_names:
        permisos.update((menu['key'], 'ver') for menu in MENU_PERMISOS if 'ver' in menu['acciones'])
    return permisos


def _sync_permissions(usuario, permisos):
    if usuario.id:
        usuario.permisos.delete(synchronize_session=False)
    for menu, accion in sorted(permisos):
        usuario.permisos.append(UsuarioPermiso(menu=menu, accion=accion))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if Usuario.query.count() == 0:
        return redirect(url_for('auth.bootstrap'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        usuario = Usuario.query.filter_by(email=email).first()

        if not usuario or not usuario.activo or not usuario.check_password(password):
            flash('Correo o contraseña incorrectos.', 'danger')
            return render_template('auth/login.html', email=email)

        session.clear()
        session['user_id'] = usuario.id
        usuario.ultimo_acceso = datetime.utcnow()
        db.session.commit()
        flash(f'Bienvenido, {usuario.nombre}.', 'success')
        next_url = request.args.get('next') or url_for('main.index')
        return redirect(next_url)

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Sesion cerrada correctamente.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/bootstrap', methods=['GET', 'POST'])
def bootstrap():
    if Usuario.query.count() > 0:
        flash('La cuenta inicial ya fue creada.', 'info')
        return redirect(url_for('auth.login'))

    ensure_default_roles()
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        if not nombre or not email or not password:
            flash('Completa nombre, correo y contraseña.', 'danger')
            return render_template('auth/bootstrap.html', nombre=nombre, email=email)
        if password != password_confirm:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('auth/bootstrap.html', nombre=nombre, email=email)
        if len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
            return render_template('auth/bootstrap.html', nombre=nombre, email=email)

        admin_role = Rol.query.filter_by(nombre='admin').first()
        usuario = Usuario(nombre=nombre, email=email, roles=[admin_role])
        usuario.set_password(password)
        db.session.add(usuario)
        db.session.commit()
        flash('Administrador inicial creado. Ya puedes ingresar.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/bootstrap.html')


@auth_bp.route('/usuarios')
@roles_required('admin')
def usuarios():
    ensure_default_roles()
    usuarios = Usuario.query.order_by(Usuario.nombre).all()
    roles = Rol.query.order_by(Rol.nombre).all()
    return render_template(
        'auth/usuarios.html',
        usuarios=usuarios,
        roles=roles,
        menu_permisos=MENU_PERMISOS,
        accion_labels=ACCION_LABELS,
    )


@auth_bp.route('/usuarios/guardar', methods=['POST'])
@roles_required('admin')
def guardar_usuario():
    ensure_default_roles()
    usuario_id = request.form.get('id', type=int)
    nombre = request.form.get('nombre', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    password_confirm = request.form.get('password_confirm', '')
    roles = _selected_roles()
    permisos = _selected_permissions()

    if not nombre or not email:
        flash('Nombre y correo son obligatorios.', 'danger')
        return redirect(url_for('auth.usuarios'))
    if not roles:
        flash('Selecciona al menos un rol.', 'danger')
        return redirect(url_for('auth.usuarios'))
    if not permisos:
        permisos = _default_permissions_for_roles(roles)

    existente = Usuario.query.filter_by(email=email).first()
    if usuario_id:
        usuario = Usuario.query.get_or_404(usuario_id)
        if existente and existente.id != usuario.id:
            flash('Ya existe un usuario con ese correo.', 'danger')
            return redirect(url_for('auth.usuarios'))
        usuario.nombre = nombre
        usuario.email = email
        usuario.roles = roles
        _sync_permissions(usuario, permisos)
        if password:
            if password != password_confirm:
                flash('Las contrasenas no coinciden.', 'danger')
                return redirect(url_for('auth.usuarios'))
            if len(password) < 8:
                flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
                return redirect(url_for('auth.usuarios'))
            usuario.set_password(password)
        flash(f'Usuario "{nombre}" actualizado.', 'success')
    else:
        if existente:
            flash('Ya existe un usuario con ese correo.', 'danger')
            return redirect(url_for('auth.usuarios'))
        if password != password_confirm:
            flash('Las contrasenas no coinciden.', 'danger')
            return redirect(url_for('auth.usuarios'))
        if len(password) < 8:
            flash('La contraseña nueva debe tener al menos 8 caracteres.', 'danger')
            return redirect(url_for('auth.usuarios'))
        usuario = Usuario(nombre=nombre, email=email, roles=roles)
        usuario.set_password(password)
        db.session.add(usuario)
        _sync_permissions(usuario, permisos)
        flash(f'Usuario "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('auth.usuarios'))


@auth_bp.route('/usuarios/<int:usuario_id>/toggle', methods=['POST'])
@roles_required('admin')
def toggle_usuario(usuario_id):
    usuario = Usuario.query.get_or_404(usuario_id)
    usuario.activo = not usuario.activo
    db.session.commit()
    estado = 'activado' if usuario.activo else 'desactivado'
    flash(f'Usuario "{usuario.nombre}" {estado}.', 'info')
    return redirect(url_for('auth.usuarios'))


@auth_bp.route('/cambiar-clave', methods=['GET', 'POST'])
def cambiar_clave():
    usuario = Usuario.query.get(session.get('user_id'))
    if not usuario:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        password_actual = request.form.get('password_actual', '')
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        if not usuario.check_password(password_actual):
            flash('La clave actual no es correcta.', 'danger')
            return render_template('auth/cambiar_clave.html')
        if password != password_confirm:
            flash('Las claves nuevas no coinciden.', 'danger')
            return render_template('auth/cambiar_clave.html')
        if len(password) < 8:
            flash('La nueva clave debe tener al menos 8 caracteres.', 'danger')
            return render_template('auth/cambiar_clave.html')
        if usuario.check_password(password):
            flash('La nueva clave debe ser diferente a la actual.', 'warning')
            return render_template('auth/cambiar_clave.html')

        usuario.set_password(password)
        db.session.commit()
        flash('Tu clave fue actualizada correctamente.', 'success')
        return redirect(url_for('main.index'))

    return render_template('auth/cambiar_clave.html')
