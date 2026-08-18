from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import Compra, ConceptoCompra, ProductoCompra, Tercero, MedioPago
from datetime import datetime, date
from sqlalchemy import func, extract

compras_bp = Blueprint('compras', __name__, url_prefix='/compras')

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


@compras_bp.route('/')
@compras_bp.route('/<int:anio>')
@compras_bp.route('/<int:anio>/<int:mes>')
def lista(anio=None, mes=None):
    if anio is None:
        anio = date.today().year
    if mes is None:
        mes = date.today().month

    conceptos = ConceptoCompra.query.filter_by(activo=True).order_by(ConceptoCompra.nombre).all()
    productos = ProductoCompra.query.filter_by(activo=True).order_by(ProductoCompra.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()

    # Compras del mes seleccionado
    compras_mes = Compra.query.filter(
        extract('year', Compra.fecha) == anio,
        extract('month', Compra.fecha) == mes
    ).order_by(Compra.fecha.desc()).all()

    compras_pagadas_anteriores = Compra.query.filter(
        extract('year', Compra.fecha) == anio,
        extract('month', Compra.fecha) < mes,
        Compra.estado == 'pagado'
    ).order_by(Compra.fecha.desc()).all()

    # Acumulado pagado meses anteriores
    acum_pagado_anterior = db.session.query(
        func.coalesce(func.sum(Compra.valor), 0)
    ).filter(
        extract('year', Compra.fecha) == anio,
        extract('month', Compra.fecha) < mes,
        Compra.estado == 'pagado'
    ).scalar()

    # Pendientes de meses anteriores
    pendientes_anteriores_list = Compra.query.filter(
        Compra.estado == 'pendiente',
        db.or_(
            extract('year', Compra.fecha) < anio,
            db.and_(
                extract('year', Compra.fecha) == anio,
                extract('month', Compra.fecha) < mes
            )
        )
    ).order_by(Compra.fecha).all()

    total_deuda_anterior = sum(float(c.valor) for c in pendientes_anteriores_list)

    pendientes_anteriores = []
    for c in pendientes_anteriores_list:
        pendientes_anteriores.append({
            'compra': c,
            'mes_nombre': MESES[c.fecha.month - 1],
            'anio': c.fecha.year,
            'valor': float(c.valor)
        })

    # Pagado y pendiente del mes actual
    pagado_mes = sum(float(c.valor) for c in compras_mes if c.estado == 'pagado')
    pendiente_mes = sum(float(c.valor) for c in compras_mes if c.estado == 'pendiente')
    total_mes = pagado_mes + pendiente_mes

    # Resumen por concepto de compra
    resumen_conceptos = {}
    for c in compras_mes:
        concepto_nombre = c.concepto_compra.nombre if c.concepto_compra else 'Sin concepto'
        if concepto_nombre not in resumen_conceptos:
            resumen_conceptos[concepto_nombre] = {
                'nombre': concepto_nombre,
                'color': '#6366f1',
                'pagado': 0,
                'pendiente': 0,
                'cantidad': 0
            }
        resumen_conceptos[concepto_nombre]['cantidad'] += 1
        if c.estado == 'pagado':
            resumen_conceptos[concepto_nombre]['pagado'] += float(c.valor)
        else:
            resumen_conceptos[concepto_nombre]['pendiente'] += float(c.valor)

    resumen_grupos = list(resumen_conceptos.values())
    # Assign colors
    colores = ['#2563eb', '#059669', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4', '#ec4899']
    for i, g in enumerate(resumen_grupos):
        g['color'] = colores[i % len(colores)]
    resumen_grupos = sorted(
        resumen_grupos,
        key=lambda x: x['pagado'] + x['pendiente'],
        reverse=True
    )

    resumen_items = {}
    for c in compras_mes:
        item_nombre = (
            c.producto_compra.nombre if c.producto_compra
            else c.descripcion
            or 'Sin item'
        )
        if item_nombre not in resumen_items:
            resumen_items[item_nombre] = {
                'nombre': item_nombre,
                'pagado': 0,
                'pendiente': 0,
                'cantidad': 0,
                'total': 0
            }
        resumen_items[item_nombre]['cantidad'] += 1
        if c.estado == 'pagado':
            resumen_items[item_nombre]['pagado'] += float(c.valor)
        else:
            resumen_items[item_nombre]['pendiente'] += float(c.valor)
        resumen_items[item_nombre]['total'] += float(c.valor)

    resumen_items = sorted(
        resumen_items.values(),
        key=lambda x: (x['pagado'] + x['pendiente']),
        reverse=True
    )
    top_concepto = max(resumen_grupos, key=lambda x: x['pagado'] + x['pendiente']) if resumen_grupos else None
    top_item = resumen_items[0] if resumen_items else None

    items_mes_actual = []
    for c in compras_mes:
        items_mes_actual.append({
            'id': c.id,
            'fecha': c.fecha,
            'concepto': c.concepto_compra.nombre if c.concepto_compra else 'Sin concepto',
            'item': c.producto_compra.nombre if c.producto_compra else (c.descripcion or 'Sin item'),
            'proveedor': c.tercero.nombre if c.tercero else '-',
            'estado': c.estado,
            'valor': float(c.valor or 0),
            'medio': c.medio_pago.nombre if c.medio_pago else '-',
        })

    # Tarjetas
    compras_cards = []
    for c in compras_mes:
        compras_cards.append({
            'compra': c,
            'estado': c.estado,
        })

    return render_template('compras/lista.html',
                           compras_cards=compras_cards,
                           pendientes_anteriores=pendientes_anteriores,
                           anio=anio, mes=mes, meses=MESES,
                           conceptos=conceptos, productos=productos, medios=medios,
                           acum_pagado_anterior=float(acum_pagado_anterior),
                           pagado_mes=pagado_mes,
                           pendiente_mes=pendiente_mes,
                           total_mes=total_mes,
                           total_deuda_anterior=total_deuda_anterior,
                           compras_pagadas_anteriores=compras_pagadas_anteriores,
                           resumen_grupos=resumen_grupos,
                           resumen_items=resumen_items,
                           items_mes_actual=items_mes_actual,
                           top_concepto=top_concepto,
                           top_item=top_item)


@compras_bp.route('/nueva', methods=['GET', 'POST'])
def nueva():
    if request.method == 'POST':
        compra = Compra(
            fecha=datetime.strptime(request.form['fecha'], '%Y-%m-%d').date(),
            tercero_id=request.form.get('tercero_id') or None,
            concepto_compra_id=request.form['concepto_compra_id'],
            producto_compra_id=request.form.get('producto_compra_id') or None,
            descripcion=request.form['descripcion'].strip(),
            valor=request.form['valor'],
            medio_pago_id=request.form.get('medio_pago_id') or None,
            fecha_pago=request.form.get('fecha_pago') or None,
            estado=request.form.get('estado', 'pendiente'),
            observaciones=request.form.get('observaciones', '').strip()
        )
        db.session.add(compra)
        db.session.commit()
        flash('Compra registrada.', 'success')
        return redirect(url_for('compras.lista'))

    conceptos = ConceptoCompra.query.filter_by(activo=True).order_by(ConceptoCompra.nombre).all()
    productos = ProductoCompra.query.filter_by(activo=True).order_by(ProductoCompra.nombre).all()
    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    return render_template('compras/form.html', compra=None,
                           conceptos=conceptos, productos=productos, terceros=terceros, medios=medios)


@compras_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    compra = Compra.query.get_or_404(id)
    if request.method == 'POST':
        compra.fecha = datetime.strptime(request.form['fecha'], '%Y-%m-%d').date()
        compra.tercero_id = request.form.get('tercero_id') or None
        compra.concepto_compra_id = request.form['concepto_compra_id']
        compra.producto_compra_id = request.form.get('producto_compra_id') or None
        compra.descripcion = request.form['descripcion'].strip()
        compra.valor = request.form['valor']
        compra.medio_pago_id = request.form.get('medio_pago_id') or None
        compra.fecha_pago = request.form.get('fecha_pago') or None
        compra.estado = request.form.get('estado', 'pendiente')
        compra.observaciones = request.form.get('observaciones', '').strip()
        db.session.commit()
        flash('Compra actualizada.', 'success')
        return redirect(url_for('compras.lista'))

    conceptos = ConceptoCompra.query.filter_by(activo=True).order_by(ConceptoCompra.nombre).all()
    productos = ProductoCompra.query.filter_by(activo=True).order_by(ProductoCompra.nombre).all()
    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    return render_template('compras/form.html', compra=compra,
                           conceptos=conceptos, productos=productos, terceros=terceros, medios=medios)


@compras_bp.route('/detalle/<int:id>')
def detalle(id):
    """Vista detalle completa de una compra"""
    compra = Compra.query.get_or_404(id)
    return render_template('compras/detalle.html', compra=compra)


@compras_bp.route('/<int:id>/pagar', methods=['POST'])
def marcar_pagado(id):
    compra = Compra.query.get_or_404(id)
    compra.estado = 'pagado'
    compra.fecha_pago = request.form.get('fecha_pago') or date.today()
    compra.medio_pago_id = request.form.get('medio_pago_id') or None
    db.session.commit()
    flash('Compra marcada como pagada.', 'success')
    return redirect(url_for('compras.lista', anio=compra.fecha.year, mes=compra.fecha.month))


# ==================== APIs para crear inline ====================

@compras_bp.route('/api/crear-concepto', methods=['POST'])
def api_crear_concepto():
    data = request.get_json()
    nombre = (data.get('nombre') or '').strip()
    descripcion = (data.get('descripcion') or '').strip()

    if not nombre:
        return jsonify({'error': 'El nombre es requerido'}), 400

    existente = ConceptoCompra.query.filter_by(nombre=nombre).first()
    if existente:
        return jsonify({'error': f'Ya existe un concepto con el nombre "{nombre}"'}), 400

    concepto = ConceptoCompra(nombre=nombre, descripcion=descripcion or None)
    db.session.add(concepto)
    db.session.commit()
    return jsonify({'id': concepto.id, 'nombre': concepto.nombre})


@compras_bp.route('/api/crear-item', methods=['POST'])
def api_crear_item():
    data = request.get_json()
    nombre = (data.get('nombre') or '').strip()
    concepto_compra_id = data.get('concepto_compra_id')

    if not nombre or not concepto_compra_id:
        return jsonify({'error': 'Nombre y concepto son requeridos'}), 400

    existente = ProductoCompra.query.filter_by(nombre=nombre, concepto_compra_id=concepto_compra_id).first()
    if existente:
        return jsonify({'error': f'Ya existe un item "{nombre}" en ese concepto'}), 400

    item = ProductoCompra(nombre=nombre, concepto_compra_id=int(concepto_compra_id))
    db.session.add(item)
    db.session.commit()
    return jsonify({'id': item.id, 'nombre': item.nombre, 'concepto_compra_id': item.concepto_compra_id})
