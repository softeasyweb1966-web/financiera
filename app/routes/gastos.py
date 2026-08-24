from flask import Blueprint, redirect, url_for, flash

gastos_bp = Blueprint('gastos', __name__, url_prefix='/gastos')


@gastos_bp.route('/')
@gastos_bp.route('/<int:anio>')
@gastos_bp.route('/<int:anio>/<int:mes>')
def lista(anio=None, mes=None):
    kwargs = {}
    if anio is not None:
        kwargs['anio'] = anio
    if mes is not None:
        kwargs['mes'] = mes
    return redirect(url_for('compras.lista', **kwargs))


@gastos_bp.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    flash('El modulo Gastos fue unificado en Compras y Gastos.', 'info')
    return redirect(url_for('compras.nueva'))


@gastos_bp.route('/detalle/<int:id>')
def detalle(id):
    flash('El modulo Gastos fue unificado en Compras y Gastos.', 'info')
    return redirect(url_for('compras.lista'))


@gastos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    flash('El modulo Gastos fue unificado en Compras y Gastos.', 'info')
    return redirect(url_for('compras.lista'))
