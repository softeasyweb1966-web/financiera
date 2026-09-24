from functools import wraps

from flask import flash, g, redirect, request, session, url_for

from app.models import Usuario


PUBLIC_ENDPOINTS = {
    'auth.login',
    'auth.logout',
    'auth.bootstrap',
    'main.healthz',
    'static',
}


def load_current_user():
    user_id = session.get('user_id')
    g.user = Usuario.query.get(user_id) if user_id else None
    if g.user and not g.user.activo:
        session.clear()
        g.user = None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.get('user'):
            return redirect(url_for('auth.login', next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.get('user'):
                return redirect(url_for('auth.login', next=request.full_path))
            if not g.user.has_role(*roles):
                flash('No tienes permisos para acceder a esta opcion.', 'warning')
                return redirect(url_for('main.index'))
            return view(*args, **kwargs)
        return wrapped
    return decorator
