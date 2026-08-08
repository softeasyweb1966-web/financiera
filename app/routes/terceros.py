from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import Tercero, TipoTercero, HistorialEstado
from datetime import datetime, date

terceros_bp = Blueprint('terceros', __name__, url_prefix='/terceros')

ESTADOS = ['activo', 'inactivo', 'retirado', 'anulado']


def registrar_cambio_estado(entidad, entidad_id, estado_anterior, estado_nuevo, motivo=None):
    """Registra un cambio de estado en el historial"""
    if estado_anterior != estado_nuevo:
        hist = HistorialEstado(
            entidad=entidad, entidad_id=entidad_id,
            estado_anterior=estado_anterior, estado_nuevo=estado_nuevo,
            fecha_cambio=datetime.utcnow(), motivo=motivo
        )
        db.session.add(hist)


@terceros_bp.route('/')
def lista():
    tipo_id = request.args.get('tipo', type=int)
    nombre_q = request.args.get('q', '').strip()
    estado = request.args.get('estado', 'activo')

    query = Tercero.query
    if estado == 'activo':
        query = query.filter_by(activo=True)
    elif estado == 'inactivo':
        query = query.filter_by(activo=False)
    # 'todos' no filtra por estado

    if tipo_id:
        query = query.filter_by(tipo_tercero_id=tipo_id)
    if nombre_q:
        query = query.filter(Tercero.nombre.ilike(f'%{nombre_q}%'))

    terceros = query.order_by(Tercero.nombre).all()
    tipos = TipoTercero.query.order_by(TipoTercero.nombre).all()
    return render_template('terceros/lista.html',
                           terceros=terceros, tipos=tipos,
                           tipo_filtro=tipo_id, nombre_filtro=nombre_q,
                           estado_filtro=estado)


@terceros_bp.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if request.method == 'POST':
        estado = request.form.get('estado', 'activo')
        tercero = Tercero(
            tipo_tercero_id=request.form['tipo_tercero_id'],
            nombre=request.form['nombre'].strip().upper(),
            identificacion=request.form.get('identificacion', '').strip() or None,
            telefono=request.form.get('telefono', '').strip() or None,
            email=request.form.get('email', '').strip() or None,
            direccion=request.form.get('direccion', '').strip() or None,
            observaciones=request.form.get('observaciones', '').strip() or None,
            estado=estado,
            activo=(estado == 'activo')
        )
        db.session.add(tercero)
        db.session.commit()
        flash(f'Tercero "{tercero.nombre}" creado.', 'success')
        return redirect(url_for('terceros.lista'))
    tipos = TipoTercero.query.order_by(TipoTercero.nombre).all()
    return render_template('terceros/form.html', tercero=None, tipos=tipos)


@terceros_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    tercero = Tercero.query.get_or_404(id)
    if request.method == 'POST':
        # Registrar cambio de estado si cambió
        nuevo_estado = request.form.get('estado', 'activo')
        estado_anterior = tercero.estado or 'activo'
        if nuevo_estado != estado_anterior:
            motivo = request.form.get('motivo_estado', '').strip()
            fecha_str = request.form.get('fecha_cambio_estado')
            fecha_cambio = datetime.strptime(fecha_str, '%Y-%m-%d') if fecha_str else datetime.utcnow()
            hist = HistorialEstado(
                entidad='tercero', entidad_id=id,
                estado_anterior=estado_anterior, estado_nuevo=nuevo_estado,
                fecha_cambio=fecha_cambio, motivo=motivo
            )
            db.session.add(hist)
            tercero.estado = nuevo_estado
            tercero.activo = (nuevo_estado == 'activo')

        tercero.tipo_tercero_id = request.form['tipo_tercero_id']
        tercero.nombre = request.form['nombre'].strip().upper()
        tercero.identificacion = request.form.get('identificacion', '').strip() or None
        tercero.telefono = request.form.get('telefono', '').strip() or None
        tercero.email = request.form.get('email', '').strip() or None
        tercero.direccion = request.form.get('direccion', '').strip() or None
        tercero.observaciones = request.form.get('observaciones', '').strip() or None
        db.session.commit()
        flash(f'Tercero "{tercero.nombre}" actualizado.', 'success')
        return redirect(url_for('terceros.lista'))
    tipos = TipoTercero.query.order_by(TipoTercero.nombre).all()
    return render_template('terceros/form.html', tercero=tercero, tipos=tipos,
                           today=date.today().strftime('%Y-%m-%d'))


@terceros_bp.route('/<int:id>/cambiar-estado', methods=['POST'])
def cambiar_estado(id):
    tercero = Tercero.query.get_or_404(id)
    nuevo_estado = request.form.get('estado', 'inactivo')
    motivo = request.form.get('motivo', '').strip()
    estado_anterior = tercero.estado or 'activo'

    registrar_cambio_estado('tercero', id, estado_anterior, nuevo_estado, motivo)

    tercero.estado = nuevo_estado
    tercero.activo = (nuevo_estado == 'activo')
    db.session.commit()
    flash(f'Tercero "{tercero.nombre}" cambió a estado: {nuevo_estado}.', 'info')
    return redirect(url_for('terceros.lista'))


@terceros_bp.route('/<int:id>/historial')
def historial(id):
    tercero = Tercero.query.get_or_404(id)
    registros = HistorialEstado.query.filter_by(
        entidad='tercero', entidad_id=id
    ).order_by(HistorialEstado.fecha_cambio.desc()).all()
    return render_template('terceros/historial.html', tercero=tercero, registros=registros)


# API para autocompletado
@terceros_bp.route('/api/buscar')
def api_buscar():
    q = request.args.get('q', '').strip()
    tipo_id = request.args.get('tipo', type=int)
    query = Tercero.query.filter_by(activo=True)
    if tipo_id:
        query = query.filter_by(tipo_tercero_id=tipo_id)
    if q:
        query = query.filter(Tercero.nombre.ilike(f'%{q}%'))
    resultados = query.order_by(Tercero.nombre).limit(15).all()
    return jsonify([{'id': t.id, 'nombre': t.nombre,
                     'tipo': t.tipo_tercero_rel.nombre} for t in resultados])
