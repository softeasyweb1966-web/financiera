from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from app import db
from app.models import (
    Obligacion, PagoObligacion, HistorialPagoObligacion, Refinanciacion, AbonoCapitalObligacion,
    Tercero, Concepto, Categoria, MedioPago
)
from app.conceptos_estado import cargar_historial_conceptos, concepto_activo_en_periodo
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from sqlalchemy import func
import math
import re

obligaciones_bp = Blueprint('obligaciones', __name__, url_prefix='/obligaciones')

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
MAX_COMPROBANTE_SIZE = 5 * 1024 * 1024

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
    if ultimo_pago and ultimo_pago.valor_causado:
        return float(ultimo_pago.valor_causado)
    if ultimo_pago and ultimo_pago.valor_pagado:
        return float(ultimo_pago.valor_pagado)
    return 0


def _fuente_valor_estimado_obligacion(obligacion, ultimo_pago=None):
    if obligacion.valor_cuota_fija:
        return 'cuota_fija'
    if obligacion.valor_cuota_capital is not None or obligacion.valor_cuota_interes is not None:
        return 'desglose'
    if obligacion.interes_mensual_calculado:
        return 'interes_mensual'
    if obligacion.cuota_francesa_calculada:
        return 'cuota_francesa'
    if ultimo_pago and ultimo_pago.valor_causado:
        return 'ultimo_causado'
    if ultimo_pago and ultimo_pago.valor_pagado:
        return 'ultimo_pago'
    return 'sin_dato'


def _registrar_historial_pago_obligacion(pago, accion, motivo=None):
    historial = HistorialPagoObligacion(
        pago_obligacion_id=pago.id,
        obligacion_id=pago.obligacion_id,
        anio=pago.anio,
        mes=pago.mes,
        accion=accion,
        motivo=motivo,
        estado=pago.estado,
        valor_causado=pago.valor_causado,
        fecha_causacion=pago.fecha_causacion,
        valor_pagado=pago.valor_pagado,
        componente_capital=pago.componente_capital,
        componente_interes=pago.componente_interes,
        numero_cuota=pago.numero_cuota,
        dia_pago_reportado=pago.dia_pago_reportado,
        fecha_pago=pago.fecha_pago,
        medio_pago_id=pago.medio_pago_id,
        comprobante_nombre=pago.comprobante_nombre,
        observaciones=pago.observaciones,
    )
    db.session.add(historial)


def _revertir_impacto_pago(obligacion, pago):
    if not obligacion or pago.estado != 'pagado' or not pago.componente_capital:
        return

    if obligacion.saldo_actual is not None:
        obligacion.saldo_actual = float(obligacion.saldo_actual) + float(pago.componente_capital)
    obligacion.cuotas_pagadas = max((obligacion.cuotas_pagadas or 0) - 1, 0)


def _aplicar_impacto_pago(obligacion, pago):
    if not obligacion or pago.estado != 'pagado' or not pago.componente_capital:
        return

    if obligacion.saldo_actual is not None:
        obligacion.saldo_actual = float(obligacion.saldo_actual) - float(pago.componente_capital)
    obligacion.cuotas_pagadas = (obligacion.cuotas_pagadas or 0) + 1


def _estado_visible_pago(pago, cuota_referencia=None):
    if not pago:
        return 'sin_causar'
    if pago.estado == 'anulado':
        return 'sin_causar'

    valor_pagado = _float_or_none(pago.valor_pagado) or 0
    valor_causado = _float_or_none(pago.valor_causado)
    base = valor_causado if valor_causado is not None and valor_causado > 0 else (_float_or_none(cuota_referencia) or 0)

    # Corrige registros que quedaron como "pagado" aunque el valor no cubrio la cuota completa.
    if pago.estado == 'pagado' and base > 0 and valor_pagado > 0 and valor_pagado + 1 < base:
        return 'parcial'

    return pago.estado


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


def _aplicar_dia_pago_obligacion(obligacion, nuevo_dia):
    if not nuevo_dia:
        return

    obligacion.dia_limite_pago = nuevo_dia

    if obligacion.modalidad == 'cadena' and obligacion.fecha_inicio and (obligacion.frecuencia_pago or 'mensual').lower() != 'quincenal':
        ultimo_dia = monthrange(obligacion.fecha_inicio.year, obligacion.fecha_inicio.month)[1]
        obligacion.fecha_inicio = obligacion.fecha_inicio.replace(day=min(nuevo_dia, ultimo_dia))

    if obligacion.modalidad == 'pago_total_pactado' and obligacion.fecha_vencimiento:
        ultimo_dia = monthrange(obligacion.fecha_vencimiento.year, obligacion.fecha_vencimiento.month)[1]
        obligacion.fecha_vencimiento = obligacion.fecha_vencimiento.replace(day=min(nuevo_dia, ultimo_dia))


def _rango_mes(anio, mes):
    ultimo_dia = monthrange(anio, mes)[1]
    return date(anio, mes, 1), date(anio, mes, ultimo_dia)


def _mes_intersecta_rango(fecha_inicio, fecha_final, anio, mes):
    inicio_mes, fin_mes = _rango_mes(anio, mes)
    if fecha_inicio and fecha_inicio > fin_mes:
        return False
    if fecha_final and fecha_final < inicio_mes:
        return False
    return True


def _ajustar_fecha_al_rango_mes(fecha_programada, fecha_inicio, fecha_final, anio, mes):
    if not fecha_programada:
        return None

    inicio_mes, fin_mes = _rango_mes(anio, mes)
    fecha_ajustada = fecha_programada

    if fecha_inicio and inicio_mes <= fecha_inicio <= fin_mes and fecha_ajustada < fecha_inicio:
        fecha_ajustada = fecha_inicio

    if fecha_final and inicio_mes <= fecha_final <= fin_mes and fecha_ajustada > fecha_final:
        fecha_ajustada = fecha_final

    if fecha_ajustada < inicio_mes or fecha_ajustada > fin_mes:
        return None

    return fecha_ajustada


def _coerce_date(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(valor, fmt).date()
            except ValueError:
                continue
    return None


def _coerce_day(valor):
    try:
        dia = int(valor)
    except (TypeError, ValueError):
        return None
    return dia if 1 <= dia <= 31 else None


def _dia_base_obligacion(obligacion, fecha_inicio=None):
    dia_limite_pago = _coerce_day(obligacion.dia_limite_pago)
    if dia_limite_pago:
        return dia_limite_pago

    fecha_inicio = fecha_inicio or _coerce_date(obligacion.fecha_inicio)
    if fecha_inicio:
        return fecha_inicio.day

    return None


def _obligacion_operativa_en_periodo(obligacion, anio, mes):
    fecha_finalizacion = _coerce_date(obligacion.fecha_finalizacion)
    if not fecha_finalizacion:
        return True

    inicio_periodo, _ = _rango_mes(anio, mes)
    inicio_finalizacion = fecha_finalizacion.replace(day=1)
    return inicio_periodo <= inicio_finalizacion


def _fechas_programadas_obligacion(obligacion, anio, mes):
    inicio_mes, fin_mes = _rango_mes(anio, mes)
    fecha_inicio = _coerce_date(obligacion.fecha_inicio)
    fecha_final = _coerce_date(obligacion.fecha_vencimiento)
    dia_base_programado = _dia_base_obligacion(obligacion, fecha_inicio)

    if obligacion.modalidad == 'pago_total_pactado':
        if fecha_final and inicio_mes <= fecha_final <= fin_mes:
            return [fecha_final]
        return []

    if obligacion.modalidad == 'cadena' and fecha_inicio:
        if not _mes_intersecta_rango(fecha_inicio, fecha_final, anio, mes):
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

        dia = min(dia_base_programado or fecha_inicio.day, fin_mes.day)
        fecha_mes = _ajustar_fecha_al_rango_mes(
            date(anio, mes, dia), fecha_inicio, fecha_final, anio, mes
        )
        return [fecha_mes] if fecha_mes else []

    if dia_base_programado:
        if not _mes_intersecta_rango(fecha_inicio, fecha_final, anio, mes):
            return []
        try:
            fecha_mes = _ajustar_fecha_al_rango_mes(
                date(anio, mes, min(dia_base_programado, fin_mes.day)),
                fecha_inicio,
                fecha_final,
                anio,
                mes,
            )
        except ValueError:
            return []
        return [fecha_mes] if fecha_mes else []
    return []


def _siguiente_fecha_programada(obligacion, desde_fecha):
    fecha_inicio = _coerce_date(obligacion.fecha_inicio)
    fecha_final = _coerce_date(obligacion.fecha_vencimiento)
    dia_base_programado = _dia_base_obligacion(obligacion, fecha_inicio)

    if obligacion.modalidad == 'pago_total_pactado':
        if fecha_final and fecha_final > desde_fecha:
            return fecha_final
        return None

    if obligacion.modalidad == 'cadena' and fecha_inicio:
        frecuencia = (obligacion.frecuencia_pago or 'mensual').lower()

        if frecuencia == 'quincenal':
            actual = fecha_inicio
            while actual <= desde_fecha:
                if actual.year == 9999:
                    return None
                actual += timedelta(days=15)
            if fecha_final and actual > fecha_final:
                return None
            return actual

        actual = fecha_inicio
        dia_base = dia_limite_pago or fecha_inicio.day
        while actual <= desde_fecha:
            if actual.year == 9999 and actual.month == 12:
                return None
            siguiente_mes = actual.month + 1
            siguiente_anio = actual.year
            if siguiente_mes > 12:
                siguiente_mes = 1
                siguiente_anio += 1
            actual = date(
                siguiente_anio,
                siguiente_mes,
                min(dia_base, monthrange(siguiente_anio, siguiente_mes)[1])
            )
            if fecha_final and actual > fecha_final:
                return None
            return actual

    if dia_base_programado:
        candidato = date(
            desde_fecha.year,
            desde_fecha.month,
            min(dia_base_programado, monthrange(desde_fecha.year, desde_fecha.month)[1])
        )
        while candidato <= desde_fecha or (fecha_inicio and candidato < fecha_inicio):
            if candidato.year == 9999 and candidato.month == 12:
                return None

            siguiente_mes = candidato.month + 1
            siguiente_anio = candidato.year
            if siguiente_mes > 12:
                siguiente_mes = 1
                siguiente_anio += 1
            candidato = date(
                siguiente_anio,
                siguiente_mes,
                min(dia_base_programado, monthrange(siguiente_anio, siguiente_mes)[1])
            )
        if fecha_final and candidato > fecha_final:
            return None
        return candidato
    return None


def _obligacion_aplica_mes(obligacion, anio, mes):
    return _obligacion_operativa_en_periodo(obligacion, anio, mes) and bool(
        _fechas_programadas_obligacion(obligacion, anio, mes)
    )


def _obligacion_visible_mes(obligacion, anio, mes):
    if not _obligacion_operativa_en_periodo(obligacion, anio, mes):
        return False

    if obligacion.modalidad != 'pago_total_pactado':
        return _obligacion_aplica_mes(obligacion, anio, mes)

    fecha_pactada = _coerce_date(obligacion.fecha_vencimiento)
    if not fecha_pactada:
        return False

    fecha_inicio = _coerce_date(obligacion.fecha_inicio)
    inicio_visible = fecha_inicio.replace(day=1) if fecha_inicio else date(fecha_pactada.year, 1, 1)
    periodo = date(anio, mes, 1)
    fin_visible = fecha_pactada.replace(day=1)
    return inicio_visible <= periodo <= fin_visible


def _es_pactado_informativo_mes(obligacion, anio, mes):
    return (
        obligacion.modalidad == 'pago_total_pactado'
        and _obligacion_visible_mes(obligacion, anio, mes)
        and not _obligacion_aplica_mes(obligacion, anio, mes)
    )


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


def _periodos_hasta_obligacion(obligacion, anio_hasta, mes_hasta):
    fecha_inicio = _coerce_date(obligacion.fecha_inicio)
    cursor_anio = fecha_inicio.year if fecha_inicio else anio_hasta
    cursor_mes = fecha_inicio.month if fecha_inicio else 1

    while (cursor_anio, cursor_mes) <= (anio_hasta, mes_hasta):
        yield cursor_anio, cursor_mes
        cursor_mes += 1
        if cursor_mes > 12:
            cursor_mes = 1
            cursor_anio += 1


def _valor_deuda_periodo_obligacion(obligacion, pago, anio, mes, ultimo_pago=None):
    cuota_base = _valor_programado_mes_obligacion(obligacion, anio, mes, ultimo_pago)
    estado_visible = _estado_visible_pago(pago, cuota_base)

    if not pago or pago.estado == 'anulado':
        return float(cuota_base or 0)

    if estado_visible == 'parcial':
        valor_causado = float(pago.valor_causado or cuota_base or 0)
        valor_pagado = float(pago.valor_pagado or 0)
        return max(valor_causado - valor_pagado, 0)

    if estado_visible in ['pendiente', 'causado', 'vencido', 'sin_causar']:
        return float(pago.valor_causado or cuota_base or 0)

    return 0


def _resumen_vencido_obligacion(obligacion, pagos_por_periodo, anio_hasta, mes_hasta, hoy, ultimo_pago=None):
    total_vencido = 0
    fecha_mora_mas_antigua = None
    cuotas_vencidas = 0

    for anio_periodo, mes_periodo in _periodos_hasta_obligacion(obligacion, anio_hasta, mes_hasta):
        if not _obligacion_aplica_mes(obligacion, anio_periodo, mes_periodo):
            continue

        fechas_programadas = _fechas_programadas_obligacion(obligacion, anio_periodo, mes_periodo)
        fecha_limite = fechas_programadas[0] if fechas_programadas else None
        if not fecha_limite or fecha_limite >= hoy:
            continue

        pago = (pagos_por_periodo or {}).get((anio_periodo, mes_periodo))
        valor_deuda = _valor_deuda_periodo_obligacion(
            obligacion, pago, anio_periodo, mes_periodo, ultimo_pago
        )
        if valor_deuda <= 0:
            continue

        total_vencido += valor_deuda
        cuotas_vencidas += 1
        if not fecha_mora_mas_antigua or fecha_limite < fecha_mora_mas_antigua:
            fecha_mora_mas_antigua = fecha_limite

    return {
        'total_vencido': total_vencido,
        'cuotas_vencidas': cuotas_vencidas,
        'fecha_mora_mas_antigua': fecha_mora_mas_antigua,
        'dias_mora_mas_antigua': (fecha_mora_mas_antigua - hoy).days if fecha_mora_mas_antigua else None,
    }


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
        normalizado = _money_raw_or_none(valor)
        if normalizado in (None, ''):
            return None
        return float(normalizado)
    except (TypeError, ValueError, InvalidOperation):
        return None


def _money_raw_or_none(valor, scale=0):
    if valor in (None, ''):
        return None

    if isinstance(valor, Decimal):
        return format(valor, 'f')
    if isinstance(valor, (int, float)):
        return format(Decimal(str(valor)), 'f')

    cleaned = str(valor).strip().replace(' ', '')
    if not cleaned:
        return None

    negative = cleaned.startswith('-')
    unsigned = re.sub(r'[^0-9.,]', '', cleaned)
    if not unsigned:
        return None

    if scale == 0:
        last_dot = unsigned.rfind('.')
        last_comma = unsigned.rfind(',')
        separator_index = max(last_dot, last_comma)
        separator_count = unsigned.count('.') + unsigned.count(',')

        integer_digits = re.sub(r'\D', '', unsigned)
        if separator_index >= 0:
            tail = re.sub(r'\D', '', unsigned[separator_index + 1:])
            head = re.sub(r'\D', '', unsigned[:separator_index])
            if tail and (
                len(tail) <= 2
                or (separator_count == 1 and len(head) > 3 and set(tail) == {'0'})
            ):
                integer_digits = head or '0'

        integer_digits = integer_digits.lstrip('0') or '0'
        return ('-' if negative else '') + integer_digits

    last_dot = unsigned.rfind('.')
    last_comma = unsigned.rfind(',')
    separator_index = max(last_dot, last_comma)
    integer_digits = re.sub(r'\D', '', unsigned)
    decimal_digits = ''

    if separator_index >= 0:
        tail = re.sub(r'\D', '', unsigned[separator_index + 1:])
        head = re.sub(r'\D', '', unsigned[:separator_index])
        if tail:
            integer_digits = head or '0'
            decimal_digits = tail[:scale]

    integer_digits = integer_digits.lstrip('0') or '0'
    raw = ('-' if negative else '') + integer_digits
    if decimal_digits:
        raw += '.' + decimal_digits
    return raw


def _date_or_none(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
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


@obligaciones_bp.route('/verificar-valores')
def verificar_valores():
    anio = request.args.get('anio', date.today().year, type=int)
    obligaciones = Obligacion.query.filter_by(activo=True).order_by(Obligacion.dia_limite_pago, Obligacion.id).all()

    filas = []
    for obligacion in obligaciones:
        ultimo_pago = PagoObligacion.query.filter(
            PagoObligacion.obligacion_id == obligacion.id,
            PagoObligacion.estado.in_(['pagado', 'parcial']),
            PagoObligacion.valor_pagado.isnot(None),
            PagoObligacion.estado != 'anulado',
            db.or_(
                PagoObligacion.anio < anio,
                db.and_(PagoObligacion.anio == anio, PagoObligacion.mes <= date.today().month)
            )
        ).order_by(
            PagoObligacion.anio.desc(),
            PagoObligacion.mes.desc(),
            PagoObligacion.id.desc()
        ).first()

        cuota_guardada = None
        if obligacion.valor_cuota_fija is not None:
            cuota_guardada = float(obligacion.valor_cuota_fija)
        elif obligacion.valor_cuota_capital is not None or obligacion.valor_cuota_interes is not None:
            cuota_guardada = float(obligacion.valor_cuota_capital or 0) + float(obligacion.valor_cuota_interes or 0)

        ultimo_pagado = float(ultimo_pago.valor_pagado or 0) if ultimo_pago else 0
        estimado = _valor_estimado_obligacion(obligacion, ultimo_pago)
        fuente = _fuente_valor_estimado_obligacion(obligacion, ultimo_pago)
        ratio = (estimado / ultimo_pagado) if estimado and ultimo_pagado else None

        alerta = ''
        if ratio is not None:
            if abs(ratio - 10) < 0.2:
                alerta = 'Posible inflacion x10 frente al ultimo pago'
            elif abs(ratio - 100) < 2:
                alerta = 'Posible inflacion x100 frente al ultimo pago'
            elif ratio > 3:
                alerta = 'Estimado muy superior al ultimo pago'
        elif estimado and not ultimo_pagado and fuente in ('cuota_fija', 'desglose'):
            alerta = 'Verificar contra soporte, no hay pago historico para comparar'

        filas.append({
            'obligacion': obligacion,
            'cuota_guardada': cuota_guardada,
            'estimado': estimado,
            'fuente': fuente,
            'ultimo_pago': ultimo_pago,
            'ultimo_pagado': ultimo_pagado,
            'ratio': ratio,
            'alerta': alerta,
        })

    return render_template('obligaciones/verificar_valores.html',
                           filas=filas, anio=anio, meses=MESES)


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
            capital_inicial=_money_raw_or_none(request.form.get('capital_inicial')),
            saldo_actual=_money_raw_or_none(request.form.get('saldo_actual')) or _money_raw_or_none(request.form.get('capital_inicial')),
            tasa_interes_mensual=request.form.get('tasa_interes_mensual') or None,
            plazo_meses=request.form.get('plazo_meses') or None,
            plazo_dias=request.form.get('plazo_dias') or None,
            cuotas_totales=request.form.get('cuotas_totales') or None,
            valor_cuota_fija=_money_raw_or_none(request.form.get('valor_cuota_fija')),
            valor_cuota_capital=_money_raw_or_none(request.form.get('valor_cuota_capital')),
            valor_cuota_interes=_money_raw_or_none(request.form.get('valor_cuota_interes')),
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
                           modalidades=MODALIDADES, medios=medios, hoy=date.today())


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

        estado_solicitado = request.form.get('estado', 'activo')
        finalizar_obligacion = (
            request.form.get('finalizar_obligacion') == 'on'
            or estado_solicitado == 'finalizado'
        )
        fecha_finalizacion_valor = request.form.get('fecha_finalizacion') or None
        fecha_finalizacion = _date_or_none(fecha_finalizacion_valor)
        if fecha_finalizacion_valor and fecha_finalizacion is None:
            flash('La fecha de finalizacion no es valida.', 'danger')
            return redirect(request.url)

        obligacion.tercero_id = request.form['tercero_id']
        obligacion.concepto_id = request.form['concepto_id']
        obligacion.modalidad = request.form['modalidad']
        obligacion.capital_inicial = _money_raw_or_none(request.form.get('capital_inicial'))
        obligacion.saldo_actual = 0 if finalizar_obligacion else _money_raw_or_none(request.form.get('saldo_actual'))
        obligacion.tasa_interes_mensual = request.form.get('tasa_interes_mensual') or None
        obligacion.plazo_meses = request.form.get('plazo_meses') or None
        obligacion.plazo_dias = request.form.get('plazo_dias') or None
        obligacion.cuotas_totales = request.form.get('cuotas_totales') or None
        obligacion.valor_cuota_fija = _money_raw_or_none(request.form.get('valor_cuota_fija'))
        obligacion.valor_cuota_capital = _money_raw_or_none(request.form.get('valor_cuota_capital'))
        obligacion.valor_cuota_interes = _money_raw_or_none(request.form.get('valor_cuota_interes'))
        obligacion.fecha_inicio = request.form.get('fecha_inicio') or None
        obligacion.fecha_vencimiento = request.form.get('fecha_vencimiento') or None
        obligacion.fecha_recibe = request.form.get('fecha_recibe') or None
        obligacion.titular = request.form.get('titular', '').strip()
        obligacion.referencia = request.form.get('referencia', '').strip()
        obligacion.frecuencia_pago = request.form.get('frecuencia_pago', 'mensual')
        obligacion.requiere_desglose_pago = requiere_desglose_pago
        obligacion.dia_limite_pago = request.form.get('dia_limite_pago') or None
        obligacion.estado = 'finalizado' if finalizar_obligacion else estado_solicitado
        obligacion.fecha_finalizacion = (fecha_finalizacion or date.today()) if finalizar_obligacion else None
        obligacion.observaciones = request.form.get('observaciones', '').strip()
        if finalizar_obligacion and obligacion.cuotas_totales is not None:
            obligacion.cuotas_totales = obligacion.cuotas_pagadas or 0
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
                           modalidades=MODALIDADES, medios=medios, hoy=date.today())


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
        and _obligacion_visible_mes(o, anio, mes)
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

    pagos_hasta_mes_por_obligacion = {obligacion_id: {} for obligacion_id in obligacion_ids}
    if obligacion_ids:
        pagos_hasta_mes = PagoObligacion.query.filter(
            PagoObligacion.obligacion_id.in_(obligacion_ids),
            db.or_(
                PagoObligacion.anio < anio,
                db.and_(PagoObligacion.anio == anio, PagoObligacion.mes <= mes)
            )
        ).order_by(
            PagoObligacion.obligacion_id,
            PagoObligacion.anio,
            PagoObligacion.mes,
            PagoObligacion.id
        ).all()

        for pago_historico in pagos_hasta_mes:
            pagos_hasta_mes_por_obligacion.setdefault(pago_historico.obligacion_id, {})[
                (pago_historico.anio, pago_historico.mes)
            ] = pago_historico

    ultimos_pagos_dict = {}
    if obligacion_ids:
        pagos_historicos = PagoObligacion.query.filter(
            PagoObligacion.obligacion_id.in_(obligacion_ids),
            db.or_(
                PagoObligacion.valor_pagado.isnot(None),
                PagoObligacion.valor_causado.isnot(None),
            ),
            PagoObligacion.estado != 'anulado',
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

    # Pendientes de meses anteriores (pendiente, causado, vencido, parcial, sin_causar)
    pendientes_anteriores = []
    total_deuda_anterior = 0
    saldo_anterior_por_obligacion = {}
    saldo_anterior_parcial_por_obligacion = {}
    saldo_anterior_cuotas_por_obligacion = {}
    for o in obligaciones:
        pagos_hasta_mes = pagos_hasta_mes_por_obligacion.get(o.id, {})
        pagos_anteriores = [
            p for (anio_pago, mes_pago), p in pagos_hasta_mes.items()
            if (anio_pago, mes_pago) < (anio, mes)
        ]
        pagos_anteriores_map = {(p.anio, p.mes): p for p in pagos_anteriores}

        for d in pagos_anteriores:
            cuota_periodo = _valor_programado_mes_obligacion(
                o, d.anio, d.mes, ultimos_pagos_dict.get(o.id)
            )
            estado_visible_anterior = _estado_visible_pago(d, cuota_periodo)
            if estado_visible_anterior not in ['pendiente', 'causado', 'vencido', 'parcial', 'sin_causar']:
                continue
            valor_deuda = _valor_deuda_periodo_obligacion(
                o, d, d.anio, d.mes, ultimos_pagos_dict.get(o.id)
            )
            valor_cuota_periodo = float(d.valor_causado or _valor_programado_mes_obligacion(
                o, d.anio, d.mes, ultimos_pagos_dict.get(o.id)
            ) or 0)
            valor_abonado_periodo = float(d.valor_pagado or 0)
            total_deuda_anterior += valor_deuda
            saldo_anterior_por_obligacion[o.id] = saldo_anterior_por_obligacion.get(o.id, 0) + valor_deuda
            if estado_visible_anterior == 'parcial':
                saldo_anterior_parcial_por_obligacion[o.id] = saldo_anterior_parcial_por_obligacion.get(o.id, 0) + valor_deuda
            else:
                saldo_anterior_cuotas_por_obligacion[o.id] = saldo_anterior_cuotas_por_obligacion.get(o.id, 0) + valor_deuda
            pendientes_anteriores.append({
                'obligacion': o,
                'pago': d,
                'mes_nombre': MESES[d.mes - 1],
                'anio': d.anio,
                'valor_deuda': valor_deuda,
                'es_parcial': estado_visible_anterior == 'parcial',
                'valor_cuota': valor_cuota_periodo,
                'valor_abonado': valor_abonado_periodo,
                'descripcion': 'Saldo restante por abono parcial' if estado_visible_anterior == 'parcial' else 'Cuota pendiente',
            })

        fecha_inicio = _coerce_date(o.fecha_inicio)
        if fecha_inicio and fecha_inicio.year > anio:
            continue

        mes_inicio_revision = fecha_inicio.month if fecha_inicio and fecha_inicio.year == anio else 1
        for mes_revision in range(mes_inicio_revision, mes):
            if not _obligacion_aplica_mes(o, anio, mes_revision):
                continue

            pago_existente = pagos_anteriores_map.get((anio, mes_revision))
            if pago_existente:
                continue

            cuota_base = _valor_deuda_periodo_obligacion(
                o, pago_existente, anio, mes_revision, ultimos_pagos_dict.get(o.id)
            )
            if cuota_base <= 0:
                continue

            total_deuda_anterior += cuota_base
            saldo_anterior_por_obligacion[o.id] = saldo_anterior_por_obligacion.get(o.id, 0) + cuota_base
            saldo_anterior_cuotas_por_obligacion[o.id] = saldo_anterior_cuotas_por_obligacion.get(o.id, 0) + cuota_base
            pendientes_anteriores.append({
                'obligacion': o,
                'pago': pago_existente,
                'mes_nombre': MESES[mes_revision - 1],
                'anio': anio,
                'valor_deuda': cuota_base,
                'es_parcial': False,
                'valor_cuota': cuota_base,
                'valor_abonado': 0,
                'descripcion': 'Cuota pendiente',
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
        PagoObligacion.mes == mes,
        PagoObligacion.estado != 'anulado'
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
        es_pactado_informativo = _es_pactado_informativo_mes(o, anio, mes)
        cuota_estimado = 0 if es_pactado_informativo else _valor_programado_mes_obligacion(o, anio, mes, ultimos_pagos_dict.get(o.id))
        total_estimado_mes += cuota_estimado
        if cuota_estimado > 0:
            total_estimado_items += 1
        pago = pagos_dict.get(o.id)
        estado_item = _estado_visible_pago(pago, cuota_estimado or _valor_estimado_obligacion(o, ultimos_pagos_dict.get(o.id)))
        pago_anulado = bool(pago and pago.estado == 'anulado')
        valor_causado = 0 if pago_anulado else (float(pago.valor_causado or 0) if pago else 0)
        valor_pagado = 0 if pago_anulado else (float(pago.valor_pagado or 0) if pago else 0)

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
            'es_informativo': es_pactado_informativo,
            'valor_causado': valor_causado,
            'cuota_esperada': cuota_estimado,
            'valor_pagado': valor_pagado
        })

    esperado_mes = float(causado_mes_actual) + sin_causar_mes
    total_esperado_items = len({
        item['id'] for item in items_mes_actual
        if item['valor_causado'] > 0 or (item['estado'] in ('sin_causar', 'pendiente') and item['valor_estimado'] > 0)
    })
    pendiente_mes = float(causado_mes_actual) - float(pagado_mes_actual)
    saldo_mes = esperado_mes - float(pagado_mes_actual)
    diferencia_estimado_mes = esperado_mes - total_estimado_mes
    por_pagar_mes = max(saldo_mes, 0)
    saldo_favor_mes = abs(saldo_mes) if saldo_mes < 0 else 0
    total_por_cubrir_hoy = total_deuda_anterior + por_pagar_mes
    items_por_cubrir_mes = total_pendiente_items + sin_causar_items

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

        if not _es_pactado_informativo_mes(o, anio, mes):
            resumen_modalidades[mod]['esperado'] += _valor_programado_mes_obligacion(o, anio, mes, ultimos_pagos_dict.get(o.id))

    resumen_grupos = [v for v in resumen_modalidades.values() if v['cantidad'] > 0]

    # Tarjetas por obligación
    obligaciones_mes = []
    for o in obligaciones:
        es_informativo = _es_pactado_informativo_mes(o, anio, mes)
        cuota_esperada = _valor_programado_mes_obligacion(o, anio, mes, ultimos_pagos_dict.get(o.id))
        valor_referencia_card = _valor_estimado_obligacion(o, ultimos_pagos_dict.get(o.id)) if es_informativo else cuota_esperada
        pago = pagos_dict.get(o.id)
        estado = _estado_visible_pago(pago, cuota_esperada or valor_referencia_card)
        pago_anulado = bool(pago and pago.estado == 'anulado')
        resumen_vencido = _resumen_vencido_obligacion(
            o,
            pagos_hasta_mes_por_obligacion.get(o.id, {}),
            anio,
            mes,
            hoy,
            ultimos_pagos_dict.get(o.id)
        )

        # Valor cuota esperada
        if pago and not pago_anulado:
            if pago.valor_pagado:
                valor_mostrar = float(pago.valor_pagado)
            elif pago.valor_causado:
                valor_mostrar = float(pago.valor_causado)
            else:
                valor_mostrar = valor_referencia_card
        else:
            valor_mostrar = valor_referencia_card
        valor_causado = 0 if pago_anulado else (float(pago.valor_causado or 0) if pago else 0)
        saldo_cuota_pendiente = max((valor_causado or cuota_esperada or 0) - float(pago.valor_pagado or 0), 0) if pago and estado == 'parcial' else 0
        valor_abonado_cuota = float(pago.valor_pagado or 0) if pago and estado == 'parcial' else 0
        saldo_arrastrado_total = saldo_anterior_por_obligacion.get(o.id, 0) + saldo_cuota_pendiente
        saldo_anterior_parcial = saldo_anterior_parcial_por_obligacion.get(o.id, 0)
        saldo_anterior_cuotas = saldo_anterior_cuotas_por_obligacion.get(o.id, 0)

        valor_pago_sugerido = saldo_cuota_pendiente if estado == 'parcial' and saldo_cuota_pendiente > 0 else valor_mostrar

        # Días restantes
        dias_restantes = None
        fecha_proxima_cuota = None
        dias_proxima_cuota = None
        fechas_programadas_mes = _fechas_programadas_obligacion(o, anio, mes)
        fecha_limite_actual = fechas_programadas_mes[0] if fechas_programadas_mes else None
        esta_vencido = bool(estado != 'pagado' and resumen_vencido['total_vencido'] > 0)
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

        if es_informativo and not fecha_referencia:
            fecha_referencia = _coerce_date(o.fecha_vencimiento)
            etiqueta_fecha = 'Fecha pactada'

        dias_restantes = (fecha_referencia - hoy).days if fecha_referencia else None
        fecha_proxima_cuota = _siguiente_fecha_programada(o, hoy - timedelta(days=1))
        if fecha_proxima_cuota:
            dias_proxima_cuota = (fecha_proxima_cuota - hoy).days
            if dias_proxima_cuota < 0:
                fecha_proxima_cuota = None
                dias_proxima_cuota = None

        if esta_vencido and resumen_vencido['fecha_mora_mas_antigua']:
            fecha_referencia = resumen_vencido['fecha_mora_mas_antigua']
            dias_restantes = resumen_vencido['dias_mora_mas_antigua']
            etiqueta_fecha = 'Vencida desde'

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

        resumen_estado = 'Por causar'
        resumen_fecha_label = 'Fecha estimada'
        resumen_fecha = fecha_limite_actual or fecha_referencia
        resumen_valor_label = 'Valor estimado'
        resumen_valor = valor_referencia_card
        resumen_dias_texto = '-'
        resumen_dias_clase = 'text-muted'

        if es_informativo:
            resumen_estado = 'Informativo'
            resumen_fecha_label = 'Fecha pactada'
            resumen_fecha = fecha_referencia
            resumen_valor_label = 'Valor pactado'
            resumen_valor = valor_referencia_card
            if dias_restantes is not None:
                if dias_restantes < 0:
                    resumen_dias_texto = f'Vencido {abs(dias_restantes)}d'
                    resumen_dias_clase = 'text-danger'
                elif dias_restantes == 0:
                    resumen_dias_texto = 'Vence hoy'
                    resumen_dias_clase = 'text-warning'
                else:
                    resumen_dias_texto = f'Faltan {dias_restantes}d'
                    resumen_dias_clase = 'text-success'
        elif estado == 'pagado':
            resumen_estado = 'Pagado'
            resumen_fecha_label = 'Fecha pago'
            resumen_fecha = pago.fecha_pago if pago else None
            resumen_valor_label = 'Valor pagado'
            resumen_valor = float(pago.valor_pagado or 0) if pago else 0
            if dias_restantes is not None:
                resumen_dias_texto = f'Siguiente pago en {dias_restantes}d'
                resumen_dias_clase = 'text-success' if dias_restantes >= 0 else 'text-danger'
        elif estado == 'causado':
            resumen_estado = 'Causado'
            resumen_fecha_label = 'Fecha causacion'
            resumen_fecha = pago.fecha_causacion if pago else None
            resumen_valor_label = 'Valor causado'
            resumen_valor = float(pago.valor_causado or 0) if pago else 0
            if dias_restantes is not None:
                if dias_restantes < 0:
                    resumen_dias_texto = f'Vencido {abs(dias_restantes)}d'
                    resumen_dias_clase = 'text-danger'
                else:
                    resumen_dias_texto = f'Por vencer en {dias_restantes}d'
                    resumen_dias_clase = 'text-warning'
        elif esta_vencido:
            resumen_estado = 'Vencido'
            resumen_fecha_label = 'Mora mas antigua'
            resumen_fecha = resumen_vencido['fecha_mora_mas_antigua'] or fecha_referencia
            resumen_valor_label = 'Total vencido'
            resumen_valor = resumen_vencido['total_vencido']
            if dias_restantes is not None:
                resumen_dias_texto = f'Vencido {abs(dias_restantes)}d'
                resumen_dias_clase = 'text-danger'
        elif estado == 'parcial':
            resumen_estado = 'Parcial'
            resumen_fecha_label = 'Fecha pago'
            resumen_fecha = pago.fecha_pago if pago else None
            resumen_valor_label = 'Saldo pendiente'
            resumen_valor = saldo_cuota_pendiente if saldo_cuota_pendiente > 0 else float(pago.valor_pagado or 0) if pago else 0
            if dias_restantes is not None:
                if dias_restantes < 0:
                    resumen_dias_texto = f'Vencido {abs(dias_restantes)}d'
                    resumen_dias_clase = 'text-danger'
                else:
                    resumen_dias_texto = f'Por vencer en {dias_restantes}d'
                    resumen_dias_clase = 'text-warning'
        elif pago_anulado:
            resumen_estado = 'Anulado'
            resumen_fecha_label = 'Registro previo'
            resumen_fecha = (pago.fecha_pago or pago.fecha_causacion) if pago else None
            resumen_valor_label = 'Valor estimado'
            resumen_valor = cuota_esperada
            resumen_dias_texto = 'Registro anulado'
            resumen_dias_clase = 'text-muted'
        elif dias_restantes is not None:
            resumen_dias_texto = f'Por vencer en {dias_restantes}d' if dias_restantes >= 0 else f'Vencido {abs(dias_restantes)}d'
            resumen_dias_clase = 'text-warning' if dias_restantes >= 0 else 'text-danger'

        obligaciones_mes.append({
            'obligacion': o,
            'pago': pago,
            'estado': estado,
            'estado_visual': estado_visual,
            'es_informativo': es_informativo,
            'valor_mostrar': valor_mostrar,
            'valor_pago_sugerido': valor_pago_sugerido,
            'valor_causado': valor_causado,
            'saldo_anterior': saldo_anterior_por_obligacion.get(o.id, 0),
            'saldo_cuota_pendiente': saldo_cuota_pendiente,
            'valor_abonado_cuota': valor_abonado_cuota,
            'saldo_arrastrado_total': saldo_arrastrado_total,
            'saldo_anterior_parcial': saldo_anterior_parcial,
            'saldo_anterior_cuotas': saldo_anterior_cuotas,
            'cuota_esperada': cuota_esperada,
            'dias_restantes': dias_restantes,
            'fecha_proxima_cuota': fecha_proxima_cuota,
            'dias_proxima_cuota': dias_proxima_cuota,
            'tipo_pago': tipo_pago,
            'fecha_referencia': fecha_referencia,
            'fecha_limite_actual': fecha_limite_actual,
            'etiqueta_fecha': etiqueta_fecha,
            'esta_vencido': esta_vencido,
            'total_vencido': resumen_vencido['total_vencido'],
            'cuotas_vencidas': resumen_vencido['cuotas_vencidas'],
            'fecha_mora_mas_antigua': resumen_vencido['fecha_mora_mas_antigua'],
            'es_estimado': (pago_anulado or not pago or not (pago.valor_causado or pago.valor_pagado)) and not esta_vencido,
            'capital_pagado_total': capital_pagado_total,
            'interes_pagado_total': interes_pagado_total,
            'pendiente_total': pendiente_total,
            'saldo_anterior': saldo_anterior_por_obligacion.get(o.id, 0),
            'fecha_ultimo_pago': fecha_ultimo_pago,
            'dias_ultimo_pago': dias_ultimo_pago,
            'pago_anulado': pago_anulado,
            'resumen_estado': resumen_estado,
            'resumen_fecha_label': resumen_fecha_label,
            'resumen_fecha': resumen_fecha,
            'resumen_valor_label': resumen_valor_label,
            'resumen_valor': resumen_valor,
            'resumen_dias_texto': resumen_dias_texto,
            'resumen_dias_clase': resumen_dias_clase,
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
        1 if item['estado'] == 'pagado' else 2 if item.get('es_informativo') else 0,
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
                           pendiente_mes=pendiente_mes,
                           total_pagado_items=total_pagado_items,
                           total_pendiente_items=total_pendiente_items,
                           saldo_mes=saldo_mes,
                           diferencia_estimado_mes=diferencia_estimado_mes,
                           por_pagar_mes=por_pagar_mes,
                           saldo_favor_mes=saldo_favor_mes,
                           total_por_cubrir_hoy=total_por_cubrir_hoy,
                           items_por_cubrir_mes=items_por_cubrir_mes,
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
    valor_causado = _money_raw_or_none(request.form.get('valor_causado'))
    valor_pagado = _money_raw_or_none(request.form.get('valor_pagado'))
    componente_capital = _money_raw_or_none(request.form.get('componente_capital'))
    componente_interes = _money_raw_or_none(request.form.get('componente_interes'))
    estado = request.form.get('estado', 'pagado')
    medio_pago_id = request.form.get('medio_pago_id') or None
    fecha_pago = request.form.get('fecha_pago') or None
    dia_pago_reportado, error_dia = _resolver_dia_pago(
        request.form.get('dia_pago_reportado')
    )
    if accion == 'causar' and error_dia:
        flash(error_dia, 'danger')
        return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))
    if accion == 'causar' and dia_pago_reportado is None:
        flash('Al causar debe registrar el dia de pago.', 'danger')
        return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))

    comprobante_nombre, comprobante_mime, comprobante_archivo, error_comprobante = _leer_comprobante(
        request.files.get('comprobante')
    )
    if accion == 'pagar' and error_comprobante:
        flash(error_comprobante, 'danger')
        return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))

    observaciones = request.form.get('observaciones', '').strip()
    valor_causado_num = _float_or_none(valor_causado)
    valor_pagado_num = _float_or_none(valor_pagado)
    componente_capital_num = _float_or_none(componente_capital)
    componente_interes_num = _float_or_none(componente_interes)

    pago = PagoObligacion.query.filter_by(
        obligacion_id=obligacion_id, anio=anio, mes=mes
    ).first()

    if not pago and not _obligacion_aplica_mes(obligacion, anio, mes):
        flash('Esta obligacion no aplica en ese mes porque aun no habia iniciado o ya no estaba vigente.', 'danger')
        return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))

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

        base_estado = valor_causado_num
        if base_estado is None and pago and pago.valor_causado is not None:
            base_estado = float(pago.valor_causado or 0)
        if base_estado is None:
            base_estado = _valor_programado_mes_obligacion(obligacion, anio, mes)

        if estado in ('pagado', 'parcial') and valor_pagado_num is not None and valor_pagado_num > 0:
            if base_estado and valor_pagado_num + 1 < base_estado:
                estado = 'parcial'
            elif estado == 'parcial' and (not base_estado or valor_pagado_num + 1 >= base_estado):
                estado = 'pagado'

    if pago:
        _registrar_historial_pago_obligacion(pago, 'ajuste', observaciones or None)
        _revertir_impacto_pago(obligacion, pago)
        if accion == 'causar':
            pago.valor_causado = valor_causado
            pago.dia_pago_reportado = dia_pago_reportado
            pago.fecha_causacion = date.today()
            if pago.estado in ('sin_causar', 'anulado'):
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
            if comprobante_archivo:
                pago.comprobante_nombre = comprobante_nombre
                pago.comprobante_mime = comprobante_mime
                pago.comprobante_archivo = comprobante_archivo
        pago.observaciones = observaciones
    else:
        numero_cuota = (obligacion.cuotas_pagadas or 0) + 1 if obligacion else None
        if accion == 'causar':
            pago = PagoObligacion(
                obligacion_id=obligacion_id, anio=anio, mes=mes,
                valor_causado=valor_causado, estado='causado',
                dia_pago_reportado=dia_pago_reportado,
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
                fecha_pago=fecha_pago, observaciones=observaciones,
                comprobante_nombre=comprobante_nombre,
                comprobante_mime=comprobante_mime,
                comprobante_archivo=comprobante_archivo
            )
        db.session.add(pago)

    if accion == 'causar' and dia_pago_reportado:
        _aplicar_dia_pago_obligacion(obligacion, dia_pago_reportado)

    # Actualizar saldo y cuotas de la obligación si se pagó
    if accion == 'pagar':
        _aplicar_impacto_pago(obligacion, pago)

    db.session.commit()
    flash('Registro actualizado.', 'success')
    return redirect(url_for('obligaciones.pagos', anio=anio, mes=mes))


@obligaciones_bp.route('/pago/<int:pago_id>/comprobante')
def descargar_comprobante(pago_id):
    pago = PagoObligacion.query.get_or_404(pago_id)
    if not pago.comprobante_archivo:
        flash('Este pago no tiene comprobante adjunto.', 'warning')
        return redirect(request.referrer or url_for('obligaciones.detalle', id=pago.obligacion_id, anio=pago.anio))

    return send_file(
        BytesIO(pago.comprobante_archivo),
        mimetype=pago.comprobante_mime or 'application/octet-stream',
        download_name=pago.comprobante_nombre or f'comprobante_obligacion_{pago.id}',
        as_attachment=False
    )


@obligaciones_bp.route('/pago/<int:pago_id>/comprobante', methods=['POST'])
def actualizar_comprobante(pago_id):
    pago = PagoObligacion.query.get_or_404(pago_id)
    comprobante_nombre, comprobante_mime, comprobante_archivo, error_comprobante = _leer_comprobante(
        request.files.get('comprobante')
    )
    if error_comprobante:
        flash(error_comprobante, 'danger')
        return redirect(url_for('obligaciones.pagos', anio=pago.anio, mes=pago.mes))
    if not comprobante_archivo:
        flash('Debe seleccionar un recibo para adjuntar.', 'danger')
        return redirect(url_for('obligaciones.pagos', anio=pago.anio, mes=pago.mes))

    pago.comprobante_nombre = comprobante_nombre
    pago.comprobante_mime = comprobante_mime
    pago.comprobante_archivo = comprobante_archivo
    db.session.commit()
    flash('Recibo adjuntado correctamente.', 'success')
    return redirect(url_for('obligaciones.pagos', anio=pago.anio, mes=pago.mes))


@obligaciones_bp.route('/pago/<int:pago_id>/anular', methods=['POST'])
def anular_pago(pago_id):
    pago = PagoObligacion.query.get_or_404(pago_id)
    motivo = (request.form.get('motivo') or '').strip()
    if not motivo:
        flash('Debe indicar el motivo de la anulacion.', 'danger')
        return redirect(request.form.get('next') or url_for('obligaciones.pagos', anio=pago.anio, mes=pago.mes))

    if pago.estado == 'anulado':
        flash('Este pago ya estaba anulado.', 'warning')
        return redirect(request.form.get('next') or url_for('obligaciones.pagos', anio=pago.anio, mes=pago.mes))

    _registrar_historial_pago_obligacion(pago, 'anulacion', motivo)
    _revertir_impacto_pago(pago.obligacion, pago)
    pago.estado = 'causado' if pago.valor_causado else 'sin_causar'
    pago.valor_pagado = None
    pago.componente_capital = None
    pago.componente_interes = None
    pago.fecha_pago = None
    pago.medio_pago_id = None
    pago.comprobante_nombre = None
    pago.comprobante_mime = None
    pago.comprobante_archivo = None
    marca = f'ANULADO {date.today().strftime("%d/%m/%Y")}: {motivo}'
    pago.observaciones = f'{pago.observaciones}\n{marca}'.strip() if pago.observaciones else marca

    db.session.commit()
    flash('Pago anulado. La cuota volvio a estado pendiente y el historial se conservo.', 'success')
    return redirect(request.form.get('next') or url_for('obligaciones.pagos', anio=pago.anio, mes=pago.mes))


@obligaciones_bp.route('/pago/<int:pago_id>/ajustar', methods=['POST'])
def ajustar_pago_cancelado(pago_id):
    pago = PagoObligacion.query.get_or_404(pago_id)
    obligacion = pago.obligacion

    if pago.estado not in ('pagado', 'parcial'):
        flash('Solo se pueden ajustar cuotas que ya fueron registradas como pagadas o parciales.', 'warning')
        return redirect(request.form.get('next') or url_for('obligaciones.refinanciaciones', id=pago.obligacion_id))

    motivo = (request.form.get('motivo') or '').strip()
    if not motivo:
        flash('Debe indicar el motivo del ajuste para conservar el historial.', 'danger')
        return redirect(request.form.get('next') or url_for('obligaciones.refinanciaciones', id=pago.obligacion_id))

    valor_pagado = _money_raw_or_none(request.form.get('valor_pagado'))
    valor_causado = _money_raw_or_none(request.form.get('valor_causado'))
    componente_capital = _money_raw_or_none(request.form.get('componente_capital'))
    componente_interes = _money_raw_or_none(request.form.get('componente_interes'))
    medio_pago_id = request.form.get('medio_pago_id') or None
    fecha_pago = _date_or_none(request.form.get('fecha_pago'))
    observaciones = (request.form.get('observaciones') or '').strip()

    valor_pagado_num = _float_or_none(valor_pagado)
    valor_causado_num = _float_or_none(valor_causado)
    componente_capital_num = _float_or_none(componente_capital)
    componente_interes_num = _float_or_none(componente_interes)

    if valor_pagado_num is None or valor_pagado_num <= 0:
        flash('El valor pagado ajustado debe ser mayor que cero.', 'danger')
        return redirect(request.form.get('next') or url_for('obligaciones.refinanciaciones', id=pago.obligacion_id))

    if not fecha_pago:
        flash('Debe indicar una fecha de pago valida.', 'danger')
        return redirect(request.form.get('next') or url_for('obligaciones.refinanciaciones', id=pago.obligacion_id))

    requiere_desglose = bool(
        obligacion.requiere_desglose_pago
        or pago.componente_capital is not None
        or pago.componente_interes is not None
        or componente_capital_num is not None
        or componente_interes_num is not None
    )
    if requiere_desglose:
        if componente_capital_num is None or componente_interes_num is None:
            flash('Esta cuota requiere ajustar capital e interes junto con el valor pagado.', 'danger')
            return redirect(request.form.get('next') or url_for('obligaciones.refinanciaciones', id=pago.obligacion_id))
        if abs((componente_capital_num or 0) + (componente_interes_num or 0) - valor_pagado_num) > 1:
            flash('La suma de capital e interes debe coincidir con el valor pagado ajustado.', 'danger')
            return redirect(request.form.get('next') or url_for('obligaciones.refinanciaciones', id=pago.obligacion_id))

    _registrar_historial_pago_obligacion(pago, 'ajuste', motivo)
    _revertir_impacto_pago(obligacion, pago)

    pago.valor_pagado = valor_pagado
    pago.fecha_pago = fecha_pago
    pago.medio_pago_id = medio_pago_id
    pago.observaciones = observaciones
    if valor_causado_num is not None:
        pago.valor_causado = valor_causado
    if requiere_desglose:
        pago.componente_capital = componente_capital
        pago.componente_interes = componente_interes

    _aplicar_impacto_pago(obligacion, pago)

    db.session.commit()
    flash('Cuota ajustada conservando el historial anterior.', 'success')
    return redirect(request.form.get('next') or url_for('obligaciones.refinanciaciones', id=pago.obligacion_id))


@obligaciones_bp.route('/detalle/<int:id>')
def detalle(id):
    """Vista detalle de una obligación: historial de todos los meses del año"""
    obligacion = Obligacion.query.get_or_404(id)
    anio = request.args.get('anio', date.today().year, type=int)
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    pagos = PagoObligacion.query.filter_by(obligacion_id=id, anio=anio).order_by(PagoObligacion.mes).all()
    historial_pagos = HistorialPagoObligacion.query.filter_by(obligacion_id=id, anio=anio).order_by(
        HistorialPagoObligacion.created_at.desc(),
        HistorialPagoObligacion.id.desc()
    ).all()
    pagos_dict = {p.mes: p for p in pagos}
    meses_aplicables = {mes: _obligacion_aplica_mes(obligacion, anio, mes) for mes in range(1, 13)}
    return render_template('obligaciones/detalle.html',
                           obligacion=obligacion, anio=anio,
                           meses=MESES, pagos=pagos_dict, medios=medios,
                           meses_aplicables=meses_aplicables,
                           historial_pagos=historial_pagos)


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
    pagos_cancelados = PagoObligacion.query.filter(
        PagoObligacion.obligacion_id == id,
        PagoObligacion.estado.in_(['pagado', 'parcial'])
    ).order_by(
        PagoObligacion.anio.desc(),
        PagoObligacion.mes.desc(),
        PagoObligacion.fecha_pago.desc(),
        PagoObligacion.id.desc()
    ).all()
    historial_pagos = HistorialPagoObligacion.query.filter_by(obligacion_id=id).order_by(
        HistorialPagoObligacion.created_at.desc(),
        HistorialPagoObligacion.id.desc()
    ).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()

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
                           pagos_cancelados=pagos_cancelados,
                           historial_pagos=historial_pagos,
                           medios=medios,
                           meses=MESES,
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
        valor_abono = float(_money_raw_or_none(request.form.get('valor_abono')) or 0)
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
        valor_refinanciado=_money_raw_or_none(request.form.get('valor_refinanciado')),
        nueva_tasa_mensual=request.form.get('nueva_tasa_mensual') or None,
        nuevo_plazo_meses=request.form.get('nuevo_plazo_meses') or None,
        nuevo_valor_cuota=_money_raw_or_none(nuevo_valor_cuota),
        nuevo_valor_cuota_capital=_money_raw_or_none(nuevo_valor_cuota_capital),
        nuevo_valor_cuota_interes=_money_raw_or_none(nuevo_valor_cuota_interes),
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
