from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import and_, extract, func, or_

from app import db
from app.models import AbonoCompra, Compra, ConceptoCompra, MedioPago, ProductoCompra, Tercero


compras_bp = Blueprint('compras', __name__, url_prefix='/compras')

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
ZERO = Decimal('0.00')


def _date_or_none(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _decimal_or_zero(value):
    if value is None:
        return ZERO
    raw = str(value).strip().replace(',', '')
    if not raw:
        return ZERO
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return ZERO


def _money(value):
    return '{:,.0f}'.format(float(_decimal_or_zero(value)))


def _safe_next_url(value):
    value = (value or '').strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None
    if not value.startswith('/'):
        return None
    return value


def _catalogos_compra():
    return {
        'conceptos': ConceptoCompra.query.filter_by(activo=True).order_by(ConceptoCompra.nombre).all(),
        'productos': ProductoCompra.query.filter_by(activo=True).order_by(ProductoCompra.nombre).all(),
        'terceros': Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all(),
        'medios': MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all(),
    }


def _abonos_por_compra(compra_ids):
    if not compra_ids:
        return {}

    rows = db.session.query(
        AbonoCompra.compra_id,
        func.coalesce(func.sum(AbonoCompra.valor_abono), 0),
        func.max(AbonoCompra.fecha_pago)
    ).filter(
        AbonoCompra.compra_id.in_(compra_ids)
    ).group_by(
        AbonoCompra.compra_id
    ).all()

    return {
        compra_id: {
            'abonado': _decimal_or_zero(total_abonado),
            'ultima_fecha': ultima_fecha,
        }
        for compra_id, total_abonado, ultima_fecha in rows
    }


def _totales_compra(compra, resumen_abonos=None):
    resumen_abonos = resumen_abonos or {}
    valor_total = _decimal_or_zero(compra.valor)
    resumen = resumen_abonos.get(compra.id) or {}
    abonado_movimientos = _decimal_or_zero(resumen.get('abonado'))
    tiene_movimientos = abonado_movimientos > ZERO

    if tiene_movimientos:
        abonado = abonado_movimientos
        ultima_fecha = resumen.get('ultima_fecha')
        fuente = 'abonos'
    elif compra.estado == 'pagado':
        abonado = valor_total
        ultima_fecha = compra.fecha_pago
        fuente = 'legacy'
    else:
        abonado = ZERO
        ultima_fecha = None
        fuente = 'ninguna'

    saldo = valor_total - abonado
    if saldo < ZERO:
        saldo = ZERO

    if saldo == ZERO and valor_total > ZERO:
        estado = 'pagado'
    elif abonado > ZERO:
        estado = 'parcial'
    else:
        estado = 'pendiente'

    return {
        'valor_total': valor_total,
        'abonado': abonado,
        'saldo': saldo,
        'estado': estado,
        'ultima_fecha': ultima_fecha,
        'fuente': fuente,
    }


def _sincronizar_snapshot_compra(compra, totales, medio_pago_id=None):
    compra.estado = totales['estado']
    if totales['abonado'] > ZERO:
        compra.fecha_pago = totales['ultima_fecha']
        if medio_pago_id:
            compra.medio_pago_id = medio_pago_id
    elif totales['estado'] == 'pendiente':
        compra.fecha_pago = None
        compra.medio_pago_id = None


def _registrar_abono_compra(compra, valor_abono, fecha_pago, medio_pago_id=None, descripcion=None):
    abono = AbonoCompra(
        compra_id=compra.id,
        valor_abono=valor_abono,
        fecha_pago=fecha_pago,
        medio_pago_id=medio_pago_id or None,
        descripcion=(descripcion or '').strip() or None,
    )
    db.session.add(abono)
    db.session.flush()
    totales = _totales_compra(compra, _abonos_por_compra([compra.id]))
    _sincronizar_snapshot_compra(compra, totales, medio_pago_id=medio_pago_id)
    return abono, totales


def _compra_descripcion_corta(compra):
    if compra.producto_compra and compra.producto_compra.nombre:
        return compra.producto_compra.nombre
    return compra.descripcion or 'Registro sin descripcion'


@compras_bp.route('/')
@compras_bp.route('/<int:anio>')
@compras_bp.route('/<int:anio>/<int:mes>')
def lista(anio=None, mes=None):
    if anio is None:
        anio = date.today().year
    if mes is None:
        mes = date.today().month

    catalogos = _catalogos_compra()

    compras_mes = Compra.query.filter(
        extract('year', Compra.fecha) == anio,
        extract('month', Compra.fecha) == mes
    ).order_by(
        Compra.fecha.desc(),
        Compra.id.desc()
    ).all()

    compras_previas = Compra.query.filter(
        or_(
            extract('year', Compra.fecha) < anio,
            and_(
                extract('year', Compra.fecha) == anio,
                extract('month', Compra.fecha) < mes
            )
        )
    ).order_by(
        Compra.fecha.desc(),
        Compra.id.desc()
    ).all()

    compra_ids = [compra.id for compra in compras_mes + compras_previas]
    resumen_abonos = _abonos_por_compra(compra_ids)

    compras_pagadas_anteriores = []
    pendientes_anteriores = []
    acum_pagado_anterior = ZERO
    total_deuda_anterior = ZERO

    for compra in compras_previas:
        totales = _totales_compra(compra, resumen_abonos)
        if totales['abonado'] > ZERO:
            acum_pagado_anterior += totales['abonado']
            compras_pagadas_anteriores.append({
                'compra': compra,
                'estado': totales['estado'],
                'abonado': float(totales['abonado']),
                'saldo': float(totales['saldo']),
                'ultima_fecha': totales['ultima_fecha'],
            })
        if totales['saldo'] > ZERO:
            total_deuda_anterior += totales['saldo']
            pendientes_anteriores.append({
                'compra': compra,
                'mes_nombre': MESES[compra.fecha.month - 1],
                'anio': compra.fecha.year,
                'valor': float(totales['saldo']),
                'estado': totales['estado'],
            })

    pagado_mes = ZERO
    pendiente_mes = ZERO
    total_mes = ZERO
    resumen_conceptos = {}
    resumen_items = {}
    items_mes_actual = []
    compras_cards = []

    for compra in compras_mes:
        totales = _totales_compra(compra, resumen_abonos)
        valor_total = totales['valor_total']
        pagado_mes += totales['abonado']
        pendiente_mes += totales['saldo']
        total_mes += valor_total

        concepto_nombre = compra.concepto_compra.nombre if compra.concepto_compra else 'Sin concepto'
        resumen_conceptos.setdefault(concepto_nombre, {
            'nombre': concepto_nombre,
            'color': '#6366f1',
            'pagado': 0,
            'pendiente': 0,
            'cantidad': 0,
        })
        resumen_conceptos[concepto_nombre]['cantidad'] += 1
        resumen_conceptos[concepto_nombre]['pagado'] += float(totales['abonado'])
        resumen_conceptos[concepto_nombre]['pendiente'] += float(totales['saldo'])

        item_nombre = _compra_descripcion_corta(compra)
        resumen_items.setdefault(item_nombre, {
            'nombre': item_nombre,
            'pagado': 0,
            'pendiente': 0,
            'cantidad': 0,
            'total': 0,
        })
        resumen_items[item_nombre]['cantidad'] += 1
        resumen_items[item_nombre]['pagado'] += float(totales['abonado'])
        resumen_items[item_nombre]['pendiente'] += float(totales['saldo'])
        resumen_items[item_nombre]['total'] += float(valor_total)

        items_mes_actual.append({
            'id': compra.id,
            'fecha': compra.fecha,
            'concepto': concepto_nombre,
            'item': item_nombre,
            'proveedor': compra.tercero.nombre if compra.tercero else '-',
            'estado': totales['estado'],
            'valor': float(valor_total),
            'abonado': float(totales['abonado']),
            'saldo': float(totales['saldo']),
            'medio': compra.medio_pago.nombre if compra.medio_pago else '-',
        })

        compras_cards.append({
            'compra': compra,
            'estado': totales['estado'],
            'abonado': float(totales['abonado']),
            'saldo': float(totales['saldo']),
            'ultima_fecha': totales['ultima_fecha'],
            'fuente': totales['fuente'],
        })

    colores = ['#2563eb', '#059669', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4', '#ec4899']
    resumen_grupos = list(resumen_conceptos.values())
    for index, grupo in enumerate(resumen_grupos):
        grupo['color'] = colores[index % len(colores)]
    resumen_grupos = sorted(
        resumen_grupos,
        key=lambda item: item['pagado'] + item['pendiente'],
        reverse=True
    )
    resumen_items = sorted(
        resumen_items.values(),
        key=lambda item: item['total'],
        reverse=True
    )
    top_concepto = resumen_grupos[0] if resumen_grupos else None
    top_item = resumen_items[0] if resumen_items else None

    return render_template(
        'compras/lista_v2.html',
        compras_cards=compras_cards,
        compras_pagadas_anteriores=compras_pagadas_anteriores,
        pendientes_anteriores=pendientes_anteriores,
        anio=anio,
        mes=mes,
        meses=MESES,
        acum_pagado_anterior=float(acum_pagado_anterior),
        pagado_mes=float(pagado_mes),
        pendiente_mes=float(pendiente_mes),
        total_mes=float(total_mes),
        total_deuda_anterior=float(total_deuda_anterior),
        resumen_grupos=resumen_grupos,
        resumen_items=resumen_items,
        items_mes_actual=items_mes_actual,
        top_concepto=top_concepto,
        top_item=top_item,
        **catalogos,
    )


@compras_bp.route('/nueva', methods=['GET', 'POST'])
def nueva():
    catalogos = _catalogos_compra()

    if request.method == 'POST':
        valor = _decimal_or_zero(request.form.get('valor'))
        situacion_pago = request.form.get('situacion_pago', 'pendiente')
        valor_abono_inicial = _decimal_or_zero(request.form.get('valor_abono_inicial'))
        fecha_pago = _date_or_none(request.form.get('fecha_pago'))

        if valor <= ZERO:
            flash('El valor del registro debe ser mayor a cero.', 'danger')
            return render_template('compras/form_v2.html', compra=None, **catalogos)

        if situacion_pago == 'pagado' and valor_abono_inicial <= ZERO:
            valor_abono_inicial = valor
        elif situacion_pago == 'pendiente':
            valor_abono_inicial = ZERO

        if valor_abono_inicial > valor:
            flash('El abono inicial no puede superar el valor total del registro.', 'danger')
            return render_template('compras/form_v2.html', compra=None, **catalogos)

        if situacion_pago == 'parcial' and valor_abono_inicial <= ZERO:
            flash('Si la situacion inicial es parcial, indique el valor abonado.', 'danger')
            return render_template('compras/form_v2.html', compra=None, **catalogos)

        if situacion_pago in ('parcial', 'pagado') and not fecha_pago:
            flash('Debe indicar una fecha de pago valida para el abono inicial.', 'danger')
            return render_template('compras/form_v2.html', compra=None, **catalogos)

        compra = Compra(
            fecha=_date_or_none(request.form.get('fecha')) or date.today(),
            tercero_id=request.form.get('tercero_id') or None,
            concepto_compra_id=request.form['concepto_compra_id'],
            producto_compra_id=request.form.get('producto_compra_id') or None,
            descripcion=(request.form.get('descripcion') or '').strip(),
            valor=valor,
            estado='pendiente',
            observaciones=(request.form.get('observaciones') or '').strip() or None,
        )
        db.session.add(compra)
        db.session.flush()

        if valor_abono_inicial > ZERO:
            _registrar_abono_compra(
                compra,
                valor_abono_inicial,
                fecha_pago,
                medio_pago_id=request.form.get('medio_pago_id') or None,
                descripcion=request.form.get('descripcion_pago') or request.form.get('observaciones'),
            )

        if valor_abono_inicial == ZERO:
            _sincronizar_snapshot_compra(compra, _totales_compra(compra))

        db.session.commit()
        flash('Registro guardado en Compras y Gastos.', 'success')
        return redirect(url_for('compras.lista', anio=compra.fecha.year, mes=compra.fecha.month))

    return render_template('compras/form_v2.html', compra=None, **catalogos)


@compras_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    compra = Compra.query.get_or_404(id)
    catalogos = _catalogos_compra()
    resumen_abonos = _abonos_por_compra([compra.id])
    totales_actuales = _totales_compra(compra, resumen_abonos)

    if request.method == 'POST':
        nuevo_valor = _decimal_or_zero(request.form.get('valor'))
        if nuevo_valor <= ZERO:
            flash('El valor del registro debe ser mayor a cero.', 'danger')
            return render_template(
                'compras/form_v2.html',
                compra=compra,
                totales_actuales=totales_actuales,
                **catalogos,
            )

        if nuevo_valor < totales_actuales['abonado']:
            flash(
                f'No puede dejar el valor por debajo de lo ya abonado (${_money(totales_actuales["abonado"])}).',
                'danger'
            )
            return render_template(
                'compras/form_v2.html',
                compra=compra,
                totales_actuales=totales_actuales,
                **catalogos,
            )

        compra.fecha = _date_or_none(request.form.get('fecha')) or compra.fecha
        compra.tercero_id = request.form.get('tercero_id') or None
        compra.concepto_compra_id = request.form['concepto_compra_id']
        compra.producto_compra_id = request.form.get('producto_compra_id') or None
        compra.descripcion = (request.form.get('descripcion') or '').strip()
        compra.valor = nuevo_valor
        compra.observaciones = (request.form.get('observaciones') or '').strip() or None

        nuevos_totales = _totales_compra(compra, resumen_abonos)
        _sincronizar_snapshot_compra(compra, nuevos_totales, medio_pago_id=compra.medio_pago_id)

        db.session.commit()
        flash('Registro actualizado en Compras y Gastos.', 'success')
        return redirect(url_for('compras.detalle', id=compra.id))

    return render_template(
        'compras/form_v2.html',
        compra=compra,
        totales_actuales=totales_actuales,
        **catalogos,
    )


@compras_bp.route('/detalle/<int:id>')
def detalle(id):
    compra = Compra.query.get_or_404(id)
    resumen_abonos = _abonos_por_compra([compra.id])
    totales = _totales_compra(compra, resumen_abonos)
    abonos = compra.abonos.order_by(AbonoCompra.fecha_pago.desc(), AbonoCompra.id.desc()).all()
    legacy_pago = not abonos and compra.estado == 'pagado'
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()

    return render_template(
        'compras/detalle_v2.html',
        compra=compra,
        totales=totales,
        abonos=abonos,
        legacy_pago=legacy_pago,
        medios=medios,
        fecha_hoy=date.today(),
    )


@compras_bp.route('/<int:id>/abonar', methods=['POST'])
@compras_bp.route('/<int:id>/pagar', methods=['POST'])
def registrar_abono(id):
    compra = Compra.query.get_or_404(id)
    resumen_abonos = _abonos_por_compra([compra.id])
    totales_antes = _totales_compra(compra, resumen_abonos)
    fecha_pago = _date_or_none(request.form.get('fecha_pago'))

    if totales_antes['saldo'] <= ZERO:
        flash('Ese registro ya no tiene saldo pendiente.', 'info')
        destino = _safe_next_url(request.form.get('next'))
        return redirect(destino or url_for('compras.detalle', id=compra.id))

    valor_abono = _decimal_or_zero(request.form.get('valor_abono'))
    if valor_abono <= ZERO:
        valor_abono = totales_antes['saldo']

    if valor_abono > totales_antes['saldo']:
        flash(
            f'El abono no puede superar el saldo pendiente (${_money(totales_antes["saldo"])}).',
            'danger'
        )
        destino = _safe_next_url(request.form.get('next'))
        return redirect(destino or url_for('compras.detalle', id=compra.id))

    if not fecha_pago:
        flash('Debe indicar una fecha de pago valida para registrar el abono.', 'danger')
        destino = _safe_next_url(request.form.get('next'))
        return redirect(destino or url_for('compras.detalle', id=compra.id))

    _, totales_despues = _registrar_abono_compra(
        compra,
        valor_abono,
        fecha_pago,
        medio_pago_id=request.form.get('medio_pago_id') or None,
        descripcion=request.form.get('descripcion'),
    )
    db.session.commit()

    flash(
        f'Abono registrado. Saldo pendiente: ${_money(totales_despues["saldo"])}.',
        'success'
    )
    destino = _safe_next_url(request.form.get('next'))
    return redirect(destino or url_for('compras.detalle', id=compra.id))


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

    existente = ProductoCompra.query.filter_by(
        nombre=nombre,
        concepto_compra_id=concepto_compra_id
    ).first()
    if existente:
        return jsonify({'error': f'Ya existe un item "{nombre}" en ese concepto'}), 400

    item = ProductoCompra(nombre=nombre, concepto_compra_id=int(concepto_compra_id))
    db.session.add(item)
    db.session.commit()
    return jsonify({
        'id': item.id,
        'nombre': item.nombre,
        'concepto_compra_id': item.concepto_compra_id,
    })
