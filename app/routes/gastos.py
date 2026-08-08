from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import Gasto, ConceptoGasto, ItemGasto, Tercero, MedioPago
from datetime import datetime, date
from sqlalchemy import func, extract

gastos_bp = Blueprint('gastos', __name__, url_prefix='/gastos')

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


@gastos_bp.route('/')
@gastos_bp.route('/<int:anio>')
@gastos_bp.route('/<int:anio>/<int:mes>')
def lista(anio=None, mes=None):
    if anio is None:
        anio = date.today().year
    if mes is None:
        mes = date.today().month

    conceptos = ConceptoGasto.query.filter_by(activo=True).order_by(ConceptoGasto.nombre).all()
    items_catalogo = ItemGasto.query.filter_by(activo=True).order_by(ItemGasto.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()

    # Gastos del mes seleccionado
    gastos_mes = Gasto.query.filter(
        extract('year', Gasto.fecha) == anio,
        extract('month', Gasto.fecha) == mes
    ).order_by(Gasto.fecha.desc()).all()

    gastos_anteriores = Gasto.query.filter(
        extract('year', Gasto.fecha) == anio,
        extract('month', Gasto.fecha) < mes
    ).order_by(Gasto.fecha.desc()).all()

    # Acumulado meses anteriores del año
    acum_anterior = db.session.query(
        func.coalesce(func.sum(Gasto.valor), 0)
    ).filter(
        extract('year', Gasto.fecha) == anio,
        extract('month', Gasto.fecha) < mes
    ).scalar()

    # Total del mes actual
    total_mes = sum(float(g.valor) for g in gastos_mes)

    # Promedio mensual (basado en meses transcurridos)
    meses_transcurridos = mes - 1 if mes > 1 else 1
    promedio_mensual = float(acum_anterior) / meses_transcurridos if meses_transcurridos > 0 and float(acum_anterior) > 0 else 0

    # Resumen por concepto de gasto
    resumen_conceptos = {}
    for g in gastos_mes:
        concepto_nombre = g.concepto_gasto.nombre if g.concepto_gasto else 'Sin concepto'
        if concepto_nombre not in resumen_conceptos:
            resumen_conceptos[concepto_nombre] = {
                'nombre': concepto_nombre,
                'color': '#6366f1',
                'total': 0,
                'cantidad': 0
            }
        resumen_conceptos[concepto_nombre]['total'] += float(g.valor)
        resumen_conceptos[concepto_nombre]['cantidad'] += 1

    resumen_grupos = list(resumen_conceptos.values())
    # Assign colors
    colores = ['#2563eb', '#059669', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4', '#ec4899', '#84cc16']
    for i, g in enumerate(resumen_grupos):
        g['color'] = colores[i % len(colores)]
    resumen_grupos = sorted(
        resumen_grupos,
        key=lambda x: x['total'],
        reverse=True
    )

    resumen_items = {}
    for g in gastos_mes:
        item_nombre = (
            g.item_gasto.nombre if g.item_gasto
            else g.descripcion
            or 'Sin item'
        )
        if item_nombre not in resumen_items:
            resumen_items[item_nombre] = {
                'nombre': item_nombre,
                'total': 0,
                'cantidad': 0
            }
        resumen_items[item_nombre]['total'] += float(g.valor)
        resumen_items[item_nombre]['cantidad'] += 1

    resumen_items = sorted(
        resumen_items.values(),
        key=lambda x: x['total'],
        reverse=True
    )
    top_concepto = max(resumen_grupos, key=lambda x: x['total']) if resumen_grupos else None
    top_item = resumen_items[0] if resumen_items else None

    meses_previos = []
    if mes > 1:
        for m in range(1, mes):
            total_mes_prev = sum(float(g.valor or 0) for g in gastos_anteriores if g.fecha.month == m)
            cantidad_mes_prev = sum(1 for g in gastos_anteriores if g.fecha.month == m)
            meses_previos.append({
                'mes': m,
                'mes_nombre': MESES[m - 1],
                'total': total_mes_prev,
                'cantidad': cantidad_mes_prev
            })

    items_mes_actual = []
    for g in gastos_mes:
        items_mes_actual.append({
            'id': g.id,
            'fecha': g.fecha,
            'concepto': g.concepto_gasto.nombre if g.concepto_gasto else 'Sin concepto',
            'item': g.item_gasto.nombre if g.item_gasto else (g.descripcion or 'Sin item'),
            'responsable': g.responsable or '-',
            'tercero': g.tercero.nombre if g.tercero else '-',
            'valor': float(g.valor or 0),
            'medio': g.medio_pago.nombre if g.medio_pago else '-',
        })

    # Resumen por responsable
    resumen_responsables = {}
    for g in gastos_mes:
        resp = g.responsable or 'Sin asignar'
        if resp not in resumen_responsables:
            resumen_responsables[resp] = 0
        resumen_responsables[resp] += float(g.valor)

    # Tarjetas
    gastos_cards = []
    for g in gastos_mes:
        gastos_cards.append({
            'gasto': g,
        })

    return render_template('gastos/lista.html',
                           gastos_cards=gastos_cards,
                           anio=anio, mes=mes, meses=MESES,
                           conceptos=conceptos, items_catalogo=items_catalogo, medios=medios,
                           acum_anterior=float(acum_anterior),
                           gastos_anteriores=gastos_anteriores,
                           total_mes=total_mes,
                           promedio_mensual=promedio_mensual,
                           resumen_grupos=resumen_grupos,
                           resumen_items=resumen_items,
                           resumen_responsables=resumen_responsables,
                           meses_previos=meses_previos,
                           items_mes_actual=items_mes_actual,
                           top_concepto=top_concepto,
                           top_item=top_item)


@gastos_bp.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if request.method == 'POST':
        gasto = Gasto(
            fecha=datetime.strptime(request.form['fecha'], '%Y-%m-%d').date(),
            tercero_id=request.form.get('tercero_id') or None,
            concepto_gasto_id=request.form['concepto_gasto_id'],
            item_gasto_id=request.form.get('item_gasto_id') or None,
            descripcion=request.form.get('descripcion', '').strip(),
            valor=request.form['valor'],
            medio_pago_id=request.form.get('medio_pago_id') or None,
            fecha_pago=request.form.get('fecha_pago') or None,
            responsable=request.form.get('responsable', '').strip(),
            observaciones=request.form.get('observaciones', '').strip()
        )
        db.session.add(gasto)
        db.session.commit()
        flash('Gasto registrado.', 'success')
        return redirect(url_for('gastos.lista'))

    conceptos = ConceptoGasto.query.filter_by(activo=True).order_by(ConceptoGasto.nombre).all()
    items_catalogo = ItemGasto.query.filter_by(activo=True).order_by(ItemGasto.nombre).all()
    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    return render_template('gastos/form.html', gasto=None,
                           conceptos=conceptos, items_catalogo=items_catalogo, terceros=terceros, medios=medios)


@gastos_bp.route('/detalle/<int:id>')
def detalle(id):
    """Vista detalle completa de un gasto"""
    gasto = Gasto.query.get_or_404(id)
    return render_template('gastos/detalle.html', gasto=gasto)


@gastos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    gasto = Gasto.query.get_or_404(id)
    if request.method == 'POST':
        gasto.fecha = datetime.strptime(request.form['fecha'], '%Y-%m-%d').date()
        gasto.tercero_id = request.form.get('tercero_id') or None
        gasto.concepto_gasto_id = request.form['concepto_gasto_id']
        gasto.item_gasto_id = request.form.get('item_gasto_id') or None
        gasto.descripcion = request.form.get('descripcion', '').strip()
        gasto.valor = request.form['valor']
        gasto.medio_pago_id = request.form.get('medio_pago_id') or None
        gasto.fecha_pago = request.form.get('fecha_pago') or None
        gasto.responsable = request.form.get('responsable', '').strip()
        gasto.observaciones = request.form.get('observaciones', '').strip()
        db.session.commit()
        flash('Gasto actualizado.', 'success')
        return redirect(url_for('gastos.lista'))

    conceptos = ConceptoGasto.query.filter_by(activo=True).order_by(ConceptoGasto.nombre).all()
    items_catalogo = ItemGasto.query.filter_by(activo=True).order_by(ItemGasto.nombre).all()
    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    return render_template('gastos/form.html', gasto=gasto,
                           conceptos=conceptos, items_catalogo=items_catalogo, terceros=terceros, medios=medios)
