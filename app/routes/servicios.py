from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from app import db
from app.models import (
    Servicio, PagoServicio, Tercero, Concepto, Categoria, MedioPago,
    HistorialEstado,
    GrupoServicio, GrupoServicioConcepto, PagoTC
)
from app.conceptos_estado import (
    ESTADOS_SERVICIO,
    cargar_historial_conceptos, cargar_historial_servicios,
    concepto_activo_en_periodo, servicio_activo_en_periodo,
    estado_servicio_en_periodo, periodo_anterior, siguiente_cambio_servicio
)
from calendar import monthrange
from datetime import date, datetime
from io import BytesIO

servicios_bp = Blueprint('servicios', __name__, url_prefix='/servicios')

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
MAX_COMPROBANTE_SIZE = 5 * 1024 * 1024


def _resolver_dia_pago(dia_valor, fecha_pago_valor=None):
    valor_fuente = dia_valor
    if valor_fuente in (None, '') and fecha_pago_valor:
        try:
            valor_fuente = datetime.strptime(fecha_pago_valor, '%Y-%m-%d').day
        except ValueError:
            valor_fuente = None

    if valor_fuente in (None, ''):
        return None, None

    try:
        dia = int(valor_fuente)
    except (TypeError, ValueError):
        return None, 'El dia de pago debe ser un numero entre 1 y 31.'

    if dia < 1 or dia > 31:
        return None, 'El dia de pago debe estar entre 1 y 31.'

    return dia, None


def _leer_comprobante(archivo):
    if not archivo or not archivo.filename:
        return None, None, None, None

    contenido = archivo.read()
    if not contenido:
        return None, None, None, 'El comprobante adjunto esta vacio.'

    if len(contenido) > MAX_COMPROBANTE_SIZE:
        return None, None, None, 'El comprobante supera el limite de 5 MB.'

    return archivo.filename[:255], (archivo.mimetype or 'application/octet-stream')[:120], contenido, None


def _aplicar_dia_pago_servicio(servicio, nuevo_dia):
    if not nuevo_dia:
        return

    servicio.dia_limite_pago = nuevo_dia
    if servicio.periodicidad == 'anual' and servicio.fecha_pago_anual:
        ultimo_dia = monthrange(servicio.fecha_pago_anual.year, servicio.fecha_pago_anual.month)[1]
        servicio.fecha_pago_anual = servicio.fecha_pago_anual.replace(day=min(nuevo_dia, ultimo_dia))


def _conceptos_activos_categoria(nombre_categoria, anio, mes):
    cat = Categoria.query.filter_by(nombre=nombre_categoria).first()
    conceptos = Concepto.query.filter_by(categoria_id=cat.id).order_by(Concepto.nombre).all() if cat else []
    historiales = cargar_historial_conceptos([c.id for c in conceptos])
    return [
        c for c in conceptos
        if concepto_activo_en_periodo(c, anio, mes, historiales.get(c.id, []))
    ]


@servicios_bp.route('/')
def lista():
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.dia_limite_pago).all()
    anio = request.args.get('anio', date.today().year, type=int)
    mes = request.args.get('mes', date.today().month, type=int)
    historiales = cargar_historial_servicios([s.id for s in servicios])
    for servicio in servicios:
        rows = historiales.get(servicio.id, [])
        estado_operativo, cambio_vigente = estado_servicio_en_periodo(
            servicio, anio, mes, rows
        )
        servicio.estado_operativo = estado_operativo
        servicio.cambio_vigente = cambio_vigente
        servicio.proximo_cambio = siguiente_cambio_servicio(servicio, anio, mes, rows)
    return render_template(
        'servicios/lista.html',
        servicios=servicios,
        anio=anio,
        mes=mes,
        meses=MESES,
        mes_actual=date.today().strftime('%Y-%m')
    )


@servicios_bp.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if request.method == 'POST':
        fecha_pago_anual = request.form.get('fecha_pago_anual') or None
        servicio = Servicio(
            tercero_id=request.form['tercero_id'],
            concepto_id=request.form['concepto_id'],
            referencia=request.form.get('referencia', '').strip(),
            periodicidad=request.form.get('periodicidad', 'mensual'),
            dia_limite_pago=request.form.get('dia_limite_pago') or None,
            dia_causacion=request.form.get('dia_causacion') or None,
            valor_estimado=request.form.get('valor_estimado') or None,
            provision_mensual=request.form.get('provision_mensual') or None,
            fecha_pago_anual=fecha_pago_anual,
            mes_inicio_bimestral=request.form.get('mes_inicio_bimestral') or 1,
            direccion_inmueble=request.form.get('direccion_inmueble', '').strip(),
            estrato=request.form.get('estrato') or None,
            estado='activo',
            observaciones=request.form.get('observaciones', '').strip()
        )
        db.session.add(servicio)
        db.session.commit()
        flash('Servicio creado correctamente.', 'success')
        return redirect(url_for('servicios.lista'))

    conceptos = _conceptos_activos_categoria('Servicios Públicos', date.today().year, date.today().month)
    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    return render_template('servicios/form.html', servicio=None,
                           conceptos=conceptos, terceros=terceros)


@servicios_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    servicio = Servicio.query.get_or_404(id)
    if request.method == 'POST':
        servicio.tercero_id = request.form['tercero_id']
        servicio.concepto_id = request.form['concepto_id']
        servicio.referencia = request.form.get('referencia', '').strip()
        servicio.periodicidad = request.form.get('periodicidad', 'mensual')
        servicio.dia_limite_pago = request.form.get('dia_limite_pago') or None
        servicio.dia_causacion = request.form.get('dia_causacion') or None
        servicio.valor_estimado = request.form.get('valor_estimado') or None
        servicio.provision_mensual = request.form.get('provision_mensual') or None
        servicio.fecha_pago_anual = request.form.get('fecha_pago_anual') or None
        servicio.mes_inicio_bimestral = request.form.get('mes_inicio_bimestral') or 1
        servicio.direccion_inmueble = request.form.get('direccion_inmueble', '').strip()
        servicio.estrato = request.form.get('estrato') or None
        servicio.observaciones = request.form.get('observaciones', '').strip()
        db.session.commit()
        flash('Servicio actualizado.', 'success')
        return redirect(url_for('servicios.lista'))

    conceptos = _conceptos_activos_categoria('Servicios Públicos', date.today().year, date.today().month)
    if servicio.concepto and not any(c.id == servicio.concepto_id for c in conceptos):
        conceptos = sorted(conceptos + [servicio.concepto], key=lambda item: item.nombre.lower())
    hoy = date.today()
    historial_rows = cargar_historial_servicios([servicio.id]).get(servicio.id, [])
    servicio.estado_operativo, servicio.cambio_vigente = estado_servicio_en_periodo(
        servicio, hoy.year, hoy.month, historial_rows
    )
    servicio.proximo_cambio = siguiente_cambio_servicio(servicio, hoy.year, hoy.month, historial_rows)
    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    return render_template('servicios/form.html', servicio=servicio,
                           conceptos=conceptos, terceros=terceros,
                           mes_actual=hoy.strftime('%Y-%m'))


@servicios_bp.route('/pagos')
@servicios_bp.route('/pagos/<int:anio>')
@servicios_bp.route('/pagos/<int:anio>/<int:mes>')
def pagos(anio=None, mes=None):
    if anio is None:
        anio = date.today().year
    if mes is None:
        mes = date.today().month

    hoy = date.today()
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.dia_limite_pago).all()
    historiales = cargar_historial_servicios([s.id for s in servicios])
    servicios = [
        s for s in servicios
        if servicio_activo_en_periodo(s, anio, mes, historiales.get(s.id, []))
    ]
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    servicio_ids = [s.id for s in servicios]

    def servicio_aplica_mes(s, m):
        """Verifica si un servicio aplica para el mes dado según su periodicidad"""
        if s.periodicidad == 'bimestral':
            mes_inicio = s.mes_inicio_bimestral or 1
            if mes_inicio == 1 and m % 2 == 0:  # odd months only
                return False
            if mes_inicio == 2 and m % 2 != 0:  # even months only
                return False
        if s.periodicidad == 'anual' and m != 1:
            return False
        return True

    def fecha_limite_periodo(s, periodo_anio, periodo_mes):
        if not s.dia_limite_pago:
            return None
        ultimo_dia = monthrange(periodo_anio, periodo_mes)[1]
        return date(periodo_anio, periodo_mes, min(s.dia_limite_pago, ultimo_dia))

    def siguiente_periodo_aplicable(s, periodo_anio, periodo_mes):
        siguiente_anio = periodo_anio
        siguiente_mes = periodo_mes
        for _ in range(24):
            siguiente_mes += 1
            if siguiente_mes > 12:
                siguiente_mes = 1
                siguiente_anio += 1
            if servicio_aplica_mes(s, siguiente_mes):
                return siguiente_anio, siguiente_mes
        return None, None

    # Pagos del mes seleccionado
    pagos_mes = PagoServicio.query.filter(
        PagoServicio.anio == anio,
        PagoServicio.mes == mes,
        PagoServicio.servicio_id.in_(servicio_ids)
    ).all() if servicio_ids else []
    pagos_dict = {p.servicio_id: p for p in pagos_mes}

    ultimos_pagos = []
    if servicio_ids:
        ultimos_pagos = PagoServicio.query.filter(
            PagoServicio.servicio_id.in_(servicio_ids),
            PagoServicio.valor_pagado.isnot(None),
            PagoServicio.valor_pagado > 0,
            db.or_(
                PagoServicio.anio < anio,
                db.and_(PagoServicio.anio == anio, PagoServicio.mes < mes)
            )
        ).order_by(
            PagoServicio.servicio_id,
            PagoServicio.anio.desc(),
            PagoServicio.mes.desc(),
            PagoServicio.fecha_pago.desc(),
            PagoServicio.id.desc()
        ).all()

    ultimo_pago_por_servicio = {}
    for pago_hist in ultimos_pagos:
        if pago_hist.servicio_id not in ultimo_pago_por_servicio:
            ultimo_pago_por_servicio[pago_hist.servicio_id] = float(pago_hist.valor_pagado or 0)

    def valor_estimado_servicio(servicio):
        valor_ultimo_pago = ultimo_pago_por_servicio.get(servicio.id)
        if valor_ultimo_pago and valor_ultimo_pago > 0:
            return valor_ultimo_pago
        return float(servicio.valor_estimado or 0)

    # Pendientes de meses anteriores (causado, vencido, parcial)
    pendientes_anteriores = []
    total_deuda_anterior = 0
    saldo_anterior_por_servicio = {}
    for s in servicios:
        deudas = PagoServicio.query.filter(
            PagoServicio.servicio_id == s.id,
            PagoServicio.estado.in_(['causado', 'vencido', 'parcial']),
            db.or_(
                PagoServicio.anio < anio,
                db.and_(PagoServicio.anio == anio, PagoServicio.mes < mes)
            )
        ).order_by(PagoServicio.anio, PagoServicio.mes).all()
        for d in deudas:
            valor_deuda = float(d.valor_causado or d.valor_pagado or 0)
            if d.estado == 'parcial' and d.valor_causado and d.valor_pagado:
                valor_deuda = float(d.valor_causado) - float(d.valor_pagado)
            total_deuda_anterior += valor_deuda
            saldo_anterior_por_servicio[s.id] = saldo_anterior_por_servicio.get(s.id, 0) + valor_deuda
            pendientes_anteriores.append({
                'servicio': s,
                'pago': d,
                'mes_nombre': MESES[d.mes - 1],
                'anio': d.anio,
                'valor_deuda': valor_deuda
            })

    # Acumulados
    from sqlalchemy import func

    # Pagado hasta el mes anterior (inclusive)
    acum_pagado_anterior = db.session.query(
        func.coalesce(func.sum(PagoServicio.valor_pagado), 0)
    ).filter(
        PagoServicio.servicio_id.in_(servicio_ids),
        PagoServicio.anio == anio,
        PagoServicio.mes < mes,
        PagoServicio.estado.in_(['pagado', 'parcial'])
    ).scalar() if servicio_ids else 0

    # Pagado en el mes actual
    pagado_mes_actual = db.session.query(
        func.coalesce(func.sum(PagoServicio.valor_pagado), 0)
    ).filter(
        PagoServicio.servicio_id.in_(servicio_ids),
        PagoServicio.anio == anio,
        PagoServicio.mes == mes,
        PagoServicio.estado.in_(['pagado', 'parcial'])
    ).scalar() if servicio_ids else 0

    # Acumulado pagado por servicio hasta el mes anterior
    acum_por_servicio_rows = db.session.query(
        PagoServicio.servicio_id,
        func.coalesce(func.sum(PagoServicio.valor_pagado), 0).label('total')
    ).filter(
        PagoServicio.servicio_id.in_(servicio_ids),
        PagoServicio.anio == anio,
        PagoServicio.mes < mes,
        PagoServicio.estado.in_(['pagado', 'parcial'])
    ).group_by(PagoServicio.servicio_id).all() if servicio_ids else []

    acum_servicios_detalle = []
    for servicio_id, total in acum_por_servicio_rows:
        servicio = next((s for s in servicios if s.id == servicio_id), None)
        if servicio and float(total or 0) > 0:
            acum_servicios_detalle.append({
                'servicio': servicio,
                'total': float(total)
            })

    acum_servicios_detalle.sort(key=lambda item: item['total'], reverse=True)

    # Enhanced month card: calculate sin_causar, total_esperado, pendiente, saldo
    causado_mes_actual = 0
    total_estimado_mes = 0
    total_estimado_items = 0
    total_causado_items = 0
    sin_causar_mes = 0
    sin_causar_items = 0
    total_pagado_items = 0
    total_pendiente_items = 0
    items_mes_actual = []
    for s in servicios:
        if not servicio_aplica_mes(s, mes):
            continue
        pago = pagos_dict.get(s.id)
        valor_estimado = valor_estimado_servicio(s)
        total_estimado_mes += valor_estimado
        if valor_estimado > 0:
            total_estimado_items += 1
        valor_causado = float((pago.valor_causado or pago.valor_pagado) or 0) if pago else 0
        valor_pagado = float(pago.valor_pagado or 0) if pago else 0
        estado_item = pago.estado if pago else 'sin_causar'

        if valor_causado > 0:
            total_causado_items += 1
            causado_mes_actual += valor_causado
        if valor_pagado > 0:
            total_pagado_items += 1
        if valor_causado <= 0 and estado_item != 'n/a':
            sin_causar_mes += valor_estimado
            if valor_estimado > 0:
                sin_causar_items += 1
        if valor_causado > valor_pagado:
            total_pendiente_items += 1

        items_mes_actual.append({
            'id': s.id,
            'nombre': s.tercero.nombre,
            'estado': estado_item,
            'valor_causado': valor_causado,
            'valor_pagado': valor_pagado,
            'valor_estimado': valor_estimado
        })

    total_esperado_mes = float(causado_mes_actual) + sin_causar_mes
    total_esperado_items = len({
        item['id'] for item in items_mes_actual
        if item['valor_causado'] > 0 or (item['estado'] != 'n/a' and item['valor_estimado'] > 0)
    })
    pendiente_mes = float(causado_mes_actual) - float(pagado_mes_actual)
    saldo_mes = total_esperado_mes - float(pagado_mes_actual)
    diferencia_estimado_mes = total_esperado_mes - total_estimado_mes
    por_pagar_mes = max(saldo_mes, 0)
    saldo_favor_mes = abs(saldo_mes) if saldo_mes < 0 else 0
    total_por_cubrir_hoy = total_deuda_anterior + por_pagar_mes
    items_por_cubrir_mes = total_pendiente_items + sin_causar_items
    total_items_mes = len(items_mes_actual)

    # Resumen agrupado del mes (usa grupos personalizados si existen, sino agrupa por concepto)
    grupos = GrupoServicio.query.filter_by(activo=True).order_by(GrupoServicio.orden).all()
    resumen_grupos = []

    if grupos:
        concepto_a_grupo = {}
        for g in grupos:
            for gc in g.conceptos.all():
                concepto_a_grupo[gc.concepto_id] = g

        grupo_datos = {}
        sin_grupo_datos = {'nombre': 'Otros', 'color': '#94a3b8', 'causado': 0, 'pagado': 0, 'cantidad': 0, 'detalle': []}

        for g in grupos:
            grupo_datos[g.id] = {'nombre': g.nombre, 'color': g.color, 'causado': 0, 'pagado': 0, 'cantidad': 0, 'detalle': []}

        for s in servicios:
            if not servicio_aplica_mes(s, mes):
                continue
            pago = pagos_dict.get(s.id)
            grupo = concepto_a_grupo.get(s.concepto_id)
            valor_estimado_item = valor_estimado_servicio(s)
            valor_causado = float((pago.valor_causado or pago.valor_pagado) or 0) if pago else valor_estimado_item
            if valor_causado <= 0 and (not pago or pago.estado != 'n/a'):
                valor_causado = valor_estimado_item
            valor_pagado = float(pago.valor_pagado or 0) if pago else 0

            item_data = {
                'id': s.id,
                'nombre': s.tercero.nombre,
                'concepto': s.concepto.nombre,
                'causado': valor_causado,
                'pagado': valor_pagado,
                'estado': pago.estado if pago else 'sin_causar'
            }

            if grupo:
                grupo_datos[grupo.id]['causado'] += valor_causado
                grupo_datos[grupo.id]['pagado'] += valor_pagado
                grupo_datos[grupo.id]['cantidad'] += 1
                grupo_datos[grupo.id]['detalle'].append(item_data)
            else:
                sin_grupo_datos['causado'] += valor_causado
                sin_grupo_datos['pagado'] += valor_pagado
                sin_grupo_datos['cantidad'] += 1
                sin_grupo_datos['detalle'].append(item_data)

        resumen_grupos = [d for d in grupo_datos.values() if d['cantidad'] > 0]
        if sin_grupo_datos['cantidad'] > 0:
            resumen_grupos.append(sin_grupo_datos)
    else:
        resumen_conceptos = {}
        for s in servicios:
            if not servicio_aplica_mes(s, mes):
                continue
            concepto_nombre = s.concepto.nombre
            pago = pagos_dict.get(s.id)
            if concepto_nombre not in resumen_conceptos:
                resumen_conceptos[concepto_nombre] = {'causado': 0, 'pagado': 0, 'cantidad': 0, 'detalle': []}
            resumen_conceptos[concepto_nombre]['cantidad'] += 1

            valor_causado_item = 0
            valor_pagado_item = 0
            estado_item = 'sin_causar'
            valor_estimado_item = valor_estimado_servicio(s)
            if pago:
                valor_causado_item = float((pago.valor_causado or pago.valor_pagado) or 0)
                if valor_causado_item <= 0 and pago.estado != 'n/a':
                    valor_causado_item = valor_estimado_item
                resumen_conceptos[concepto_nombre]['causado'] += valor_causado_item
                resumen_conceptos[concepto_nombre]['pagado'] += float(pago.valor_pagado or 0)
                valor_pagado_item = float(pago.valor_pagado or 0)
                estado_item = pago.estado
            elif valor_estimado_item:
                resumen_conceptos[concepto_nombre]['causado'] += valor_estimado_item
                valor_causado_item = valor_estimado_item

            resumen_conceptos[concepto_nombre]['detalle'].append({
                'id': s.id,
                'nombre': s.tercero.nombre,
                'concepto': s.concepto.nombre,
                'causado': valor_causado_item,
                'pagado': valor_pagado_item,
                'estado': estado_item
            })

        for nombre, datos in resumen_conceptos.items():
            resumen_grupos.append({'nombre': nombre, 'color': '#6366f1', **datos})

    # Para cada servicio del mes: estado, valor, días restantes, tipo de pago
    servicios_mes = []
    for s in servicios:
        if not servicio_aplica_mes(s, mes):
            continue

        pago = pagos_dict.get(s.id)
        estado = pago.estado if pago else 'sin_causar'
        valor_mostrar = None
        es_estimado = False

        if pago:
            if pago.valor_pagado:
                valor_mostrar = float(pago.valor_pagado)
            elif pago.valor_causado:
                valor_mostrar = float(pago.valor_causado)
            else:
                valor_mostrar = valor_estimado_servicio(s) or None
                es_estimado = True
        else:
            valor_mostrar = valor_estimado_servicio(s) or None
            es_estimado = True

        # Calcular días restantes para el pago
        fecha_limite_actual = fecha_limite_periodo(s, anio, mes)
        esta_vencido = bool(
            fecha_limite_actual and
            estado not in ('pagado', 'n/a') and
            fecha_limite_actual < hoy
        )
        estado_visual = 'vencido' if esta_vencido else ('na' if estado == 'n/a' else estado)

        fecha_referencia = fecha_limite_actual
        etiqueta_fecha = 'Dia limite'
        es_proximo_pago = False
        if estado == 'pagado':
            siguiente_anio, siguiente_mes = siguiente_periodo_aplicable(s, anio, mes)
            if siguiente_anio and siguiente_mes:
                fecha_referencia = fecha_limite_periodo(s, siguiente_anio, siguiente_mes)
                etiqueta_fecha = 'Proximo pago'
                es_proximo_pago = True

        dias_restantes = None
        if fecha_referencia and estado != 'n/a':
            dias_restantes = (fecha_referencia - hoy).days

        # Determinar tipo de pago (anticipado, a tiempo, vencido)
        tipo_pago = None
        if pago and pago.estado == 'pagado' and pago.fecha_pago and s.dia_limite_pago:
            try:
                fecha_limite = fecha_limite_actual or fecha_limite_periodo(s, anio, mes)
                diff = (pago.fecha_pago - fecha_limite).days
                if diff < 0:
                    tipo_pago = 'anticipado'
                elif diff == 0:
                    tipo_pago = 'a_tiempo'
                else:
                    tipo_pago = 'tarde'
            except ValueError:
                pass

        servicios_mes.append({
            'servicio': s,
            'pago': pago,
            'estado': estado,
            'estado_visual': estado_visual,
            'esta_vencido': esta_vencido,
            'valor_mostrar': valor_mostrar,
            'es_estimado': es_estimado,
            'dias_restantes': dias_restantes,
            'tipo_pago': tipo_pago,
            'saldo_anterior': saldo_anterior_por_servicio.get(s.id, 0),
            'fecha_referencia': fecha_referencia,
            'etiqueta_fecha': etiqueta_fecha,
            'es_proximo_pago': es_proximo_pago,
        })

    prioridad_estado = {
        'vencido': 0,
        'parcial': 1,
        'causado': 2,
        'sin_causar': 3,
        'na': 4,
        'pagado': 5,
    }
    servicios_mes.sort(key=lambda item: (
        1 if item['estado'] == 'pagado' else 0,
        prioridad_estado.get(item['estado_visual'], 9),
        item['fecha_referencia'] or date.max,
        item['servicio'].dia_limite_pago or 99,
        item['servicio'].tercero.nombre.lower(),
    ))

    return render_template('servicios/pagos.html',
                           servicios_mes=servicios_mes,
                           pendientes_anteriores=pendientes_anteriores,
                           anio=anio, mes=mes, meses=MESES,
                            medios=medios,
                            acum_pagado_anterior=float(acum_pagado_anterior),
                            acum_servicios_detalle=acum_servicios_detalle,
                            pagado_mes_actual=float(pagado_mes_actual),
                           causado_mes_actual=float(causado_mes_actual),
                           total_deuda_anterior=total_deuda_anterior,
                            resumen_grupos=resumen_grupos,
                            total_estimado_mes=total_estimado_mes,
                            total_estimado_items=total_estimado_items,
                            total_causado_items=total_causado_items,
                            sin_causar_mes=sin_causar_mes,
                            sin_causar_items=sin_causar_items,
                            total_esperado_mes=total_esperado_mes,
                            total_esperado_items=total_esperado_items,
                            diferencia_estimado_mes=diferencia_estimado_mes,
                            pendiente_mes=pendiente_mes,
                            por_pagar_mes=por_pagar_mes,
                            saldo_favor_mes=saldo_favor_mes,
                            total_por_cubrir_hoy=total_por_cubrir_hoy,
                            items_por_cubrir_mes=items_por_cubrir_mes,
                            total_pagado_items=total_pagado_items,
                            total_pendiente_items=total_pendiente_items,
                            saldo_mes=saldo_mes,
                            total_items_mes=total_items_mes,
                            items_mes_actual=items_mes_actual)


@servicios_bp.route('/detalle/<int:id>')
def detalle(id):
    """Vista detalle de un servicio: historial de todos los meses del año"""
    servicio = Servicio.query.get_or_404(id)
    anio = request.args.get('anio', date.today().year, type=int)
    pagos = PagoServicio.query.filter_by(servicio_id=id, anio=anio).order_by(PagoServicio.mes).all()
    pagos_dict = {p.mes: p for p in pagos}
    return render_template('servicios/detalle.html',
                           servicio=servicio, anio=anio,
                           meses=MESES, pagos=pagos_dict)


@servicios_bp.route('/<int:id>/cambiar-estado', methods=['POST'])
def cambiar_estado(id):
    servicio = Servicio.query.get_or_404(id)
    nuevo_estado = request.form.get('estado', '').strip().lower()
    motivo = request.form.get('motivo', '').strip()
    vigencia_str = request.form.get('vigencia_desde', '').strip()
    destino = request.form.get('next_url', '').strip() or url_for('servicios.lista', anio=date.today().year, mes=date.today().month)

    if nuevo_estado not in ESTADOS_SERVICIO:
        flash('Seleccione un estado válido para el servicio.', 'danger')
        return redirect(destino)
    if not motivo:
        flash('Debe indicar el motivo del cambio de estado.', 'danger')
        return redirect(destino)
    if not vigencia_str:
        flash('Debe indicar desde qué mes empieza a operar el nuevo estado.', 'danger')
        return redirect(destino)

    try:
        vigencia_desde = datetime.strptime(vigencia_str, '%Y-%m').date().replace(day=1)
    except ValueError:
        flash('El mes de vigencia no es válido.', 'danger')
        return redirect(destino)

    mes_actual = date.today().replace(day=1)
    if vigencia_desde < mes_actual:
        flash('El nuevo estado no puede operar hacia atrás.', 'danger')
        return redirect(destino)

    historiales = cargar_historial_servicios([servicio.id]).get(servicio.id, [])
    anio_prev, mes_prev = periodo_anterior(vigencia_desde.year, vigencia_desde.month)
    estado_anterior, _ = estado_servicio_en_periodo(servicio, anio_prev, mes_prev, historiales)
    estado_objetivo, _ = estado_servicio_en_periodo(servicio, vigencia_desde.year, vigencia_desde.month, historiales)

    if estado_objetivo == nuevo_estado:
        flash('Ese servicio ya queda en ese estado para el mes indicado.', 'warning')
        return redirect(destino)

    db.session.add(HistorialEstado(
        entidad='servicio',
        entidad_id=servicio.id,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado,
        fecha_cambio=datetime.utcnow(),
        vigencia_desde=vigencia_desde,
        motivo=motivo
    ))

    if vigencia_desde <= mes_actual:
        servicio.estado = nuevo_estado
    db.session.commit()
    flash(
        f'Servicio "{servicio.tercero.nombre}" programado como {nuevo_estado} desde {vigencia_desde.strftime("%m/%Y")}.',
        'info'
    )
    return redirect(destino)


@servicios_bp.route('/pago', methods=['POST'])
def registrar_pago():
    servicio_id = int(request.form['servicio_id'])
    anio = int(request.form['anio'])
    mes = int(request.form['mes'])
    servicio = Servicio.query.get_or_404(servicio_id)
    accion = request.form.get('accion', 'pagar')  # causar o pagar
    valor_causado = request.form.get('valor_causado') or None
    valor_pagado = request.form.get('valor_pagado') or None
    estado = request.form.get('estado', 'pagado')
    medio_pago_id = request.form.get('medio_pago_id') or None
    fecha_pago = request.form.get('fecha_pago') or None
    dia_pago_reportado, error_dia = _resolver_dia_pago(
        request.form.get('dia_pago_reportado'),
        fecha_pago
    )
    if accion == 'pagar' and error_dia:
        flash(error_dia, 'danger')
        return redirect(url_for('servicios.pagos', anio=anio, mes=mes))

    comprobante_nombre, comprobante_mime, comprobante_archivo, error_comprobante = _leer_comprobante(
        request.files.get('comprobante')
    )
    if accion == 'pagar' and error_comprobante:
        flash(error_comprobante, 'danger')
        return redirect(url_for('servicios.pagos', anio=anio, mes=mes))

    observaciones = request.form.get('observaciones', '').strip()

    pago = PagoServicio.query.filter_by(
        servicio_id=servicio_id, anio=anio, mes=mes
    ).first()

    if pago:
        if accion == 'causar':
            pago.valor_causado = valor_causado
            # Fecha de causación automática (server-side)
            pago.fecha_causacion = date.today()
            if pago.estado == 'sin_causar':
                pago.estado = 'causado'
        else:
            pago.valor_pagado = valor_pagado
            pago.estado = estado
            pago.medio_pago_id = medio_pago_id
            pago.fecha_pago = fecha_pago
            pago.dia_pago_reportado = dia_pago_reportado
            if valor_causado:
                pago.valor_causado = valor_causado
            if comprobante_archivo:
                pago.comprobante_nombre = comprobante_nombre
                pago.comprobante_mime = comprobante_mime
                pago.comprobante_archivo = comprobante_archivo
        pago.observaciones = observaciones
    else:
        if accion == 'causar':
            pago = PagoServicio(
                servicio_id=servicio_id, anio=anio, mes=mes,
                valor_causado=valor_causado, estado='causado',
                # Fecha de causación automática (server-side)
                fecha_causacion=date.today(),
                observaciones=observaciones
            )
        else:
            pago = PagoServicio(
                servicio_id=servicio_id, anio=anio, mes=mes,
                valor_causado=valor_causado, valor_pagado=valor_pagado,
                estado=estado, medio_pago_id=medio_pago_id,
                fecha_pago=fecha_pago, observaciones=observaciones,
                dia_pago_reportado=dia_pago_reportado,
                comprobante_nombre=comprobante_nombre,
                comprobante_mime=comprobante_mime,
                comprobante_archivo=comprobante_archivo
            )
        db.session.add(pago)

    if accion == 'pagar' and dia_pago_reportado:
        _aplicar_dia_pago_servicio(servicio, dia_pago_reportado)

    db.session.commit()

    # Si el medio de pago es "Tarjeta crédito", guardar info TC
    if accion == 'pagar' and medio_pago_id:
        medio = MedioPago.query.get(int(medio_pago_id))
        if medio and 'tarjeta' in medio.nombre.lower() and 'cr' in medio.nombre.lower():
            titular_tc = request.form.get('titular_tc', '').strip()
            numero_cuotas_tc = request.form.get('numero_cuotas_tc') or 1
            fecha_pago_tc = request.form.get('fecha_pago_tc') or None
            if titular_tc:
                valor_cuota = float(valor_pagado) / int(numero_cuotas_tc) if valor_pagado and int(numero_cuotas_tc) > 0 else None
                pago_tc = PagoTC(
                    pago_tipo='servicio',
                    pago_id=pago.id,
                    titular_tc=titular_tc,
                    numero_cuotas=int(numero_cuotas_tc),
                    fecha_pago_tc=fecha_pago_tc,
                    valor_cuota=valor_cuota
                )
                db.session.add(pago_tc)
                db.session.commit()

    flash('Registro actualizado.', 'success')
    return redirect(url_for('servicios.pagos', anio=anio, mes=mes))


@servicios_bp.route('/pago/<int:pago_id>/comprobante')
def descargar_comprobante(pago_id):
    pago = PagoServicio.query.get_or_404(pago_id)
    if not pago.comprobante_archivo:
        flash('Este pago no tiene comprobante adjunto.', 'warning')
        return redirect(request.referrer or url_for('servicios.detalle', id=pago.servicio_id, anio=pago.anio))

    return send_file(
        BytesIO(pago.comprobante_archivo),
        mimetype=pago.comprobante_mime or 'application/octet-stream',
        download_name=pago.comprobante_nombre or f'comprobante_servicio_{pago.id}',
        as_attachment=False
    )
