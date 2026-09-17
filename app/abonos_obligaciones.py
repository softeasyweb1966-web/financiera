"""Planes de abonos: cálculos sin escritura, aplicación atómica e historial reversible."""
import hashlib
import json
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app import db
from app.models import AbonoCapitalObligacion

CENTAVO = Decimal('0.01')
ETIQUETAS = {
    'reducir_cuota': 'Reducir cuota — abono a capital',
    'reducir_plazo': 'Reducir plazo — abono a tiempo',
    'acuerdo': 'Abono con acuerdo de saldo y cuotas',
}
CAMPOS = ('saldo_actual', 'valor_cuota_fija', 'valor_cuota_capital',
          'valor_cuota_interes', 'cuotas_totales', 'fecha_vencimiento',
          'fecha_finalizacion', 'requiere_desglose_pago')


def dinero(value):
    try:
        result = Decimal(str(value or '0'))
        if not result.is_finite() or result < 0 or result > Decimal('999999999999.99'):
            raise ValueError()
        return result.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError('Ingrese valores monetarios válidos, positivos y sin separadores de miles.')


def serializar(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return value


def estado_firma(o):
    """Incluye pagos y tablas: un cambio concurrente invalida la vista previa/reversión."""
    def fila(obj):
        return {c.name: serializar(getattr(obj, c.name)) for c in obj.__table__.columns if c.name != 'updated_at'}
    state = {'obligacion': fila(o)}
    for nombre in ('pagos', 'amortizaciones', 'refinanciaciones'):
        state[nombre] = sorted([fila(p) for p in getattr(o, nombre).all()], key=lambda p: p['id'])
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def activo(o):
    # Cache por instancia, solamente durante la petición.
    if not hasattr(o, '_abono_plan_cache'):
        o._abono_plan_cache = next((a for a in o.abonos_capital.order_by(None).order_by(
            AbonoCapitalObligacion.id.desc()).all() if a.datos and not a.revertido), None)
    return o._abono_plan_cache


def plan_periodo(o, anio, mes):
    a = activo(o)
    if not a or (anio, mes) < (a.fecha_abono.year, a.fecha_abono.month):
        return None
    return [f for f in a.datos['plan'] if f['fecha'][:7] == f'{anio:04d}-{mes:02d}']


def cubierto_por_acuerdo(o, anio, mes):
    a = activo(o)
    return bool(a and a.opcion_recalculo == 'acuerdo'
                and (anio, mes) <= (a.fecha_abono.year, a.fecha_abono.month))


def _mes(fecha, desplazamiento):
    index = fecha.year * 12 + fecha.month - 1 + desplazamiento
    year, month = divmod(index, 12)
    return date(year, month + 1, min(fecha.day, monthrange(year, month + 1)[1]))


def preparar(o, form):
    opcion = form.get('opcion_recalculo')
    if opcion not in ETIQUETAS:
        raise ValueError('Seleccione el efecto del abono.')
    try:
        fecha = date.fromisoformat(form.get('fecha_abono', ''))
    except ValueError:
        raise ValueError('Ingrese una fecha de abono válida.')
    if fecha > date.today():
        raise ValueError('No se puede registrar como realizado un pago futuro.')
    if o.fecha_inicio and fecha < o.fecha_inicio:
        raise ValueError('El abono no puede ser anterior al inicio de la obligación.')
    anteriores = [a for a in o.abonos_capital.all() if not a.revertido]
    if any(a.fecha_abono > fecha for a in anteriores):
        raise ValueError('Existe un abono posterior. Registre los movimientos en orden de fecha.')
    saldo = dinero(o.saldo_actual)
    pago = dinero(form.get('valor_abono'))
    descuento = dinero(form.get('descuento_intereses'))
    if pago <= 0 or saldo <= 0 or pago + descuento > saldo:
        raise ValueError('El pago debe ser mayor que cero y pago más descuento no puede superar el saldo.')
    if opcion != 'acuerdo' and descuento:
        raise ValueError('El descuento de intereses se registra mediante un acuerdo de saldo y cuotas.')
    nuevo = saldo - pago - descuento
    observaciones = (form.get('observaciones') or '').strip()
    if opcion == 'acuerdo' and not observaciones:
        raise ValueError('Describa el acuerdo y el motivo del descuento de intereses.')

    pagos = o.pagos.all()
    if any(p.fecha_pago and p.fecha_pago > fecha and p.estado in ('pagado', 'parcial') for p in pagos):
        raise ValueError('Hay pagos posteriores a esta fecha. Revise su historial antes de registrar el abono.')
    plan = []
    cubiertos = []
    if opcion == 'acuerdo':
        fechas = form.getlist('cuota_fecha')
        valores = form.getlist('cuota_valor')
        if len(fechas) != len(valores) or len(fechas) > 600:
            raise ValueError('Revise las cuotas del acuerdo (máximo 600).')
        for fecha_texto, valor in zip(fechas, valores):
            if not fecha_texto and not valor:
                continue
            try:
                vencimiento = date.fromisoformat(fecha_texto)
            except ValueError:
                raise ValueError('Todas las cuotas deben tener una fecha válida.')
            importe = dinero(valor)
            # Los pagos del sistema son mensuales: no mezclar pago inicial y cuota restante.
            if vencimiento.replace(day=1) <= fecha.replace(day=1) or importe <= 0:
                raise ValueError('Las cuotas restantes deben ser positivas y empezar en un mes posterior al abono.')
            plan.append({'fecha': vencimiento.isoformat(), 'total': str(importe)})
        plan.sort(key=lambda f: f['fecha'])
        if len({f['fecha'][:7] for f in plan}) != len(plan):
            raise ValueError('Registre una sola cuota por mes; el sistema maneja pagos mensuales.')
        if sum((dinero(f['total']) for f in plan), Decimal(0)) != nuevo:
            raise ValueError('La suma de las cuotas restantes debe coincidir exactamente con el nuevo saldo.')
        # Conserva pagos anteriores; sólo salda su deuda residual, con snapshot para revertir.
        for p in pagos:
            if p.estado not in ('anulado', 'pagado'):
                cubiertos.append({'id': p.id, 'estado': p.estado,
                                  'valor_causado': serializar(p.valor_causado),
                                  'periodo': f'{p.anio:04d}-{p.mes:02d}'})
    else:
        if o.modalidad not in ('bancario_cuota_fija', 'credito_con_amortizacion', 'bancario_tabla_amortizacion'):
            raise ValueError('Esta modalidad no tiene amortización bancaria automática. Use el acuerdo para conservar las condiciones pactadas.')
        if (o.frecuencia_pago or 'mensual') != 'mensual':
            raise ValueError('El cálculo automático requiere cuotas mensuales. Use un acuerdo de cuotas.')
        if activo(o) and activo(o).opcion_recalculo == 'acuerdo':
            raise ValueError('El saldo de un acuerdo incluye todos los valores pactados. Registre otro acuerdo para ajustarlo.')
        if form.get('saldo_es_capital') != '1':
            raise ValueError('Confirme que el saldo corresponde a capital, sin intereses futuros incluidos.')
        if o.tasa_interes_mensual is None:
            raise ValueError('Falta la tasa mensual. Regístrela (cero si no hay intereses) o use un acuerdo.')
        tasa = Decimal(str(o.tasa_interes_mensual)) / 100
        if tasa < 0:
            raise ValueError('La tasa mensual no puede ser negativa.')
        n = o.cuotas_pendientes or 0
        if nuevo and not 0 < n <= 600:
            raise ValueError('Se necesita un plazo pendiente entre 1 y 600 cuotas.')
        from app.routes.obligaciones import _resumen_vencido_obligacion, _fechas_programadas_obligacion
        vencido = _resumen_vencido_obligacion(o, {(p.anio, p.mes): p for p in pagos},
                                            fecha.year, fecha.month, fecha)
        if vencido['total_vencido'] > 0:
            raise ValueError('Hay cuotas vencidas. Páguelas primero o inclúyalas en un acuerdo de saldo y cuotas.')
        try:
            primera = date.fromisoformat(form.get('primera_cuota', '')) if nuevo else fecha
        except ValueError:
            raise ValueError('Indique la fecha de la próxima cuota.')
        siguiente = None
        for desplazamiento in range(601 if nuevo else 0):
            periodo = _mes(fecha.replace(day=1), desplazamiento)
            registro = next((p for p in pagos if (p.anio, p.mes) == (periodo.year, periodo.month)
                             and p.estado != 'anulado'), None)
            if registro and registro.estado == 'pagado':
                continue
            fechas = _fechas_programadas_obligacion(o, periodo.year, periodo.month)
            siguiente = next((f for f in fechas if f >= fecha), None)
            if siguiente:
                break
        if nuevo and primera != siguiente:
            raise ValueError('La próxima cuota debe coincidir con el primer vencimiento pendiente del calendario vigente: '
                             + (siguiente.isoformat() if siguiente else 'sin fecha disponible') + '.')
        cuota = dinero(o.valor_cuota_fija)
        if opcion == 'reducir_cuota' and nuevo:
            cuota = (nuevo * tasa / (1 - (1 + tasa) ** (-n)) if tasa else nuevo / n).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        saldo_plan = nuevo
        for i in range(600):
            if saldo_plan <= 0:
                break
            interes = (saldo_plan * tasa).quantize(CENTAVO, rounding=ROUND_HALF_UP)
            capital = min(cuota - interes, saldo_plan)
            if opcion == 'reducir_cuota' and i == n - 1:
                capital = saldo_plan
            if capital <= 0:
                raise ValueError('La cuota vigente no alcanza a amortizar el capital. Revise cuota y tasa.')
            saldo_plan -= capital
            plan.append({'fecha': _mes(primera, i).isoformat(), 'total': str(capital + interes),
                         'capital': str(capital), 'interes': str(interes)})
        if saldo_plan > 0 or (opcion == 'reducir_plazo' and len(plan) > n):
            raise ValueError('Con esta cuota no se reduce el plazo. Revise los datos o use un acuerdo.')
        # Tablas importadas pueden contener tasas variables, seguros y otros cargos.
        if o.amortizaciones.count():
            raise ValueError('Esta obligación tiene una tabla importada. Use un acuerdo con los valores actualizados del banco para conservar seguros y demás cargos.')

    meses_plan = {f['fecha'][:7] for f in plan}
    for p in pagos:
        periodo = f'{p.anio:04d}-{p.mes:02d}'
        if p.estado in ('pagado', 'parcial') and periodo >= fecha.strftime('%Y-%m') and float(p.valor_pagado or 0) > 0:
            if periodo in meses_plan or (p.anio, p.mes) > (fecha.year, fecha.month):
                raise ValueError('El calendario se cruza con cuotas que ya tienen pagos. Revise las fechas.')
        if opcion != 'acuerdo' and periodo in meses_plan and p.estado != 'anulado':
            raise ValueError('Ya hay una cuota registrada en el nuevo calendario. Use un acuerdo o revise las causaciones.')
    return {'opcion': opcion, 'fecha': fecha.isoformat(), 'pago': str(pago),
            'descuento': str(descuento), 'saldo_anterior': str(saldo), 'saldo_nuevo': str(nuevo),
            'plan': plan, 'cubiertos': cubiertos, 'observaciones': observaciones,
            'firma': estado_firma(o), 'ultimo_abono': max((a.id for a in o.abonos_capital.all()), default=0)}


def aplicar(o, datos):
    if datos['firma'] != estado_firma(o):
        raise ValueError('La obligación cambió después de la vista previa. Revise nuevamente antes de confirmar.')
    anteriores = o.abonos_capital.all()
    if max((a.id for a in anteriores), default=0) != datos['ultimo_abono']:
        raise ValueError('Este movimiento ya fue registrado o existe otro abono. Actualice la pantalla.')
    datos = dict(datos)
    datos['antes'] = {campo: serializar(getattr(o, campo)) for campo in CAMPOS}
    plan = datos['plan']
    a = AbonoCapitalObligacion(obligacion_id=o.id, fecha_abono=date.fromisoformat(datos['fecha']),
        valor_abono=datos['pago'], saldo_anterior=datos['saldo_anterior'], saldo_nuevo=datos['saldo_nuevo'],
        opcion_recalculo=datos['opcion'], cuotas_pendientes_antes=o.cuotas_pendientes,
        cuotas_pendientes_despues=len(plan), cuota_anterior=o.valor_cuota_fija,
        cuota_nueva=plan[0]['total'] if plan else 0, observaciones=datos['observaciones'])
    db.session.add(a)
    o.saldo_actual = datos['saldo_nuevo']
    o.cuotas_totales = (o.cuotas_pagadas or 0) + len(plan)
    o.valor_cuota_fija = plan[0]['total'] if plan else 0
    o.valor_cuota_capital = plan[0].get('capital') if plan else 0
    o.valor_cuota_interes = plan[0].get('interes') if plan else 0
    if datos['opcion'] != 'acuerdo':
        o.requiere_desglose_pago = True
    o.fecha_vencimiento = date.fromisoformat(plan[-1]['fecha']) if plan else a.fecha_abono
    o.fecha_finalizacion = None if plan else a.fecha_abono
    from app.routes.obligaciones import _registrar_historial_pago_obligacion
    for anterior in datos['cubiertos']:
        p = next(p for p in o.pagos.all() if p.id == anterior['id'])
        _registrar_historial_pago_obligacion(p, 'acuerdo', datos['observaciones'])
        p.estado = 'pagado' if p.valor_pagado else 'acordado'
        p.valor_causado = p.valor_pagado or 0
        nueva = next((f for f in plan if f['fecha'][:7] == anterior['periodo']), None)
        if nueva:
            p.estado = 'pendiente'
            p.valor_causado = nueva['total']
    db.session.flush()
    # Refrescar tipos numéricos y timestamps antes de calcular la huella.
    db.session.refresh(o)
    for p in o.pagos.all():
        db.session.refresh(p)
    datos['despues_firma'] = estado_firma(o)
    a.datos_movimiento = json.dumps(datos)
    o._abono_plan_cache = a
    return a


def revertir(o, a, motivo):
    if not motivo.strip():
        raise ValueError('Indique el motivo de la reversión.')
    if not a.datos or a.revertido or activo(o).id != a.id:
        raise ValueError('Sólo se puede revertir el último abono vigente con historial completo.')
    datos = a.datos
    if datos['despues_firma'] != estado_firma(o):
        raise ValueError('Hay pagos o cambios posteriores. Deben revisarse antes de revertir este abono.')
    for campo, valor in datos['antes'].items():
        setattr(o, campo, date.fromisoformat(valor) if valor and campo.startswith('fecha_') else valor)
    from app.routes.obligaciones import _registrar_historial_pago_obligacion
    for anterior in datos['cubiertos']:
        p = next(p for p in o.pagos.all() if p.id == anterior['id'])
        _registrar_historial_pago_obligacion(p, 'reversion_acuerdo', motivo)
        p.estado = anterior['estado']
        p.valor_causado = anterior['valor_causado']
    datos['revertido'] = datetime.utcnow().isoformat()
    datos['motivo_reversion'] = motivo.strip()
    a.datos_movimiento = json.dumps(datos)
    if hasattr(o, '_abono_plan_cache'):
        del o._abono_plan_cache
