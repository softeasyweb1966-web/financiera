from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models import (
    Obligacion, PagoObligacion, Refinanciacion, AbonoCapitalObligacion,
    Tercero, Concepto, Categoria, MedioPago
)
from app.conceptos_estado import cargar_historial_conceptos, concepto_activo_en_periodo
from calendar import monthrange
from datetime import date, datetime, timedelta
from sqlalchemy import func
import math

obligaciones_bp = Blueprint('obligaciones', __name__, url_prefix='/obligaciones')

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

MODALIDADES = [
    ('bancario_cuota_fija', 'Bancario cuota fija'),
    ('solo_interes', 'Solo interés mensual (capital al final)'),
    ('cadena', 'Cadena (cuota fija entre personas)'),
    ('pago_total_pactado', 'Pago total pactado'),
    ('prestamo_corto_plazo', 'Préstamo a días (corto plazo)'),
]

MODALIDAD_LABELS = dict(MODALIDADES)


def _conceptos_activos_categoria(nombre_categoria, anio, mes):
    cat = Categoria.query.filter_by(nombre=nombre_categoria).first()
    conceptos = Concepto.query.filter_by(categoria_id=cat.id).order_by(Concepto.nombre).all() if cat else []
    historiales = cargar_historial_conceptos([c.id for c in conceptos])
    return [
        c for c in conceptos
        if concepto_activo_en_periodo(c, anio, mes, historiales.get(c.id, []))
    ]


def _valor_estimado_obligacion(obligacion, ultimo_pago=None):
    if obligacion.valor_cuota_fija:
        return float(obligacion.valor_cuota_fija)
    if obligacion.valor_cuota_capital is not None or obligacion.valor_cuota_interes is not None:
        return float(obligacion.valor_cuota_capital or 0) + float(obligacion.valor_cuota_interes or 0)
    if obligacion.interes_mensual_calculado:
        return obligacion.interes_mensual_calculado
    if obligacion.cuota_francesa_calculada:
        return obligacion.cuota_francesa_calculada
    if ultimo_pago and ultimo_pago.valor_pagado:
        return float(ultimo_pago.valor_pagado)
    return 0


def _rango_mes(anio, mes):
    ultimo_dia = monthrange(anio, mes)[1]
    return date(anio, mes, 1), date(anio, mes, ultimo_dia)


def _fechas_programadas_obligacion(obligacion, anio, mes):
    inicio_mes, fin_mes = _rango_mes(anio, mes)

    if obligacion.modalidad == 'pago_total_pactado':
        if obligacion.fecha_vencimiento and inicio_mes <= obligacion.fecha_vencimiento <= fin_mes:
            return [obligacion.fecha_vencimiento]
        return []

    if obligacion.modalidad == 'cadena' and obligacion.fecha_inicio:
        fecha_inicio = obligacion.fecha_inicio
        fecha_final = obligacion.fecha_vencimiento
        if fecha_final and fecha_final < inicio_mes:
            return []
        if fecha_inicio > fin_mes:
            return []

        frecuencia = (obligacion.frecuencia_pago or 'mensual').lower()
        if frecuencia == 'quincenal':
            fechas = []
            actual = fecha_inicio
            while actual < inicio_mes:
                actual += timedelta(days=15)
            while actual <= fin_mes and (not fecha_final or actual <= fecha_final):
                fechas.append(actual)
                actual += timedelta(days=15)
            return fechas

        dia = min(fecha_inicio.day, fin_mes.day)
        fecha_mes = date(anio, mes, dia)
        if fecha_mes < fecha_inicio:
            return []
        if fecha_final and fecha_mes > fecha_final:
            return []
        return [fecha_mes]

    if obligacion.dia_limite_pago:
        try:
            return [date(anio, mes, min(obligacion.dia_limite_pago, fin_mes.day))]
        except ValueError:
            return []
    return []


def _siguiente_fecha_programada(obligacion, desde_fecha):
    if obligacion.modalidad == 'pago_total_pactado':
        if obligacion.fecha_vencimiento and obligacion.fecha_vencimiento > desde_fecha:
            return obligacion.fecha_vencimiento
        return None

    if obligacion.modalidad == 'cadena' and obligacion.fecha_inicio:
        fecha_final = obligacion.fecha_vencimiento
        frecuencia = (obligacion.frecuencia_pago or 'mensual').lower()

        if frecuencia == 'quincenal':
            actual = obligacion.fecha_inicio
            while actual <= desde_fecha:
                actual += timedelta(days=15)
            if fecha_final and actual > fecha_final:
                return None
            return actual

        actual = obligacion.fecha_inicio
        while actual <= desde_fecha:
            siguiente_mes = actual.month + 1
            siguiente_anio = actual.year
            if siguiente_mes > 12:
                siguiente_mes = 1
                siguiente_anio += 1
            actual = date(
                siguiente_anio,
                siguiente_mes,
                min(obligacion.fecha_inicio.day, monthrange(siguiente_anio, siguiente_mes)[1])
            )
        if fecha_final and actual > fecha_final:
            return None
        return actual

    if obligacion.dia_limite_pago:
        candidato = date(
            desde_fecha.year,
            desde_fecha.month,
            min(obligacion.dia_limite_pago, monthrange(desde_fecha.year, desde_fecha.month)[1])
        )
        if candidato <= desde_fecha:
            siguiente_mes = desde_fecha.month + 1
            siguiente_anio = desde_fecha.year
            if siguiente_mes > 12:
                siguiente_mes = 1
                siguiente_anio += 1
            candidato = date(
                siguiente_anio,
                siguiente_mes,
                min(obligacion.dia_limite_pago, monthrange(siguiente_anio, siguiente_mes)[1])
            )
        return candidato
    return None


def _valor_programado_mes_obligacion(obligacion, anio, mes, ultimo_pago=None):
    base = _valor_estimado_obligacion(obligacion, ultimo_pago)
    if base <= 0:
        return 0

    if obligacion.modalidad == 'pago_total_pactado':
        return base if _fechas_programadas_obligacion(obligacion, anio, mes) else 0

    if obligacion.modalidad == 'cadena':
        cuotas_mes = len(_fechas_programadas_obligacion(obligacion, anio, mes))
        if cuotas_mes <= 0:
            return 0
        return base * cuotas_mes

    return base


def _saldo_pendiente_total_obligacion(obligacion, capital_pagado=0):
    if obligacion.saldo_actual is not None:
        return float(obligacion.saldo_actual)
    if obligacion.capital_inicial is not None:
        return max(float(obligacion.capital_inicial) - float(capital_pagado or 0), 0)
    if obligacion.valor_cuota_fija is not None and obligacion.cuotas_pendientes is not None:
        return max(float(obligacion.valor_cuota_fija) * max(obligacion.cuotas_pendientes, 0), 0)
    return 0


def _fecha_ultimo_pago_estimada(obligacion, fecha_base):
    if obligacion.fecha_vencimiento:
        return obligacion.fecha_vencimiento

    cuotas_pendientes = obligacion.cuotas_pendientes
    if not fecha_base or cuotas_pendientes is None or cuotas_pendientes <= 0:
        return None

    fecha_estimada = fecha_base
    for _ in range(max(cuotas_pendientes - 1, 0)):
        fecha_estimada = _siguiente_fecha_programada(obligacion, fecha_estimada)
        if not fecha_estimada:
            break
    return fecha_estimada


def _cuota_con_tasa(saldo, tasa_mensual, cuotas_pendientes):
    if saldo <= 0 or tasa_mensual <= 0 or cuotas_pendientes <= 0:
        return 0
    return saldo * tasa_mensual / (1 - (1 + tasa_mensual) ** (-cuotas_pendientes))


def _plazo_con_tasa(saldo, tasa_mensual, cuota_objetivo):
    if saldo <= 0:
        return 0
    if tasa_mensual <= 0:
        return max(1, math.ceil(saldo / cuota_objetivo)) if cuota_objetivo > 0 else 0
    interes_periodo = saldo * tasa_mensual
    if cuota_objetivo <= interes_periodo:
        return None
    plazo = math.log(cuota_objetivo / (cuota_objetivo - interes_periodo)) / math.log(1 + tasa_mensual)
    return max(1, math.ceil(plazo))


def _float_or_none(valor):
    try:
        if valor in (None, ''):
            return None
        return float(valor)
    except (TypeError, ValueError):
        return None


def _validar_desglose_cuota_form(requiere_desglose, valor_cuota_fija, valor_cuota_capital, valor_cuota_interes):
    total = _float_or_none(valor_cuota_fija)
    capital = _float_or_none(valor_cuota_capital)
    interes = _float_or_none(valor_cuota_interes)

    if not requiere_desglose and capital is None and interes is None:
        return None

    if capital is None or interes is None:
        return 'Si discrimina la cuota, debe diligenciar tanto capital como interes.'

    suma_componentes = (capital or 0) + (interes or 0)
    if total is None:
        return 'Para discriminar la cuota, primero debe registrar el valor total de la cuota.'

    if abs(suma_componentes - total) > 1:
        return 'La suma de capital e interes debe coincidir con el valor de la cuota.'

    return None


@obligaciones_bp.route('/')
def lista():
    obligaciones = Obligacion.query.filter_by(activo=True).order_by(Obligacion.dia_limite_pago).all()
    anio = request.args.get('anio', date.today().year, type=int)
    return render_template('obligaciones/lista.html',
                           obligaciones=obligaciones, anio=anio, meses=MESES)


@obligaciones_bp.route('/nueva', methods=['GET', 'POST'])
def nueva():
    if request.method == 'POST':
        tiene_desglose_cuota = any(
            _float_or_none(request.form.get(campo)) is not None
            for campo in ('valor_cuota_capital', 'valor_cuota_interes')
        )
        requiere_desglose_pago = request.form.get('requiere_desglose_pago') == 'on' or tiene_desglose_cuota
        error_desglose = _validar_desglose_cuota_form(
            requiere_desglose_pago,
            request.form.get('valor_cuota_fija'),
            request.form.get('valor_cuota_capital'),
            request.form.get('valor_cuota_interes'),
        )
        if error_desglose:
            flash(error_desglose, 'danger')
            return redirect(request.url)

        obligacion = Obligacion(
            tercero_id=request.form['tercero_id'],
            concepto_id=request.form['concepto_id'],
            modalidad=request.form['modalidad'],
            capital_inicial=request.form.get('capital_inicial') or None,
            saldo_actual=request.form.get('saldo_actual') or request.form.get('capital_inicial') or None,
            tasa_interes_mensual=request.form.get('tasa_interes_mensual') or None,
            plazo_meses=request.form.get('plazo_meses') or None,
            plazo_dias=request.form.get('plazo_dias') or None,
            cuotas_totales=request.form.get('cuotas_totales') or None,
            valor_cuota_fija=request.form.get('valor_cuota_fija') or None,
            valor_cuota_capital=request.form.get('valor_cuota_capital') or None,
            valor_cuota_interes=request.form.get('valor_cuota_interes') or None,
            fecha_inicio=request.form.get('fecha_inicio') or None,
            fecha_vencimiento=request.form.get('fecha_vencimiento') or None,
            fecha_recibe=request.form.get('fecha_recibe') or None,
            titular=request.form.get('titular', '').strip(),
            referencia=request.form.get('referencia', '').strip(),
            frecuencia_pago=request.form.get('frecuencia_pago', 'mensual'),
            requiere_desglose_pago=requiere_desglose_pago,
            dia_limite_pago=request.form.get('dia_limite_pago') or None,
            estado=request.form.get('estado', 'activo'),
            observaciones=request.form.get('observaciones', '').strip()
        )
        db.session.add(obligacion)
        db.session.commit()
        flash('Obligación creada correctamente.', 'success')
        return redirect(url_for('obligaciones.lista'))

    conceptos = _conceptos_activos_categoria('Obligaciones Bancarias', date.today().year, date.today().month)
    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).all()
    return render_template('obligaciones/form.html', obligacion=None,
                           conceptos=conceptos, terceros=terceros,
                           modalidades=MODALIDADES, medios=medios)


@obligaciones_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    obligacion = Obligacion.query.get_or_404(id)
    if request.method == 'POST':
        tiene_desglose_cuota = any(
            _float_or_none(request.form.get(campo)) is not None
            for campo in ('valor_cuota_capital', 'valor_cuota_interes')
        )
        requiere_desglose_pago = request.form.get('requiere_desglose_pago') == 'on' or tiene_desglose_cuota
        error_desglose = _validar_desglose_cuota_form(
            requiere_desglose_pago,
            request.form.get('valor_cuota_fija'),
            request.form.get('valor_cuota_capital'),
            request.form.get('valor_cuota_interes'),
        )
        if error_desglose:
            flash(error_desglose, 'danger')
            return redirect(request.url)

        obligacion.tercero_id = request.form['tercero_id']
        obligacion.concepto_id = request.form['concepto_id']
        obligacion.modalidad = request.form['modalidad']
        obligacion.capital_inicial = request.form.get('capital_inicial') or None
        obligacion.saldo_actual = request.form.get('saldo_actual') or None
        obligacion.tasa_interes_mensual = request.form.get('tasa_interes_mensual') or None
        obligacion.plazo_meses = request.form.get('plazo_meses') or None
        obligacion.plazo_dias = request.form.get('plazo_dias') or None
        obligacion.cuotas_totales = request.form.get('cuotas_totales') or None
        obligacion.valor_cuota_fija = request.form.get('valor_cuota_fija') or None
        obligacion.valor_cuota_capital = request.form.get('valor_cuota_capital') or None
        obligacion.valor_cuota_interes = request.form.get('valor_cuota_interes') or None
        obligacion.fecha_inicio = request.form.get('fecha_inicio') or None
        obligacion.fecha_vencimiento = request.form.get('fecha_vencimiento') or None
        obligacion.fecha_recibe = request.form.get('fecha_recibe') or None
        obligacion.titular = request.form.get('titular', '').strip()
        obligacion.referencia = request.form.get('referencia', '').strip()
        obligacion.frecuencia_pago = request.form.get('frecuencia_pago', 'mensual')
        obligacion.requiere_desglose_pago = requiere_desglose_pago
        obligacion.dia_limite_pago = request.form.get('dia_limite_pago') or None
        obligacion.estado = request.form.get('estado', 'activo')
        obligacion.observaciones = request.form.get('observaciones', '').strip()
        db.session.commit()
        flash('Obligación actualizada.', 'success')
        return redirect(url_for('obligaciones.lista'))

    conceptos = _conceptos_activos_categoria('Obligaciones Bancarias', date.today().year, date.today().month)
    if obligacion.concepto and not any(c.id == obligacion.concepto_id for c in conceptos):
        conceptos = sorted(conceptos + [obligacion.concepto], key=lambda item: item.nombre.lower())
    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).all()
    return render_template('obligaciones/form.html', obligacion=obligacion,
                           conceptos=conceptos, terceros=terceros,
                           modalidades=MODALIDADES, medios=medios)


@obligaciones_bp.route('/pagos')
@obligaciones_bp.route('/pagos/<int:anio>')
@obligaciones_bp.route('/pagos/<int:anio>/<int:mes>')
def pagos(anio=None, mes=None):
    if anio is None:
        anio = date.today().year
    if mes is None:
        mes = date.today().month

    hoy = date.today()
    obligaciones = Obligacion.query.filter_by(activo=True).order_by(Obligacion.dia_limite_pago).all()
    historiales = cargar_historial_conceptos([o.concepto_id for o in obligaciones])
    obligaciones = [
        o for o in obligaciones
        if concepto_activo_en_periodo(o.concepto, anio, mes, historiales.get(o.concepto_id, []))
    ]
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    obligacion_ids = [o.id for o in obligaciones]

    # Pagos del mes seleccionado
    pagos_mes = PagoObligacion.query.filter(
        PagoObligacion.anio == anio,
        PagoObligacion.mes == mes,
        PagoObligacion.obligacion_id.in_(obligacion_ids)
    ).all() if obligacion_ids else []
    pagos_dict = {p.obligacion_id: p for p in pagos_mes}

    ultimos_pagos_dict = {}
    if obligacion_ids:
        pagos_historicos = PagoObligacion.query.filter(
            PagoObligacion.obligacion_id.in_(obligacion_ids),
            PagoObligacion.valor_pagado.isnot(None),
            db.or_(
                PagoObligacion.anio < anio,
                db.and_(PagoObligacion.anio == anio, PagoObligacion.mes <= mes)
            )
        ).order_by(
            PagoObligacion.obligacion_id,
            PagoObligacion.anio.desc(),
            PagoObligacion.mes.desc(),
            PagoObligacion.id.desc()
        ).all()

        for pago_historico in pagos_historicos:
            if pago_historico.obligacion_id not in ultimos_pagos_dict:
                ultimos_pagos_dict[pago_historico.obligacion_id] = pago_historico

    totales_pago_dict = {}
    if obligacion_ids:
        totales_pago_rows = db.session.query(
            PagoObligacion.obligacion_id,
            func.coalesce(func.sum(PagoObligacion.componente_capital), 0).label('capital_pagado'),
            func.coalesce(func.sum(PagoObligacion.componente_interes), 0).label('interes_pagado')
        ).filter(
            PagoObligacion.obligacion_id.in_(obligacion_ids),
            PagoObligacion.estado.in_(['pagado', 'parcial'])
        ).group_by(PagoObligacion.obligacion_id).all()

        totales_pago_dict = {
            obligacion_id: {
                'capital_pagado': float(capital_pagado or 0),
                'interes_pagado': float(interes_pagado or 0),
            }
            for obligacion_id, capital_pagado, interes_pagado in totales_pago_rows
        }

    # Pendientes de meses anteriores
    pendientes_anteriores = []
    total_deuda_anterior = 0
    for o in obligaciones:
        deudas = PagoObligacion.query.filter(
            PagoObligacion.obligacion_id == o.id,
            PagoObligacion.estado == 'pendiente',
            db.or_(
                PagoObligacion.anio < anio,
                db.and_(PagoObligacion.anio == anio, PagoObligacion.mes < mes)
            )
        ).order_by(PagoObligacion.anio, PagoObligacion.mes).all()
        for d in deudas:
            cuota_base = _valor_programado_mes_obligacion(o, d.anio, d.mes, ultimos_pagos_dict.get(o.id))
            valor_deuda = float(d.valor_causado or d.valor_pagado or cuota_base or 0)
            total_deuda_anterior += valor_deuda
            pendientes_anteriores.append({
                'obligacion': o,
                'pago': d,
                'mes_nombre': MESES[d.mes - 1],
                'anio': d.anio,
                'valor_deuda': valor_deuda
            })

    # Acumulado pagado meses anteriores del año
    acum_pagado_anterior = db.session.query(
        func.coalesce(func.sum(PagoObligacion.valor_pagado), 0)
    ).filter(
        PagoObligacion.obligacion_id.in_(obligacion_ids),
        PagoObligacion.anio == anio,
        PagoObligacion.mes < mes,
        PagoObligacion.estado.in_(['pagado', 'parcial'])
    ).scalar() if obligacion_ids else 0

    acum_por_obligacion_rows = db.session.query(
        PagoObligacion.obligacion_id,
        func.coalesce(func.sum(PagoObligacion.valor_pagado), 0).label('total')
    ).filter(
        PagoObligacion.obligacion_id.in_(obligacion_ids),
        PagoObligacion.anio == anio,
        PagoObligacion.mes < mes,
        PagoObligacion.estado.in_(['pagado', 'parcial'])
    ).group_by(PagoObligacion.obligacion_id).all() if obligacion_ids else []

    acum_obligaciones_detalle = []
    for obligacion_id, total in acum_por_obligacion_rows:
        obligacion = next((o for o in obligaciones if o.id == obligacion_id), None)
        if obligacion and float(total or 0) > 0:
            acum_obligaciones_detalle.append({
                'obligacion': obligacion,
                'total': float(total)
            })

    acum_obligaciones_detalle.sort(key=lambda item: item['total'], reverse=True)

    # Pagado en el mes actual
    pagado_mes_actual = db.session.query(
        func.coalesce(func.sum(PagoObligacion.valor_pagado), 0)
    ).filter(
        PagoObligacion.obligacion_id.in_(obligacion_ids),
        PagoObligacion.anio == anio,
        PagoObligacion.mes == mes,
        PagoObligacion.estado.in_(['pagado', 'parcial'])
    ).scalar() if obligacion_ids else 0

    # Total causado del mes actual
    causado_mes_actual = db.session.query(
        func.coalesce(func.sum(PagoObligacion.valor_causado), 0)
    ).filter(
        PagoObligacion.obligacion_id.in_(obligacion_ids),
        PagoObligacion.anio == anio,
        PagoObligacion.mes == mes
    ).scalar() if obligacion_ids else 0

    # Totales del mes para el resumen detallado
    total_estimado_mes = 0
    total_estimado_items = 0
    total_causado_items = 0
    sin_causar_mes = 0
    sin_causar_items = 0
    total_pagado_items = 0
    total_pendiente_items = 0
    esperado_mes = 0
    items_mes_actual = []
    for o in obligaciones:
        cuota_estimado = _valor_programado_mes_obligacion(o, anio, mes, ultimos_pagos_dict.get(o.id))
        total_estimado_mes += cuota_estimado
        if cuota_estimado > 0:
            total_estimado_items += 1
        pago = pagos_dict.get(o.id)
        estado_item = pago.estado if pago else 'sin_causar'
        valor_causado = float(pago.valor_causado or 0) if pago else 0
        valor_pagado = float(pago.valor_pagado or 0) if pago else 0

        if valor_causado > 0:
            total_causado_items += 1
        if valor_pagado > 0:
            total_pagado_items += 1
        if estado_item in ('sin_causar', 'pendiente'):
            sin_causar_mes += cuota_estimado
            if cuota_estimado > 0:
                sin_causar_items += 1
        if valor_causado > valor_pagado:
            total_pendiente_items += 1

        items_mes_actual.append({
            'id': o.id,
            'nombre': o.tercero.nombre,
            'modalidad': o.modalidad.replace('_', ' ').title(),
            'estado': estado_item,
            'valor_estimado': cuota_estimado,
            'valor_causado': valor_causado,
            'cuota_esperada': cuota_estimado,
            'valor_pagado': valor_pagado
        })

    esperado_mes = float(causado_mes_actual) + sin_causar_mes
    total_esperado_items = len({
        item['id'] for item in items_mes_actual
        if item['valor_causado'] > 0 or (item['estado'] in ('sin_causar', 'pendiente') and item['valor_estimado'] > 0)
    })

    # Resumen agrupado por modalidad
    resumen_modalidades = {}
    for o in obligaciones:
        mod = o.modalidad
        label = MODALIDAD_LABELS.get(mod, mod.replace('_', ' ').title())
        if mod not in resumen_modalidades:
            resumen_modalidades[mod] = {
                'nombre': label,
                'color': _color_modalidad(mod),
                'cantidad': 0,
                'pagado': 0,
                'esperado': 0,
                'saldo_total': 0
            }
        resumen_modalidades[mod]['cantidad'] += 1
        resumen_modalidades[mod]['saldo_total'] += float(o.saldo_actual or 0)

        pago = pagos_dict.get(o.id)
        if pago and pago.estado in ('pagado', 'parcial'):
            resumen_modalidades[mod]['pagado'] += float(pago.valor_pagado or 0)

        resumen_modalidades[mod]['esperado'] += _valor_programado_mes_obligacion(o, anio, mes, ultimos_pagos_dict.get(o.id))

    resumen_grupos = [v for v in resumen_modalidades.values() if v['cantidad'] > 0]

    # Tarjetas por obligación
    obligaciones_mes = []
    for o in obligaciones:
        pago = pagos_dict.get(o.id)
        estado = pago.estado if pago else 'sin_causar'

        # Valor cuota esperada
        cuota_esperada = _valor_programado_mes_obligacion(o, anio, mes, ultimos_pagos_dict.get(o.id))
        if pago:
            if pago.valor_pagado:
                valor_mostrar = float(pago.valor_pagado)
            elif pago.valor_causado:
                valor_mostrar = float(pago.valor_causado)
            else:
                valor_mostrar = cuota_esperada
        else:
            valor_mostrar = cuota_esperada
        valor_causado = float(pago.valor_causado or 0) if pago else 0

        # Días restantes
        dias_restantes = None
        fechas_programadas_mes = _fechas_programadas_obligacion(o, anio, mes)
        fecha_limite_actual = fechas_programadas_mes[0] if fechas_programadas_mes else None
        esta_vencido = bool(fecha_limite_actual and estado != 'pagado' and fecha_limite_actual < hoy)
        estado_visual = 'vencido' if esta_vencido else estado

        fecha_referencia = fecha_limite_actual
        etiqueta_fecha = 'Fecha pactada' if o.modalidad == 'pago_total_pactado' else 'Dia limite'

        if estado == 'pagado':
            base_referencia = fechas_programadas_mes[-1] if fechas_programadas_mes else (
                pago.fecha_pago if pago and pago.fecha_pago else hoy
            )
            fecha_referencia = _siguiente_fecha_programada(o, base_referencia)
            etiqueta_fecha = 'Proximo pago'
        elif not fecha_referencia:
            fecha_referencia = _siguiente_fecha_programada(o, hoy - timedelta(days=1))
            if fecha_referencia:
                etiqueta_fecha = 'Proximo pago'

        dias_restantes = (fecha_referencia - hoy).days if fecha_referencia else None

        # Tipo de pago
        tipo_pago = None
        if pago and pago.estado == 'pagado' and pago.fecha_pago and fecha_limite_actual:
            diff = (pago.fecha_pago - fecha_limite_actual).days
            if diff < 0:
                tipo_pago = 'anticipado'
            elif diff == 0:
                tipo_pago = 'a_tiempo'
            else:
                tipo_pago = 'tarde'

        totales_pago = totales_pago_dict.get(o.id, {})
        capital_pagado_total = float(totales_pago.get('capital_pagado', 0))
        interes_pagado_total = float(totales_pago.get('interes_pagado', 0))
        pendiente_total = _saldo_pendiente_total_obligacion(o, capital_pagado_total)
        fecha_ultimo_pago = _fecha_ultimo_pago_estimada(o, fecha_referencia)
        dias_ultimo_pago = (fecha_ultimo_pago - hoy).days if fecha_ultimo_pago else None

        obligaciones_mes.append({
            'obligacion': o,
            'pago': pago,
            'estado': estado,
            'estado_visual': estado_visual,
            'valor_mostrar': valor_mostrar,
            'valor_causado': valor_causado,
            'cuota_esperada': cuota_esperada,
            'dias_restantes': dias_restantes,
            'tipo_pago': tipo_pago,
            'fecha_referencia': fecha_referencia,
            'fecha_limite_actual': fecha_limite_actual,
            'etiqueta_fecha': etiqueta_fecha,
            'esta_vencido': esta_vencido,
            'es_estimado': not pago or not (pago.valor_causado or pago.valor_pagado),
            'capital_pagado_total': capital_pagado_total,
            'interes_pagado_total': interes_pagado_total,
            'pendiente_total': pendiente_total,
            'fecha_ultimo_pago': fecha_ultimo_pago,
            'dias_ultimo_pago': dias_ultimo_pago,
        })

    prioridad_estado = {
        'vencido': 0,
        'parcial': 1,
        'causado': 2,
        'pendiente': 3,
        'sin_causar': 4,
        'pagado': 5,
    }
    obligaciones_mes.sort(key=lambda item: (
        1 if item['estado'] == 'pagado' else 0,
        prioridad_estado.get(item['estado_visual'], 9),
        item['fecha_referencia'] or date.max,
        item['obligacion'].dia_limite_pago or 99,
        item['obligacion'].tercero.nombre.lower(),
    ))

    total_items_mes = len(obligaciones_mes)

    return render_template('obligaciones/pagos.html',
                           obligaciones_mes=obligaciones_mes,
                           pendientes_anteriores=pendientes_anteriores,
                           anio=anio, mes=mes, meses=MESES,
                           medios=medios,
                           acum_pagado_anterior=float(acum_pagado_anterior),
                           acum_obligaciones_detalle=acum_obligaciones_detalle,
                           pagado_mes_actual=float(pagado_mes_actual),
                           causado_mes_actual=float(causado_mes_actual),
                           total_estimado_mes=total_estimado_mes,
                           total_estimado_items=total_estimado_items,
                           total_causado_items=total_causado_items,
                           sin_causar_mes=sin_causar_mes,
                           sin_causar_items=sin_causar_items,
                           esperado_mes=esperado_mes,
                           total_esperado_items=total_esperado_items,
                           total_deuda_anterior=total_deuda_anterior,
                           resumen_grupos=resumen_grupos,
                           pendiente_mes=float(causado_mes_actual) - float(pagado_mes_actual),
                           total_pagado_items=total_pagado_items,
                           total_pendiente_items=total_pendiente_items,
                           saldo_mes=esperado_mes - float(pagado_mes_actual),
                           total_items_mes=total_items_mes,
                           items_mes_actual=items_mes_actual)


def _color_modalidad(mod):
    colores = {
        'bancario_cuota_fija': '#2563eb',
        'solo_interes': '#f59e0b',
        'cadena': '#8b5cf6',
        'pago_total_pactado': '#059669',
    }
    return colores.get(mod, '#6366f1')


@obligaciones_bp.route('/pago', methods=['POST'])
def registrar_pago():
    obligacion_id = int(request.form['obligacion_id'])
    anio = int(request.form['anio'])
    mes = int(request.form['mes'])
    obligacion = Obligacion.query.get_or_404(obligacion_id)
    accion = request.form.get('accion', 'pagar')  # causar o pagar
    valor_causado = request.form.get('valor_causado') or None
    valor_pagado = request.form.get('valor_pagado') or None
    componente_capital = request.form.get('componente_capital') or None
    componente_interes = request.form.get('componente_interes') or None
    estado = request.form.get('estado', 'pagado')
    medio_pago_id = request.form.get('medio_pago_id') or None
    fecha_pago = request.form.get('fecha_pago') or None
    observaciones = request.form.get('observaciones', '').strip()
    valor_causado_num = _float_or_none(valor_causado)
    valor_pagado_num = _float_or_none(valor_pagado)
    componente_capital_num = _float_or_none(componente_capital)
    componente_interes_num = _float_or_none(componente_interes)

    if accion == 'pagar':
        if obligacion.requiere_desglose_pago and estado in ('pagado', 'parcial'):
            if componente_capital_num is None or componente_interes_num is None:
                flash('Esta obligacion requiere registrar la cuota discriminada entre capital e interes.', 'danger')
                return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))

            base_comparacion = valor_pagado_num if valor_pagado_num is not None else valor_causado_num
            total_componentes = (componente_capital_num or 0) + (componente_interes_num or 0)
            if base_comparacion is not None and abs(total_componentes - base_comparacion) > 1:
                flash('La suma de capital e interes debe coincidir con la cuota pagada.', 'danger')
                return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))
        elif (componente_capital_num is None) ^ (componente_interes_num is None):
            flash('Si registra capital o interes, debe diligenciar ambos valores.', 'danger')
            return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))

    pago = PagoObligacion.query.filter_by(
        obligacion_id=obligacion_id, anio=anio, mes=mes
    ).first()

    if pago:
        if accion == 'causar':
            pago.valor_causado = valor_causado
            pago.fecha_causacion = date.today()
            if pago.estado == 'sin_causar':
                pago.estado = 'causado'
        else:
            pago.valor_pagado = valor_pagado
            pago.componente_capital = componente_capital
            pago.componente_interes = componente_interes
            pago.estado = estado
            pago.medio_pago_id = medio_pago_id
            pago.fecha_pago = fecha_pago
            if valor_causado:
                pago.valor_causado = valor_causado
        pago.observaciones = observaciones
    else:
        numero_cuota = (obligacion.cuotas_pagadas or 0) + 1 if obligacion else None
        if accion == 'causar':
            pago = PagoObligacion(
                obligacion_id=obligacion_id, anio=anio, mes=mes,
                valor_causado=valor_causado, estado='causado',
                fecha_causacion=date.today(),
                numero_cuota=numero_cuota,
                observaciones=observaciones
            )
        else:
            pago = PagoObligacion(
                obligacion_id=obligacion_id, anio=anio, mes=mes,
                valor_causado=valor_causado, valor_pagado=valor_pagado,
                componente_capital=componente_capital,
                componente_interes=componente_interes,
                numero_cuota=numero_cuota,
                estado=estado, medio_pago_id=medio_pago_id,
                fecha_pago=fecha_pago, observaciones=observaciones
            )
        db.session.add(pago)

    # Actualizar saldo y cuotas de la obligación si se pagó
    if accion == 'pagar' and estado == 'pagado' and componente_capital:
        obligacion = Obligacion.query.get(obligacion_id)
        if obligacion and obligacion.saldo_actual:
            obligacion.saldo_actual = float(obligacion.saldo_actual) - float(componente_capital)
            obligacion.cuotas_pagadas = (obligacion.cuotas_pagadas or 0) + 1

    db.session.commit()
    flash('Registro actualizado.', 'success')
    return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))


@obligaciones_bp.route('/detalle/<int:id>')
def detalle(id):
    """Vista detalle de una obligación: historial de todos los meses del año"""
    obligacion = Obligacion.query.get_or_404(id)
    anio = request.args.get('anio', date.today().year, type=int)
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    pagos = PagoObligacion.query.filter_by(obligacion_id=id, anio=anio).order_by(PagoObligacion.mes).all()
    pagos_dict = {p.mes: p for p in pagos}
    return render_template('obligaciones/detalle.html',
                           obligacion=obligacion, anio=anio,
                           meses=MESES, pagos=pagos_dict, medios=medios)


# ==================== REFINANCIACIONES ====================

@obligaciones_bp.route('/<int:id>/refinanciaciones')
def refinanciaciones(id):
    obligacion = Obligacion.query.get_or_404(id)
    refis = Refinanciacion.query.filter_by(obligacion_id=id).order_by(
        Refinanciacion.fecha_refinanciacion.desc()).all()
    abonos = AbonoCapitalObligacion.query.filter_by(obligacion_id=id).order_by(
        AbonoCapitalObligacion.fecha_abono.desc(),
        AbonoCapitalObligacion.id.desc()
    ).all()
    pagos = PagoObligacion.query.filter_by(obligacion_id=id).all()

    total_pagado = sum(float(p.valor_pagado or 0) for p in pagos)
    total_capital_pagado = sum(float(p.componente_capital or 0) for p in pagos)
    total_interes_pagado = sum(float(p.componente_interes or 0) for p in pagos)
    total_abonos_capital = sum(float(a.valor_abono or 0) for a in abonos)
    total_amortizado = total_capital_pagado + total_abonos_capital
    salida_total = total_pagado + total_abonos_capital

    return render_template('obligaciones/refinanciaciones.html',
                           obligacion=obligacion,
                           refinanciaciones=refis,
                           abonos=abonos,
                           hoy=date.today(),
                           resumen_costos={
                               'capital_inicial': float(obligacion.capital_inicial or 0),
                               'saldo_actual': float(obligacion.saldo_actual or 0),
                               'total_pagado': total_pagado,
                               'total_capital_pagado': total_capital_pagado,
                               'total_interes_pagado': total_interes_pagado,
                               'total_abonos_capital': total_abonos_capital,
                               'total_amortizado': total_amortizado,
                               'salida_total': salida_total,
                           })


@obligaciones_bp.route('/<int:id>/abonar-capital', methods=['POST'])
def abonar_capital(id):
    obligacion = Obligacion.query.get_or_404(id)

    try:
        fecha_abono = datetime.strptime(request.form['fecha_abono'], '%Y-%m-%d').date()
    except (KeyError, ValueError):
        flash('La fecha del abono no es válida.', 'danger')
        return redirect(url_for('obligaciones.refinanciaciones', id=id))

    try:
        valor_abono = float(request.form.get('valor_abono') or 0)
    except ValueError:
        valor_abono = 0

    opcion_recalculo = request.form.get('opcion_recalculo')
    observaciones = request.form.get('observaciones', '').strip()

    saldo_anterior = float(obligacion.saldo_actual or 0)
    cuotas_pendientes_antes = obligacion.cuotas_pendientes or 0
    cuota_anterior = float(
        obligacion.valor_cuota_fija
        or obligacion.cuota_francesa_calculada
        or _valor_estimado_obligacion(obligacion)
        or 0
    )

    if valor_abono <= 0:
        flash('El valor del abono debe ser mayor que cero.', 'danger')
        return redirect(url_for('obligaciones.refinanciaciones', id=id))
    if saldo_anterior <= 0:
        flash('La obligación no tiene saldo pendiente para abonar.', 'warning')
        return redirect(url_for('obligaciones.refinanciaciones', id=id))
    if valor_abono > saldo_anterior:
        flash('El abono no puede ser mayor al saldo actual.', 'danger')
        return redirect(url_for('obligaciones.refinanciaciones', id=id))
    if opcion_recalculo not in ('reducir_cuota', 'reducir_plazo'):
        flash('Debe indicar si el abono reduce la cuota o reduce el plazo.', 'danger')
        return redirect(url_for('obligaciones.refinanciaciones', id=id))

    saldo_nuevo = max(saldo_anterior - valor_abono, 0)
    tasa_mensual = float(obligacion.tasa_interes_mensual or 0) / 100
    cuotas_pendientes_despues = cuotas_pendientes_antes
    cuota_nueva = cuota_anterior

    if saldo_nuevo <= 0:
        cuotas_pendientes_despues = 0
        cuota_nueva = 0
    elif opcion_recalculo == 'reducir_cuota':
        if cuotas_pendientes_antes <= 0:
            flash('No hay cuotas pendientes para recalcular la cuota.', 'warning')
            return redirect(url_for('obligaciones.refinanciaciones', id=id))
        if tasa_mensual > 0:
            cuota_nueva = _cuota_con_tasa(saldo_nuevo, tasa_mensual, cuotas_pendientes_antes)
        else:
            cuota_nueva = saldo_nuevo / cuotas_pendientes_antes
    else:
        cuota_objetivo = cuota_anterior
        if cuota_objetivo <= 0:
            flash('No fue posible determinar la cuota vigente para reducir el plazo.', 'warning')
            return redirect(url_for('obligaciones.refinanciaciones', id=id))
        cuotas_pendientes_despues = _plazo_con_tasa(saldo_nuevo, tasa_mensual, cuota_objetivo)
        if cuotas_pendientes_despues is None:
            flash('La cuota actual no alcanza a amortizar el interés mensual. Revise tasa o cuota.', 'warning')
            return redirect(url_for('obligaciones.refinanciaciones', id=id))

    abono = AbonoCapitalObligacion(
        obligacion_id=id,
        fecha_abono=fecha_abono,
        valor_abono=valor_abono,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=saldo_nuevo,
        opcion_recalculo=opcion_recalculo,
        cuotas_pendientes_antes=cuotas_pendientes_antes,
        cuotas_pendientes_despues=cuotas_pendientes_despues,
        cuota_anterior=cuota_anterior,
        cuota_nueva=cuota_nueva,
        observaciones=observaciones
    )
    db.session.add(abono)

    obligacion.saldo_actual = saldo_nuevo
    if opcion_recalculo == 'reducir_cuota':
        obligacion.valor_cuota_fija = cuota_nueva
    if obligacion.cuotas_totales is not None:
        obligacion.cuotas_totales = (obligacion.cuotas_pagadas or 0) + cuotas_pendientes_despues
    if saldo_nuevo <= 0:
        obligacion.valor_cuota_fija = 0

    db.session.commit()
    flash('Abono a capital registrado y obligación actualizada.', 'success')
    return redirect(url_for('obligaciones.refinanciaciones', id=id))


@obligaciones_bp.route('/<int:id>/refinanciar', methods=['POST'])
def refinanciar(id):
    obligacion = Obligacion.query.get_or_404(id)
    nuevo_valor_cuota = request.form.get('nuevo_valor_cuota')
    nuevo_valor_cuota_capital = request.form.get('nuevo_valor_cuota_capital')
    nuevo_valor_cuota_interes = request.form.get('nuevo_valor_cuota_interes')
    error_desglose = _validar_desglose_cuota_form(
        bool(_float_or_none(nuevo_valor_cuota_capital) is not None or _float_or_none(nuevo_valor_cuota_interes) is not None),
        nuevo_valor_cuota,
        nuevo_valor_cuota_capital,
        nuevo_valor_cuota_interes,
    )
    if error_desglose:
        flash(error_desglose, 'danger')
        return redirect(url_for('obligaciones.refinanciaciones', id=id))

    refi = Refinanciacion(
        obligacion_id=id,
        fecha_refinanciacion=datetime.strptime(request.form['fecha_refinanciacion'], '%Y-%m-%d').date(),
        valor_refinanciado=request.form['valor_refinanciado'],
        nueva_tasa_mensual=request.form.get('nueva_tasa_mensual') or None,
        nuevo_plazo_meses=request.form.get('nuevo_plazo_meses') or None,
        nuevo_valor_cuota=nuevo_valor_cuota or None,
        nuevo_valor_cuota_capital=nuevo_valor_cuota_capital or None,
        nuevo_valor_cuota_interes=nuevo_valor_cuota_interes or None,
        nueva_fecha_vencimiento=request.form.get('nueva_fecha_vencimiento') or None,
        observaciones=request.form.get('observaciones', '').strip()
    )
    db.session.add(refi)

    # Actualizar la obligación con las nuevas condiciones
    if refi.nueva_tasa_mensual:
        obligacion.tasa_interes_mensual = refi.nueva_tasa_mensual
    if refi.nuevo_plazo_meses:
        obligacion.plazo_meses = refi.nuevo_plazo_meses
        obligacion.cuotas_totales = refi.nuevo_plazo_meses
    if refi.nuevo_valor_cuota:
        obligacion.valor_cuota_fija = refi.nuevo_valor_cuota
    if refi.nuevo_valor_cuota_capital is not None or refi.nuevo_valor_cuota_interes is not None:
        obligacion.valor_cuota_capital = refi.nuevo_valor_cuota_capital
        obligacion.valor_cuota_interes = refi.nuevo_valor_cuota_interes
        obligacion.requiere_desglose_pago = True
    if refi.nueva_fecha_vencimiento:
        obligacion.fecha_vencimiento = refi.nueva_fecha_vencimiento
    obligacion.saldo_actual = refi.valor_refinanciado

    db.session.commit()
    flash('Refinanciación registrada. Condiciones de la obligación actualizadas.', 'success')
    return redirect(url_for('obligaciones.refinanciaciones', id=id))
