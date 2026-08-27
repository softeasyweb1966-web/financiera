from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app import db
from app.models import (
    Empleado, Tercero, TipoTercero, RegistroNomina,
    ConceptoNomina, MedioPago, HistorialEstado, SaldoAnteriorNomina,
    HistorialSalario, AbonoNomina
)
from datetime import date, datetime
import calendar
import json

nomina_bp = Blueprint('nomina', __name__, url_prefix='/nomina')

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
FORMAS_PAGO = [
    ('diaria', 'Diaria'),
    ('semanal', 'Semanal'),
    ('quincenal', 'Quincenal'),
    ('mensual', 'Mensual'),
]
FORMAS_PAGO_LABELS = dict(FORMAS_PAGO)
ESTADOS_EMPLEADO = ['activo', 'inactivo', 'retirado', 'anulado']
ESTADOS_EMPLEADO_LABELS = {
    'activo': 'Activo',
    'inactivo': 'Inactivo',
    'retirado': 'Retirado',
    'anulado': 'Anulado',
}
NOMINA_INICIO_ANIO = 2026
NOMINA_INICIO_MES = 1
NOMINA_INICIO_QUINCENA = 1


def _preliquidacion_session_key(anio, mes, quincena):
    return f'nomina_preliquidacion_{anio}_{mes}_{quincena}'


def _periodo_nomina_clave(anio, mes, quincena=0):
    return (anio * 1000) + (mes * 10) + quincena


def _meses_habilitados_nomina(anio):
    if anio < NOMINA_INICIO_ANIO:
        return []
    mes_inicial = NOMINA_INICIO_MES if anio == NOMINA_INICIO_ANIO else 1
    return list(range(mes_inicial, 13))


def _normalizar_periodo_nomina(anio, mes, quincena=1):
    mes = min(max(int(mes or 1), 1), 12)
    quincena = quincena if quincena in (1, 2) else 1
    if anio < NOMINA_INICIO_ANIO:
        return NOMINA_INICIO_ANIO, NOMINA_INICIO_MES, quincena
    if anio == NOMINA_INICIO_ANIO and mes < NOMINA_INICIO_MES:
        return anio, NOMINA_INICIO_MES, quincena
    return anio, mes, quincena


def _periodo_es_anterior_al_inicio_nomina(anio, mes, quincena):
    return _periodo_nomina_clave(anio, mes, quincena) < _periodo_nomina_clave(
        NOMINA_INICIO_ANIO, NOMINA_INICIO_MES, NOMINA_INICIO_QUINCENA
    )


def _periodo_actual_nomina_clave():
    hoy = date.today()
    quincena = 1 if hoy.day <= 15 else 2
    return _periodo_nomina_clave(hoy.year, hoy.month, quincena)


def _date_or_none(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


def _normalizar_forma_pago_nomina(forma_pago):
    forma = (forma_pago or 'quincenal')
    if not isinstance(forma, str):
        forma = str(forma)
    forma = forma.strip().lower().replace(' ', '_')
    equivalencias = {
        'prestacion_servicios': 'prestacion_servicios',
        'prestacion-de-servicios': 'prestacion_servicios',
        'mensualidad': 'mensual',
        'quincena': 'quincenal',
        'mes': 'mensual',
        'semana': 'semanal',
        'dia': 'diaria',
    }
    return equivalencias.get(forma, forma or 'quincenal')


def _normalizar_tipo_contrato_nomina(tipo_contrato):
    tipo = (tipo_contrato or '')
    if not isinstance(tipo, str):
        tipo = str(tipo)
    tipo = tipo.strip().lower().replace(' ', '_').replace('-', '_')
    equivalencias = {
        'obra_labor': 'obra_labor',
        'obra__labor': 'obra_labor',
    }
    return equivalencias.get(tipo, tipo)


def _nombre_concepto_nomina(concepto):
    return ((concepto.nombre if concepto else '') or '').strip().lower()


def _es_concepto_base_nomina(concepto):
    return _nombre_concepto_nomina(concepto) in ('salario', 'honorarios')


def _concepto_base_preferido_nombre(empleado):
    if _es_contrato_prestacion_servicios_nomina(empleado):
        return 'honorarios'
    return 'salario'


def _es_contrato_prestacion_servicios_nomina(empleado_o_tipo):
    tipo = getattr(empleado_o_tipo, 'tipo_contrato', empleado_o_tipo)
    return _normalizar_tipo_contrato_nomina(tipo) == 'prestacion_servicios'


def _es_contrato_obra_labor_nomina(empleado_o_tipo):
    tipo = getattr(empleado_o_tipo, 'tipo_contrato', empleado_o_tipo)
    return _normalizar_tipo_contrato_nomina(tipo) == 'obra_labor'


def _ultimo_valor_pagado_obra_labor(empleado, anio, mes, quincena):
    if not empleado or not getattr(empleado, 'id', None):
        return 0

    cache = getattr(empleado, '_obra_labor_referencia_cache', None)
    if cache is None:
        cache = {}
        setattr(empleado, '_obra_labor_referencia_cache', cache)

    cache_key = (anio, mes, quincena)
    if cache_key in cache:
        return cache[cache_key]

    periodo_limite = _periodo_nomina_clave(anio, mes, quincena)
    periodos = set()

    registros_periodo = RegistroNomina.query.filter(
        RegistroNomina.empleado_id == empleado.id
    ).with_entities(
        RegistroNomina.anio,
        RegistroNomina.mes,
        RegistroNomina.quincena
    ).all()
    for anio_reg, mes_reg, quincena_reg in registros_periodo:
        if _periodo_nomina_clave(anio_reg, mes_reg, quincena_reg) < periodo_limite:
            periodos.add((anio_reg, mes_reg, quincena_reg))

    abonos_periodo = AbonoNomina.query.filter(
        AbonoNomina.empleado_id == empleado.id,
        AbonoNomina.saldo_anterior_nomina_id.is_(None)
    ).with_entities(
        AbonoNomina.anio,
        AbonoNomina.mes,
        AbonoNomina.quincena
    ).all()
    for anio_abo, mes_abo, quincena_abo in abonos_periodo:
        if _periodo_nomina_clave(anio_abo, mes_abo, quincena_abo) < periodo_limite:
            periodos.add((anio_abo, mes_abo, quincena_abo))

    valor_referencia = 0
    for anio_ref, mes_ref, quincena_ref in sorted(
        periodos,
        key=lambda periodo: _periodo_nomina_clave(*periodo),
        reverse=True
    ):
        resumen = _resumen_pago_periodo_nomina(empleado.id, anio_ref, mes_ref, quincena_ref)
        valor_pagado = float(resumen['total_pagado'] or 0)
        if valor_pagado > 0:
            valor_referencia = valor_pagado
            break

    cache[cache_key] = valor_referencia
    return valor_referencia


def _ordenar_empleados_catalogo(empleados):
    prioridad_estado = {
        'activo': 0,
        'inactivo': 1,
        'retirado': 2,
        'anulado': 3,
    }
    return sorted(
        empleados,
        key=lambda e: (
            0 if e.activo else 1,
            prioridad_estado.get((e.estado or 'activo').lower(), 9),
            (e.cargo or '').lower(),
            (e.nombre or '').lower(),
            e.id or 0,
        )
    )


def _registrar_cambio_estado_empleado(empleado, nuevo_estado, fecha_cambio, motivo):
    estado_anterior = (empleado.estado or 'activo').lower()
    if nuevo_estado == estado_anterior:
        return False

    historial = HistorialEstado(
        entidad='empleado',
        entidad_id=empleado.id,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado,
        fecha_cambio=datetime.combine(fecha_cambio, datetime.min.time()),
        motivo=motivo,
        vigencia_desde=fecha_cambio,
    )
    db.session.add(historial)
    empleado.estado = nuevo_estado
    empleado.activo = (nuevo_estado == 'activo')
    empleado.fecha_retiro = None if nuevo_estado == 'activo' else fecha_cambio
    return True


def _saldos_anteriores_manuales_hasta(empleado_id, anio, mes, quincena):
    return SaldoAnteriorNomina.query.filter(
        SaldoAnteriorNomina.empleado_id == empleado_id,
        SaldoAnteriorNomina.estado.in_(['pendiente', 'parcial']),
        SaldoAnteriorNomina.saldo_pendiente > 0,
        db.or_(
            SaldoAnteriorNomina.anio < anio,
            db.and_(
                SaldoAnteriorNomina.anio == anio,
                db.or_(
                    SaldoAnteriorNomina.mes < mes,
                    db.and_(
                        SaldoAnteriorNomina.mes == mes,
                        SaldoAnteriorNomina.quincena < quincena
                    )
                )
            )
        )
    ).order_by(
        SaldoAnteriorNomina.anio,
        SaldoAnteriorNomina.mes,
        SaldoAnteriorNomina.quincena,
        SaldoAnteriorNomina.id
    )


def _aplicar_saldos_anteriores_manuales(empleado_id, monto, fecha_pago=None, medio_pago_id=None, descripcion=None):
    monto_restante = float(monto or 0)
    total_aplicado = 0
    if monto_restante <= 0:
        return 0

    saldos = SaldoAnteriorNomina.query.filter(
        SaldoAnteriorNomina.empleado_id == empleado_id,
        SaldoAnteriorNomina.estado.in_(['pendiente', 'parcial']),
        SaldoAnteriorNomina.saldo_pendiente > 0
    ).order_by(
        SaldoAnteriorNomina.anio,
        SaldoAnteriorNomina.mes,
        SaldoAnteriorNomina.quincena,
        SaldoAnteriorNomina.id
    ).all()

    for saldo in saldos:
        if monto_restante <= 0:
            break
        pendiente = float(saldo.saldo_pendiente or 0)
        if pendiente <= 0:
            continue
        aplicado = min(pendiente, monto_restante)
        saldo.saldo_pendiente = pendiente - aplicado
        saldo.estado = 'pagado' if float(saldo.saldo_pendiente or 0) <= 0 else 'parcial'
        if fecha_pago:
            _registrar_abono_nomina(
                empleado_id=empleado_id,
                saldo_anterior_nomina_id=saldo.id,
                anio=saldo.anio,
                mes=saldo.mes,
                quincena=saldo.quincena,
                valor_abono=aplicado,
                fecha_pago=fecha_pago,
                medio_pago_id=medio_pago_id,
                descripcion=descripcion
            )
        total_aplicado += aplicado
        monto_restante -= aplicado

    return total_aplicado


def _append_observacion(texto_actual, nueva_linea):
    nueva_linea = (nueva_linea or '').strip()
    if not nueva_linea:
        return texto_actual
    if not texto_actual:
        return nueva_linea
    if nueva_linea in texto_actual:
        return texto_actual
    return f'{texto_actual}\n{nueva_linea}'


def _nota_pago_historico_nomina(valor_aplicado, fecha_pago, medio_pago=None, observaciones=None):
    partes = [
        f'Pago saldo historico: ${float(valor_aplicado or 0):,.0f}',
        f'fecha {fecha_pago.strftime("%d/%m/%Y")}',
    ]
    if medio_pago:
        partes.append(f'medio {medio_pago.nombre}')
    if observaciones:
        partes.append(observaciones.strip())
    return ' | '.join(partes)


def _nota_pago_periodo_nomina(valor_aplicado, fecha_pago, medio_pago=None, observaciones=None):
    partes = [
        f'Pago quincena: ${float(valor_aplicado or 0):,.0f}',
        f'fecha {fecha_pago.strftime("%d/%m/%Y")}',
    ]
    if medio_pago:
        partes.append(f'medio {medio_pago.nombre}')
    if observaciones:
        partes.append(observaciones.strip())
    return ' | '.join(partes)


def _registrar_abono_nomina(empleado_id, anio, mes, quincena, valor_abono, fecha_pago,
                            medio_pago_id=None, descripcion=None, saldo_anterior_nomina_id=None):
    valor_abono = float(valor_abono or 0)
    if valor_abono <= 0 or not fecha_pago:
        return None

    existente = AbonoNomina.query.filter_by(
        empleado_id=empleado_id,
        saldo_anterior_nomina_id=saldo_anterior_nomina_id,
        anio=anio,
        mes=mes,
        quincena=quincena,
        fecha_pago=fecha_pago,
        medio_pago_id=medio_pago_id,
        descripcion=descripcion
    ).filter(
        AbonoNomina.valor_abono == valor_abono
    ).first()
    if existente:
        return existente

    abono = AbonoNomina(
        empleado_id=empleado_id,
        saldo_anterior_nomina_id=saldo_anterior_nomina_id,
        anio=anio,
        mes=mes,
        quincena=quincena,
        valor_abono=valor_abono,
        fecha_pago=fecha_pago,
        medio_pago_id=medio_pago_id,
        descripcion=descripcion
    )
    db.session.add(abono)
    return abono


def _items_pago_historico_empleado(empleado, periodo_limite_clave=None):
    if periodo_limite_clave is None:
        periodo_limite_clave = _periodo_actual_nomina_clave()

    registros = RegistroNomina.query.filter_by(empleado_id=empleado.id).order_by(
        RegistroNomina.anio,
        RegistroNomina.mes,
        RegistroNomina.quincena,
        RegistroNomina.created_at,
        RegistroNomina.id
    ).all()
    registros_por_periodo = {}
    for registro in registros:
        key = (registro.anio, registro.mes, registro.quincena)
        registros_por_periodo.setdefault(key, []).append(registro)

    abonos = AbonoNomina.query.filter_by(empleado_id=empleado.id).order_by(
        AbonoNomina.anio,
        AbonoNomina.mes,
        AbonoNomina.quincena,
        AbonoNomina.fecha_pago,
        AbonoNomina.id
    ).all()
    abonos_por_periodo = {}
    abonos_por_saldo = {}
    for abono in abonos:
        key = (abono.anio, abono.mes, abono.quincena)
        abonos_por_periodo.setdefault(key, []).append(abono)
        if abono.saldo_anterior_nomina_id:
            abonos_por_saldo.setdefault(abono.saldo_anterior_nomina_id, []).append(abono)

    saldos = SaldoAnteriorNomina.query.filter(
        SaldoAnteriorNomina.empleado_id == empleado.id,
        SaldoAnteriorNomina.estado.in_(['pendiente', 'parcial']),
        SaldoAnteriorNomina.saldo_pendiente > 0
    ).order_by(
        SaldoAnteriorNomina.anio,
        SaldoAnteriorNomina.mes,
        SaldoAnteriorNomina.quincena,
        SaldoAnteriorNomina.id
    ).all()
    saldos_por_periodo = {
        (saldo.anio, saldo.mes, saldo.quincena): saldo
        for saldo in saldos
    }

    claves = set(registros_por_periodo.keys()) | set(saldos_por_periodo.keys()) | set(abonos_por_periodo.keys())
    if periodo_limite_clave:
        anio_limite = periodo_limite_clave // 1000
        mes_quincena_limite = periodo_limite_clave % 1000
        mes_limite = mes_quincena_limite // 10
        for anio in range(NOMINA_INICIO_ANIO, anio_limite + 1):
            mes_inicio = NOMINA_INICIO_MES if anio == NOMINA_INICIO_ANIO else 1
            mes_fin = mes_limite if anio == anio_limite else 12
            for mes in range(mes_inicio, mes_fin + 1):
                for quincena in (1, 2):
                    if _periodo_nomina_clave(anio, mes, quincena) >= periodo_limite_clave:
                        continue
                    if _empleado_aplica_periodo(empleado, anio, mes, quincena):
                        claves.add((anio, mes, quincena))

    items = []

    for anio, mes, quincena in sorted(claves):
        if periodo_limite_clave and _periodo_nomina_clave(anio, mes, quincena) >= periodo_limite_clave:
            continue
        if not _empleado_aplica_periodo(empleado, anio, mes, quincena):
            continue

        registros_periodo = registros_por_periodo.get((anio, mes, quincena), [])
        saldo_periodo = saldos_por_periodo.get((anio, mes, quincena))
        abonos_periodo = abonos_por_periodo.get((anio, mes, quincena), [])
        desglose = _desglose_registros_periodo_nomina(
            empleado, anio, mes, quincena, registros=registros_periodo
        )
        total_causado = float(desglose['total_causado'] or 0)
        total_abonado = sum(float(a.valor_abono or 0) for a in abonos_periodo)
        if not total_abonado and desglose['registros'] and desglose['base_pagada'] and all(
            r.fecha_pago for r in desglose['otros_registros']
        ):
            total_abonado = total_causado
        valor_deuda = 0
        valor_abonado = 0
        origen = 'nomina' if registros_periodo else 'manual'

        if registros_periodo:
            if saldo_periodo and float(saldo_periodo.saldo_pendiente or 0) > 0:
                valor_deuda = float(saldo_periodo.saldo_pendiente or 0)
                valor_abonado = max(total_causado - valor_deuda, total_abonado)
            else:
                valor_deuda = max(total_causado - total_abonado, 0)
                valor_abonado = min(total_abonado, total_causado)
        elif saldo_periodo:
            valor_deuda = float(saldo_periodo.saldo_pendiente or 0)
            valor_abonado = sum(float(a.valor_abono or 0) for a in abonos_por_saldo.get(saldo_periodo.id, []))
            if not valor_abonado and float(saldo_periodo.valor_inicial or 0) > valor_deuda:
                valor_abonado = float(saldo_periodo.valor_inicial or 0) - valor_deuda
        else:
            if _es_contrato_obra_labor_nomina(empleado):
                continue
            valor_programado = _valor_periodo_empleado(empleado, anio, mes, quincena)
            if valor_programado > 0:
                valor_deuda = valor_programado
                valor_abonado = 0

        if valor_deuda <= 0:
            continue

        items.append({
            'anio': anio,
            'mes': mes,
            'quincena': quincena,
            'periodo': f'{MESES[mes - 1]} {anio} Q{quincena}',
            'valor_deuda': valor_deuda,
            'valor_causado': total_causado,
            'valor_abonado': max(valor_abonado, 0),
            'origen': origen,
            'registros': registros_periodo,
            'abonos': abonos_periodo,
            'saldo': saldo_periodo,
            'detalle': saldo_periodo.observaciones if saldo_periodo else None,
        })

    return items


def _dias_periodo_nomina(anio, mes, quincena):
    dias_mes = calendar.monthrange(anio, mes)[1]
    return 15 if quincena == 1 else max(dias_mes - 15, 0)


def _rango_periodo_nomina(anio, mes, quincena):
    inicio_dia = 1 if quincena == 1 else 16
    fin_dia = 15 if quincena == 1 else calendar.monthrange(anio, mes)[1]
    return date(anio, mes, inicio_dia), date(anio, mes, fin_dia)


def _dias_vinculados_en_rango_nomina(empleado, fecha_inicio, fecha_fin):
    if fecha_inicio > fecha_fin:
        return 0

    inicio_efectivo = max(fecha_inicio, empleado.fecha_ingreso) if empleado.fecha_ingreso else fecha_inicio
    fin_efectivo = min(fecha_fin, empleado.fecha_retiro) if empleado.fecha_retiro else fecha_fin
    if inicio_efectivo > fin_efectivo:
        return 0
    return (fin_efectivo - inicio_efectivo).days + 1


def _empleado_aplica_periodo(empleado, anio, mes, quincena, forma_pago=None):
    periodo_inicio, periodo_fin = _rango_periodo_nomina(anio, mes, quincena)
    if empleado.fecha_ingreso and empleado.fecha_ingreso > periodo_fin:
        return False
    if empleado.fecha_retiro and empleado.fecha_retiro < periodo_inicio:
        return False
    frecuencia = _normalizar_forma_pago_nomina(forma_pago or empleado.forma_pago)
    if frecuencia == 'mensual':
        quincena_pago = empleado.quincena_pago_mensual or 2
        if quincena != quincena_pago:
            return False
    return True


def _valor_periodo_empleado(empleado, anio, mes, quincena, forma_pago=None):
    frecuencia = _normalizar_forma_pago_nomina(forma_pago or empleado.forma_pago)
    mes_inicio = date(anio, mes, 1)
    mes_fin = date(anio, mes, calendar.monthrange(anio, mes)[1])
    dias_trabajados_mes = _dias_vinculados_en_rango_nomina(empleado, mes_inicio, mes_fin)
    periodo_inicio, periodo_fin = _rango_periodo_nomina(anio, mes, quincena)
    dias_trabajados_periodo = _dias_vinculados_en_rango_nomina(empleado, periodo_inicio, periodo_fin)

    if not _empleado_aplica_periodo(empleado, anio, mes, quincena, frecuencia):
        return 0
    if _es_contrato_obra_labor_nomina(empleado):
        return _ultimo_valor_pagado_obra_labor(empleado, anio, mes, quincena)

    salario = float(empleado.salario_base or 0)
    if not salario:
        return 0
    valor_dia = salario / 30
    if frecuencia == 'mensual':
        quincena_pago = empleado.quincena_pago_mensual or 2
        return valor_dia * dias_trabajados_mes if quincena == quincena_pago else 0
    if frecuencia in ('diaria', 'semanal'):
        return valor_dia * dias_trabajados_periodo
    return valor_dia * dias_trabajados_periodo


def _concepto_base_predeterminado_empleado(empleado, conceptos):
    preferido = _concepto_base_preferido_nombre(empleado)
    conceptos = conceptos or []

    for concepto in conceptos:
        if _nombre_concepto_nomina(concepto) == preferido:
            return concepto
    for nombre in ('honorarios', 'salario'):
        for concepto in conceptos:
            if _nombre_concepto_nomina(concepto) == nombre:
                return concepto
    for concepto in conceptos:
        if (concepto.tipo or '').strip().lower() != 'deduccion':
            return concepto
    return conceptos[0] if conceptos else None


def _concepto_principal_periodo_nomina(empleado, anio, mes, quincena, conceptos, registros=None):
    if registros is None:
        registros = RegistroNomina.query.filter_by(
            empleado_id=empleado.id,
            anio=anio,
            mes=mes,
            quincena=quincena
        ).order_by(RegistroNomina.id).all()

    preferido = _concepto_base_preferido_nombre(empleado)
    registros_devengados = [
        registro for registro in (registros or [])
        if registro.concepto_nomina and (registro.concepto_nomina.tipo or '').strip().lower() != 'deduccion'
    ]

    for registro in registros_devengados:
        if _nombre_concepto_nomina(registro.concepto_nomina) == preferido:
            return registro.concepto_nomina
    for registro in registros_devengados:
        if _es_concepto_base_nomina(registro.concepto_nomina):
            return registro.concepto_nomina
    for registro in registros_devengados:
        if float(registro.valor or 0) > 0:
            return registro.concepto_nomina
    return _concepto_base_predeterminado_empleado(empleado, conceptos)


def _desglose_registros_periodo_nomina(empleado, anio, mes, quincena, registros=None):
    if registros is None:
        registros = RegistroNomina.query.filter_by(
            empleado_id=empleado.id,
            anio=anio,
            mes=mes,
            quincena=quincena
        ).order_by(RegistroNomina.id).all()

    registros = list(registros or [])
    registros_base = [registro for registro in registros if _es_concepto_base_nomina(registro.concepto_nomina)]
    nombres_base = {_nombre_concepto_nomina(registro.concepto_nomina) for registro in registros_base}
    conflicto_base = len(nombres_base) > 1
    preferido = _concepto_base_preferido_nombre(empleado)
    principal = next(
        (registro for registro in registros_base if _nombre_concepto_nomina(registro.concepto_nomina) == preferido),
        registros_base[0] if registros_base else None
    )
    valor_base_efectivo = float(principal.valor or 0) if principal else 0
    if conflicto_base and principal:
        valor_base_efectivo = _valor_periodo_empleado(empleado, anio, mes, quincena) or valor_base_efectivo

    registros_visibles = []
    conceptos_visibles = []
    otros_registros = []
    for registro in registros:
        if _es_concepto_base_nomina(registro.concepto_nomina):
            if not principal or registro.id != principal.id:
                continue
            valor_visible = valor_base_efectivo
        else:
            valor_visible = float(registro.valor or 0)
            otros_registros.append(registro)

        registros_visibles.append(registro)
        conceptos_visibles.append({
            'nombre': registro.concepto_nomina.nombre if registro.concepto_nomina else 'Concepto',
            'valor': valor_visible,
            'valor_mostrar': abs(valor_visible),
            'tipo': registro.concepto_nomina.tipo if registro.concepto_nomina else 'otro',
        })

    total_otros = sum(float(registro.valor or 0) for registro in otros_registros)
    total_causado = (valor_base_efectivo + total_otros) if principal else total_otros

    return {
        'registros': registros_visibles,
        'registros_base': registros_base,
        'otros_registros': otros_registros,
        'registro_base_principal': principal,
        'conceptos': conceptos_visibles,
        'conflicto_base': conflicto_base,
        'base_pagada': any(registro.fecha_pago for registro in registros_base) if registros_base else True,
        'total_causado': total_causado,
    }


def _normalizar_conceptos_base_periodo_nomina(anio, mes, quincena, empleado_id=None):
    return 0


def _normalizar_conceptos_base_historial_empleado(empleado, anio):
    return 0


def _resumen_pago_periodo_nomina(empleado_id, anio, mes, quincena, registros=None, abonos=None):
    empleado = Empleado.query.get(empleado_id)
    if registros is None:
        registros = RegistroNomina.query.filter_by(
            empleado_id=empleado_id,
            anio=anio,
            mes=mes,
            quincena=quincena
        ).all()
    if abonos is None:
        abonos = AbonoNomina.query.filter_by(
            empleado_id=empleado_id,
            anio=anio,
            mes=mes,
            quincena=quincena
        ).all()

    if empleado:
        desglose = _desglose_registros_periodo_nomina(empleado, anio, mes, quincena, registros=registros)
        registros_resueltos = desglose['registros']
        total_registrado = float(desglose['total_causado'] or 0)
        base_pagada = desglose['base_pagada']
        otros_pagados = all(r.fecha_pago for r in desglose['otros_registros'])
    else:
        registros_resueltos = registros
        total_registrado = sum(float(r.valor or 0) for r in registros)
        base_pagada = all(r.fecha_pago for r in registros) if registros else True
        otros_pagados = True

    total_pagado = sum(float(a.valor_abono or 0) for a in abonos)
    if total_pagado <= 0 and registros_resueltos and base_pagada and otros_pagados:
        total_pagado = total_registrado

    esta_pagado = total_registrado > 0 and total_pagado + 1 >= total_registrado
    return {
        'registros': registros_resueltos,
        'abonos': abonos,
        'total_registrado': total_registrado,
        'total_pagado': total_pagado,
        'saldo': max(total_registrado - total_pagado, 0),
        'tiene_registro': bool(registros_resueltos),
        'esta_pagado': esta_pagado,
    }


def _empleados_nomina_periodo(anio, mes, quincena, empleado_id=None, solo_activos=True):
    query = Empleado.query
    if solo_activos:
        query = query.filter_by(activo=True)
    if empleado_id:
        query = query.filter_by(id=empleado_id)
    empleados = query.order_by(Empleado.cargo, Empleado.id).all()
    return [
        empleado for empleado in empleados
        if _empleado_aplica_periodo(empleado, anio, mes, quincena)
    ]


def _pendiente_anterior_empleado(empleado, anio, mes, quincena):
    periodo_limite = _periodo_nomina_clave(anio, mes, quincena)
    return sum(float(item['valor_deuda'] or 0) for item in _items_pago_historico_empleado(empleado, periodo_limite))


def _parse_novedades_periodo(raw_payload, conceptos_dict):
    novedades = []
    total_devengados = 0
    total_deducciones = 0

    try:
        rows = json.loads(raw_payload or '[]')
    except (TypeError, ValueError):
        rows = []

    for row in rows:
        concepto_id = int(row.get('concepto_id') or 0)
        valor = float(row.get('valor') or 0)
        justificacion = (row.get('justificacion') or '').strip()
        concepto = conceptos_dict.get(concepto_id)

        if not concepto or not valor or not justificacion:
            continue

        tipo = concepto.tipo or 'otro'
        if tipo == 'deduccion':
            total_deducciones += valor
        else:
            total_devengados += valor

        novedades.append({
            'concepto_id': concepto.id,
            'concepto_nombre': concepto.nombre,
            'tipo': tipo,
            'valor': valor,
            'justificacion': justificacion
        })

    return {
        'items': novedades,
        'total_devengados': total_devengados,
        'total_deducciones': total_deducciones,
        'total_neto': total_devengados - total_deducciones,
    }


@nomina_bp.route('/')
def lista():
    empleados = Empleado.query.order_by(Empleado.activo.desc(), Empleado.cargo, Empleado.id).all()
    empleados = _ordenar_empleados_catalogo(empleados)
    anio = request.args.get('anio', date.today().year, type=int)
    if anio < NOMINA_INICIO_ANIO:
        anio = NOMINA_INICIO_ANIO
    empleados_activos = [e for e in empleados if e.activo]
    return render_template(
        'nomina/lista.html',
        empleados=empleados,
        empleados_activos_count=len(empleados_activos),
        empleados_laborales_count=sum(1 for e in empleados_activos if not _es_contrato_prestacion_servicios_nomina(e)),
        empleados_servicios_count=sum(1 for e in empleados_activos if _es_contrato_prestacion_servicios_nomina(e)),
        empleados_whatsapp_count=sum(1 for e in empleados_activos if e.autoriza_whatsapp),
        anio=anio,
        meses=MESES,
        estados_empleado=ESTADOS_EMPLEADO,
        estados_empleado_labels=ESTADOS_EMPLEADO_LABELS,
        today=date.today().strftime('%Y-%m-%d'),
    )


@nomina_bp.route('/saldos-anteriores', methods=['GET', 'POST'])
def saldos_anteriores():
    empleados = _ordenar_empleados_catalogo(
        Empleado.query.order_by(Empleado.activo.desc(), Empleado.cargo, Empleado.id).all()
    )

    if request.method == 'POST':
        total_filas = int(request.form.get('total_filas', 1))
        count_guardados = 0
        count_errores = 0

        for idx in range(total_filas):
            empleado_id = request.form.get(f'empleado_id_{idx}', type=int)
            anio = request.form.get(f'anio_{idx}', type=int)
            mes = request.form.get(f'mes_{idx}', type=int)
            quincena = request.form.get(f'quincena_{idx}', type=int)
            valor = float(request.form.get(f'valor_{idx}') or 0)
            observaciones = (request.form.get(f'observaciones_{idx}') or '').strip()

            # Validar que la fila tenga datos (puede haber sido eliminada en el frontend)
            if not empleado_id or not anio or not mes or not quincena or valor <= 0:
                continue

            empleado = Empleado.query.get(empleado_id)
            if not empleado:
                count_errores += 1
                continue

            if not _periodo_es_anterior_al_inicio_nomina(anio, mes, quincena):
                count_errores += 1
                continue

            existente = SaldoAnteriorNomina.query.filter_by(
                empleado_id=empleado.id, anio=anio, mes=mes, quincena=quincena
            ).order_by(SaldoAnteriorNomina.id.desc()).first()

            if existente and existente.estado in ('pendiente', 'parcial'):
                existente.valor_inicial = float(existente.valor_inicial or 0) + valor
                existente.saldo_pendiente = float(existente.saldo_pendiente or 0) + valor
                existente.estado = 'pendiente'
                if observaciones:
                    existente.observaciones = f'{existente.observaciones} | {observaciones}' if existente.observaciones else observaciones
            else:
                db.session.add(SaldoAnteriorNomina(
                    empleado_id=empleado.id, anio=anio, mes=mes, quincena=quincena,
                    valor_inicial=valor, saldo_pendiente=valor,
                    estado='pendiente', observaciones=observaciones or None,
                ))
            count_guardados += 1

        db.session.commit()

        if count_guardados > 0:
            flash(f'{count_guardados} saldo(s) cargado(s) correctamente.', 'success')
        if count_errores > 0:
            flash(f'{count_errores} fila(s) con errores (periodo inválido o datos faltantes).', 'warning')
        if count_guardados == 0 and count_errores == 0:
            flash('No se encontraron datos para guardar.', 'warning')

        return redirect(url_for('nomina.saldos_anteriores'))

    saldos = SaldoAnteriorNomina.query.order_by(
        SaldoAnteriorNomina.anio,
        SaldoAnteriorNomina.mes,
        SaldoAnteriorNomina.quincena,
        SaldoAnteriorNomina.id
    ).all()
    total_pendiente = sum(float(s.saldo_pendiente or 0) for s in saldos if (s.estado or 'pendiente') != 'anulado')
    return render_template(
        'nomina/saldos_anteriores.html',
        empleados=empleados,
        saldos=saldos,
        meses=MESES,
        total_pendiente=total_pendiente,
        nomina_inicio_anio=NOMINA_INICIO_ANIO,
        nomina_inicio_mes=NOMINA_INICIO_MES,
    )


@nomina_bp.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if request.method == 'POST':
        tipo_contrato = _normalizar_tipo_contrato_nomina(request.form.get('tipo_contrato', 'laboral'))
        salario_base = None if _es_contrato_obra_labor_nomina(tipo_contrato) else (request.form.get('salario_base') or None)

        # Crear tercero si no existe
        tercero_id = request.form.get('tercero_id')
        if not tercero_id:
            tipo_emp = TipoTercero.query.filter_by(nombre='Empleado').first()
            tercero = Tercero(
                tipo_tercero_id=tipo_emp.id,
                nombre=request.form['nombre'].strip().upper()
            )
            db.session.add(tercero)
            db.session.flush()
            tercero_id = tercero.id

        fecha_ingreso = _date_or_none(request.form.get('fecha_ingreso'))
        empleado = Empleado(
            tercero_id=tercero_id,
            cargo=request.form.get('cargo', '').strip(),
            salario_base=salario_base,
            tipo_contrato=tipo_contrato,
            forma_pago=_normalizar_forma_pago_nomina(request.form.get('forma_pago', 'quincenal')),
            quincena_pago_mensual=request.form.get('quincena_pago_mensual', type=int) or 2,
            whatsapp=request.form.get('whatsapp', '').strip() or None,
            autoriza_whatsapp=bool(request.form.get('autoriza_whatsapp')),
            fecha_ingreso=fecha_ingreso,
            observaciones=request.form.get('observaciones', '').strip()
        )
        db.session.add(empleado)
        db.session.commit()
        flash('Empleado creado correctamente.', 'success')
        return redirect(url_for('nomina.lista'))

    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    return render_template(
        'nomina/form.html',
        empleado=None,
        terceros=terceros,
        formas_pago=FORMAS_PAGO,
        estados_empleado=ESTADOS_EMPLEADO,
        estados_empleado_labels=ESTADOS_EMPLEADO_LABELS,
        today=date.today().strftime('%Y-%m-%d'),
    )


@nomina_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
def editar(id):
    empleado = Empleado.query.get_or_404(id)
    if request.method == 'POST':
        tipo_contrato = _normalizar_tipo_contrato_nomina(request.form.get('tipo_contrato', 'laboral'))
        nuevo_estado = (request.form.get('estado') or empleado.estado or 'activo').strip().lower()
        if nuevo_estado not in ESTADOS_EMPLEADO:
            flash('Seleccione un estado valido para el empleado.', 'danger')
            return redirect(url_for('nomina.editar', id=id))

        fecha_ingreso = _date_or_none(request.form.get('fecha_ingreso'))
        if request.form.get('fecha_ingreso') and fecha_ingreso is None:
            flash('La fecha de ingreso no es valida.', 'danger')
            return redirect(url_for('nomina.editar', id=id))

        estado_anterior = (empleado.estado or 'activo').lower()
        if nuevo_estado != estado_anterior:
            motivo_estado = (request.form.get('motivo_estado') or '').strip()
            fecha_cambio_estado = _date_or_none(request.form.get('fecha_cambio_estado'))
            if not fecha_cambio_estado:
                flash('Debe indicar la fecha del cambio de estado.', 'danger')
                return redirect(url_for('nomina.editar', id=id))
            if not motivo_estado:
                flash('Debe indicar el motivo del cambio de estado.', 'danger')
                return redirect(url_for('nomina.editar', id=id))
            _registrar_cambio_estado_empleado(empleado, nuevo_estado, fecha_cambio_estado, motivo_estado)

        # Verificar cambio de salario
        nuevo_salario_str = '' if _es_contrato_obra_labor_nomina(tipo_contrato) else request.form.get('salario_base', '').strip()
        nuevo_salario = float(nuevo_salario_str) if nuevo_salario_str else None
        salario_anterior = float(empleado.salario_base) if empleado.salario_base else None

        if (
            not _es_contrato_obra_labor_nomina(tipo_contrato)
            and nuevo_salario and salario_anterior and nuevo_salario != salario_anterior
        ):
            fecha_cambio_sal = _date_or_none(request.form.get('fecha_cambio_salario'))
            motivo_sal = (request.form.get('motivo_salario') or '').strip()
            if not fecha_cambio_sal:
                flash('Debe indicar la fecha del cambio de salario.', 'danger')
                return redirect(url_for('nomina.editar', id=id))
            if not motivo_sal:
                flash('Debe indicar el motivo del cambio de salario.', 'danger')
                return redirect(url_for('nomina.editar', id=id))
            hist_sal = HistorialSalario(
                empleado_id=id,
                salario_anterior=salario_anterior,
                salario_nuevo=nuevo_salario,
                fecha_cambio=fecha_cambio_sal,
                motivo=motivo_sal
            )
            db.session.add(hist_sal)

        empleado.cargo = request.form.get('cargo', '').strip()
        empleado.salario_base = nuevo_salario
        empleado.tipo_contrato = tipo_contrato
        empleado.forma_pago = _normalizar_forma_pago_nomina(request.form.get('forma_pago', 'quincenal'))
        empleado.quincena_pago_mensual = request.form.get('quincena_pago_mensual', type=int) or 2
        empleado.whatsapp = request.form.get('whatsapp', '').strip() or None
        empleado.autoriza_whatsapp = bool(request.form.get('autoriza_whatsapp'))
        empleado.fecha_ingreso = fecha_ingreso
        empleado.observaciones = request.form.get('observaciones', '').strip()
        db.session.commit()
        flash('Empleado actualizado.', 'success')
        return redirect(url_for('nomina.lista'))

    terceros = Tercero.query.filter_by(activo=True).order_by(Tercero.nombre).all()
    return render_template(
        'nomina/form.html',
        empleado=empleado,
        terceros=terceros,
        formas_pago=FORMAS_PAGO,
        estados_empleado=ESTADOS_EMPLEADO,
        estados_empleado_labels=ESTADOS_EMPLEADO_LABELS,
        today=date.today().strftime('%Y-%m-%d'),
    )


@nomina_bp.route('/<int:id>/historial-salarios')
def historial_salarios(id):
    empleado = Empleado.query.get_or_404(id)
    registros = HistorialSalario.query.filter_by(empleado_id=id).order_by(
        HistorialSalario.fecha_cambio.desc()
    ).all()
    return render_template('nomina/historial_salarios.html', empleado=empleado, registros=registros)


@nomina_bp.route('/<int:id>/cambiar-estado', methods=['POST'])
def cambiar_estado(id):
    empleado = Empleado.query.get_or_404(id)
    nuevo_estado = (request.form.get('estado') or '').strip().lower()
    motivo = (request.form.get('motivo') or '').strip()
    fecha_cambio = _date_or_none(request.form.get('fecha_cambio'))

    if nuevo_estado not in ESTADOS_EMPLEADO:
        flash('Seleccione un estado valido para el empleado.', 'danger')
        return redirect(url_for('nomina.lista'))
    if nuevo_estado == (empleado.estado or 'activo').lower():
        flash('El empleado ya se encuentra en ese estado.', 'warning')
        return redirect(url_for('nomina.lista'))
    if not fecha_cambio:
        flash('Debe indicar la fecha del cambio de estado.', 'danger')
        return redirect(url_for('nomina.lista'))
    if not motivo:
        flash('Debe indicar el motivo del cambio de estado.', 'danger')
        return redirect(url_for('nomina.lista'))

    _registrar_cambio_estado_empleado(empleado, nuevo_estado, fecha_cambio, motivo)
    db.session.commit()
    flash(f'Empleado "{empleado.nombre}" cambiado a {ESTADOS_EMPLEADO_LABELS.get(nuevo_estado, nuevo_estado)}.', 'success')
    return redirect(url_for('nomina.lista'))


@nomina_bp.route('/<int:id>/eliminar', methods=['POST'])
def eliminar(id):
    empleado = Empleado.query.get_or_404(id)
    nombre = empleado.nombre
    registros_eliminados = RegistroNomina.query.filter_by(empleado_id=empleado.id).delete(synchronize_session=False)
    saldos_eliminados = SaldoAnteriorNomina.query.filter_by(empleado_id=empleado.id).delete(synchronize_session=False)
    historial_eliminado = HistorialEstado.query.filter_by(entidad='empleado', entidad_id=empleado.id).delete(
        synchronize_session=False
    )
    db.session.delete(empleado)
    db.session.commit()
    flash(
        f'Empleado "{nombre}" eliminado del catalogo. '
        f'Se borraron {registros_eliminados} registros de nomina, {saldos_eliminados} saldos anteriores y {historial_eliminado} cambios de estado.',
        'success'
    )
    return redirect(url_for('nomina.lista'))


@nomina_bp.route('/saldos-anteriores/<int:id>/eliminar', methods=['POST'])
def eliminar_saldo_anterior(id):
    saldo = SaldoAnteriorNomina.query.get_or_404(id)
    db.session.delete(saldo)
    db.session.commit()
    flash('Saldo anterior eliminado.', 'success')
    return redirect(url_for('nomina.saldos_anteriores'))


@nomina_bp.route('/preliquidar', methods=['GET', 'POST'])
@nomina_bp.route('/preliquidar/<int:anio>/<int:mes>/<int:quincena>', methods=['GET', 'POST'])
def preliquidar(anio=None, mes=None, quincena=None):
    if anio is None:
        anio = request.args.get('anio', date.today().year, type=int)
    if mes is None:
        mes = request.args.get('mes', date.today().month, type=int)
    if quincena is None:
        quincena = request.args.get('quincena', 1 if date.today().day <= 15 else 2, type=int)
    anio, mes, quincena = _normalizar_periodo_nomina(anio, mes, quincena)
    meses_habilitados = _meses_habilitados_nomina(anio)

    empleados_periodo = _empleados_nomina_periodo(anio, mes, quincena)
    conceptos = ConceptoNomina.query.filter_by(activo=True).order_by(ConceptoNomina.tipo, ConceptoNomina.nombre).all()
    conceptos_dict = {c.id: c for c in conceptos}
    draft_key = _preliquidacion_session_key(anio, mes, quincena)

    if request.method == 'POST':
        draft_rows = {}
        actualizados = 0
        total_novedades_periodo = 0

        for e in empleados_periodo:
            incluir = bool(request.form.get(f'incluir_{e.id}'))
            forma_aplicada = _normalizar_forma_pago_nomina(
                request.form.get(f'forma_pago_{e.id}', e.forma_pago or 'quincenal')
            )
            valor_preliquidado = float(request.form.get(f'valor_{e.id}') or 0)
            pendiente_anterior = float(request.form.get(f'pendiente_{e.id}') or 0)
            actualizar_catalogo = bool(request.form.get(f'actualizar_catalogo_{e.id}'))
            novedades_resumen = _parse_novedades_periodo(request.form.get(f'novedades_{e.id}'), conceptos_dict)
            total_novedades_periodo += novedades_resumen['total_neto']
            total_propuesto = valor_preliquidado + pendiente_anterior + novedades_resumen['total_neto']

            draft_rows[str(e.id)] = {
                'incluir': incluir,
                'forma_pago_aplicada': forma_aplicada,
                'valor_preliquidado': valor_preliquidado,
                'pendiente_anterior': pendiente_anterior,
                'novedades': novedades_resumen['items'],
                'total_devengados': novedades_resumen['total_devengados'],
                'total_deducciones': novedades_resumen['total_deducciones'],
                'total_novedades': novedades_resumen['total_neto'],
                'total_propuesto': total_propuesto
            }

            if actualizar_catalogo and e.forma_pago != forma_aplicada:
                e.forma_pago = forma_aplicada
                actualizados += 1

        if actualizados:
            db.session.commit()

        session[draft_key] = {
            'anio': anio,
            'mes': mes,
            'quincena': quincena,
            'rows': draft_rows,
            'created_at': datetime.utcnow().isoformat()
        }
        flash('Preliquidación preparada. Ya puede continuar a la liquidación de nómina.', 'success')
        return redirect(url_for('nomina.registrar_quincena', anio=anio, mes=mes, quincena=quincena))

    draft = session.get(draft_key, {})
    rows = []
    total_estimado = 0
    total_pendiente = 0
    total_novedades_periodo = 0

    for e in empleados_periodo:
        draft_row = draft.get('rows', {}).get(str(e.id), {})
        forma_aplicada = _normalizar_forma_pago_nomina(
            draft_row.get('forma_pago_aplicada', e.forma_pago or 'quincenal')
        )
        valor_referencia = (
            _ultimo_valor_pagado_obra_labor(e, anio, mes, quincena)
            if _es_contrato_obra_labor_nomina(e)
            else float(e.salario_base or 0)
        )
        valor_preliquidado = float(
            draft_row.get('valor_preliquidado', _valor_periodo_empleado(e, anio, mes, quincena, forma_aplicada))
        )
        pendiente_anterior = float(draft_row.get('pendiente_anterior', _pendiente_anterior_empleado(e, anio, mes, quincena)))
        incluir = draft_row.get('incluir', True)
        novedades = draft_row.get('novedades', [])
        total_devengados = float(draft_row.get('total_devengados', 0))
        total_deducciones = float(draft_row.get('total_deducciones', 0))
        total_novedades = float(draft_row.get('total_novedades', 0))
        total_propuesto = valor_preliquidado + pendiente_anterior + total_novedades

        total_estimado += valor_preliquidado
        total_pendiente += pendiente_anterior
        total_novedades_periodo += total_novedades
        rows.append({
            'empleado': e,
            'forma_catalogo': e.forma_pago or 'quincenal',
            'forma_aplicada': forma_aplicada,
            'valor_preliquidado': valor_preliquidado,
            'pendiente_anterior': pendiente_anterior,
            'novedades': novedades,
            'total_devengados': total_devengados,
            'total_deducciones': total_deducciones,
            'total_novedades': total_novedades,
            'total_propuesto': total_propuesto,
            'incluir': incluir,
            'es_obra_labor': _es_contrato_obra_labor_nomina(e),
            'valor_referencia': valor_referencia,
        })

    return render_template(
        'nomina/preliquidar.html',
        empleados_preliquidacion=rows,
        conceptos_novedad=conceptos,
        anio=anio,
        mes=mes,
        quincena=quincena,
        meses=MESES,
        formas_pago=FORMAS_PAGO,
        formas_pago_labels=FORMAS_PAGO_LABELS,
        meses_habilitados=meses_habilitados,
        dias_mes=calendar.monthrange(anio, mes)[1],
        dias_periodo=_dias_periodo_nomina(anio, mes, quincena),
        total_estimado=total_estimado,
        total_pendiente=total_pendiente,
        total_novedades_periodo=total_novedades_periodo,
        total_empleados=len(rows),
        nomina_inicio_anio=NOMINA_INICIO_ANIO,
        nomina_inicio_mes=NOMINA_INICIO_MES,
    )


@nomina_bp.route('/pagos')
@nomina_bp.route('/pagos/<int:anio>')
@nomina_bp.route('/pagos/<int:anio>/<int:mes>')
@nomina_bp.route('/pagos/<int:anio>/<int:mes>/<int:quincena>')
def pagos(anio=None, mes=None, quincena=None):
    if anio is None:
        anio = date.today().year
    if mes is None:
        mes = date.today().month
    if quincena is None:
        # Default: Q1 si estamos en primera mitad del mes, Q2 si segunda
        quincena = 1 if date.today().day <= 15 else 2
    anio, mes, quincena = _normalizar_periodo_nomina(anio, mes, quincena)
    meses_habilitados = _meses_habilitados_nomina(anio)
    normalizados = _normalizar_conceptos_base_periodo_nomina(anio, mes, quincena)
    if normalizados:
        db.session.commit()

    empleados = Empleado.query.filter_by(activo=True).order_by(Empleado.cargo, Empleado.id).all()
    empleados_dict = {empleado.id: empleado for empleado in empleados}
    empleados_periodo = _empleados_nomina_periodo(anio, mes, quincena)
    empleados_periodo_ids = {e.id for e in empleados_periodo}
    conceptos = ConceptoNomina.query.filter_by(activo=True).order_by(ConceptoNomina.tipo, ConceptoNomina.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()

    # Registros de esta quincena
    registros_quincena = RegistroNomina.query.filter_by(
        anio=anio, mes=mes, quincena=quincena
    ).all()
    registros_quincena = [
        r for r in registros_quincena
        if r.empleado_id is None or r.empleado_id in empleados_periodo_ids
    ]

    # Agrupar por empleado
    registros_por_empleado = {}
    for r in registros_quincena:
        if r.empleado_id not in registros_por_empleado:
            registros_por_empleado[r.empleado_id] = []
        registros_por_empleado[r.empleado_id].append(r)

    registros_anio = RegistroNomina.query.filter_by(anio=anio).all()
    registros_anio_por_periodo = {}
    for registro in registros_anio:
        key = (registro.empleado_id, registro.mes, registro.quincena)
        registros_anio_por_periodo.setdefault(key, []).append(registro)

    abonos_anio = AbonoNomina.query.filter_by(anio=anio).all()
    abonos_anio_por_periodo = {}
    for abono in abonos_anio:
        key = (abono.empleado_id, abono.mes, abono.quincena)
        abonos_anio_por_periodo[key] = abonos_anio_por_periodo.get(key, 0) + float(abono.valor_abono or 0)

    # Acumulado pagado meses anteriores
    acum_pagado_anterior = 0
    pagado_quincena_actual = 0
    acum_empleados_dict = {}
    periodos_pago = set(registros_anio_por_periodo.keys()) | set(abonos_anio_por_periodo.keys())
    for empleado_id, mes_pago, quincena_pago in periodos_pago:
        if empleado_id is None:
            continue
        registros_periodo = registros_anio_por_periodo.get((empleado_id, mes_pago, quincena_pago), [])
        empleado_periodo = empleados_dict.get(empleado_id) or Empleado.query.get(empleado_id)
        if empleado_periodo:
            desglose_periodo = _desglose_registros_periodo_nomina(
                empleado_periodo, anio, mes_pago, quincena_pago, registros=registros_periodo
            )
            total_causado_periodo = float(desglose_periodo['total_causado'] or 0)
            base_pagada = desglose_periodo['base_pagada']
            otros_pagados = all(r.fecha_pago for r in desglose_periodo['otros_registros'])
        else:
            total_causado_periodo = sum(float(r.valor or 0) for r in registros_periodo)
            base_pagada = all(r.fecha_pago for r in registros_periodo) if registros_periodo else True
            otros_pagados = True
        total_abonado_periodo = float(abonos_anio_por_periodo.get((empleado_id, mes_pago, quincena_pago), 0) or 0)
        if total_abonado_periodo > 0:
            pagado_periodo = min(total_abonado_periodo, total_causado_periodo) if total_causado_periodo > 0 else total_abonado_periodo
        elif registros_periodo and base_pagada and otros_pagados:
            pagado_periodo = total_causado_periodo
        else:
            pagado_periodo = 0
        if pagado_periodo <= 0:
            continue
        if (mes_pago, quincena_pago) == (mes, quincena):
            pagado_quincena_actual += pagado_periodo
        elif (mes_pago < mes) or (mes_pago == mes and quincena_pago < quincena):
            acum_pagado_anterior += pagado_periodo
            acum_empleados_dict[empleado_id] = acum_empleados_dict.get(empleado_id, 0) + pagado_periodo

    # Total esperado del periodo segun la frecuencia configurada
    esperado_quincena = sum(
        _valor_periodo_empleado(e, anio, mes, quincena) for e in empleados_periodo
    )

    # Quincenas sin pagar de periodos anteriores
    pendientes_anteriores = []
    total_deuda_anterior = 0
    periodo_actual_clave = _periodo_nomina_clave(anio, mes, quincena)
    for empleado in empleados:
        for item in _items_pago_historico_empleado(empleado, periodo_actual_clave):
            valor_pendiente = float(item['valor_deuda'] or 0)
            if valor_pendiente <= 0:
                continue
            total_deuda_anterior += valor_pendiente
            pendientes_anteriores.append({
                'empleado': empleado,
                'mes_nombre': MESES[item['mes'] - 1],
                'anio': item['anio'],
                'quincena': item['quincena'],
                'valor_esperado': valor_pendiente,
                'detalle': item.get('detalle'),
                'manual': item['origen'] == 'manual',
            })

    # Resumen por concepto de nómina
    resumen_conceptos = {}

    # Tarjetas por empleado
    empleados_mes = []
    for e in empleados_periodo:
        registros_emp = registros_por_empleado.get(e.id, [])
        desglose = _desglose_registros_periodo_nomina(e, anio, mes, quincena, registros=registros_emp)
        registros_visibles = desglose['registros']
        total_registrado = float(desglose['total_causado'] or 0)
        total_pagado = float(abonos_anio_por_periodo.get((e.id, mes, quincena), 0) or 0)
        if total_pagado <= 0 and registros_visibles and desglose['base_pagada'] and all(
            r.fecha_pago for r in desglose['otros_registros']
        ):
            total_pagado = total_registrado
        tiene_registro = len(registros_visibles) > 0
        esta_pagado = total_registrado > 0 and total_pagado + 1 >= total_registrado
        aplica_periodo = _empleado_aplica_periodo(e, anio, mes, quincena)
        valor_quincena = _valor_periodo_empleado(e, anio, mes, quincena)
        tiene_saldos_historicos = bool(_items_pago_historico_empleado(e, periodo_actual_clave))

        for concepto in desglose['conceptos']:
            concepto_nombre = concepto['nombre']
            tipo = concepto['tipo']
            if concepto_nombre not in resumen_conceptos:
                resumen_conceptos[concepto_nombre] = {
                    'nombre': concepto_nombre,
                    'tipo': tipo,
                    'color': '#10b981' if tipo == 'devengado' else '#ef4444',
                    'total': 0,
                    'cantidad': 0
                }
            resumen_conceptos[concepto_nombre]['total'] += float(concepto['valor'] or 0)
            resumen_conceptos[concepto_nombre]['cantidad'] += 1

        empleados_mes.append({
            'empleado': e,
            'registros': registros_visibles,
            'total_registrado': total_registrado,
            'total_pagado': total_pagado,
            'tiene_pago': esta_pagado,
            'tiene_registro': tiene_registro,
            'aplica_periodo': aplica_periodo,
            'valor_quincena': valor_quincena,
            'tiene_saldos_historicos': tiene_saldos_historicos,
            'estado': 'pagado' if esta_pagado else 'causado' if tiene_registro else 'pendiente' if aplica_periodo else 'no_aplica',
        })

    resumen_grupos = list(resumen_conceptos.values())

    empleados_pagados_count = sum(1 for item in empleados_mes if item['tiene_pago'])
    empleados_pendientes_count = sum(1 for item in empleados_mes if item['estado'] in ('pendiente', 'causado'))
    registros_quincena_count = len(registros_quincena)

    # Acumulado pagado por empleado (para drill-down)
    acum_empleados_detalle = []
    for item in empleados_mes:
        total_acum = acum_empleados_dict.get(item['empleado'].id, 0)
        if total_acum > 0:
            acum_empleados_detalle.append({
                'empleado': item['empleado'],
                'total': total_acum
            })
    acum_empleados_detalle.sort(key=lambda item: item['total'], reverse=True)

    return render_template('nomina/pagos.html',
                           empleados_mes=empleados_mes,
                           pendientes_anteriores=pendientes_anteriores,
                           anio=anio, mes=mes, quincena=quincena, meses=MESES,
                           meses_habilitados=meses_habilitados,
                           medios=medios, conceptos=conceptos,
                           acum_pagado_anterior=float(acum_pagado_anterior),
                           acum_empleados_detalle=acum_empleados_detalle,
                           pagado_quincena_actual=float(pagado_quincena_actual),
                           esperado_quincena=esperado_quincena,
                           pendiente_quincena=esperado_quincena - float(pagado_quincena_actual),
                           total_deuda_anterior=total_deuda_anterior,
                           resumen_grupos=resumen_grupos,
                           acum_empleados_dict=acum_empleados_dict,
                           empleados_pagados_count=empleados_pagados_count,
                           empleados_pendientes_count=empleados_pendientes_count,
                           registros_quincena_count=registros_quincena_count,
                           nomina_inicio_anio=NOMINA_INICIO_ANIO,
                           nomina_inicio_mes=NOMINA_INICIO_MES)


@nomina_bp.route('/detalle/<int:id>')
def detalle(id):
    """Vista detalle de un empleado: historial de pagos del año por quincena"""
    empleado = Empleado.query.get_or_404(id)
    anio = request.args.get('anio', date.today().year, type=int)
    if anio < NOMINA_INICIO_ANIO:
        anio = NOMINA_INICIO_ANIO
    normalizados = _normalizar_conceptos_base_historial_empleado(empleado, anio)
    if normalizados:
        db.session.commit()
    meses_habilitados = _meses_habilitados_nomina(anio)
    registros = RegistroNomina.query.filter_by(empleado_id=id, anio=anio).order_by(
        RegistroNomina.mes, RegistroNomina.quincena, RegistroNomina.created_at
    ).all()
    abonos = AbonoNomina.query.filter_by(empleado_id=id, anio=anio).order_by(
        AbonoNomina.mes, AbonoNomina.quincena, AbonoNomina.fecha_pago, AbonoNomina.id
    ).all()
    # Group by (mes, quincena)
    pagos_dict = {}
    pagos_raw_dict = {}
    causaciones_dict = {}
    abonos_dict = {}
    abonos_totales = {}
    estados_quincena = {}
    aplica_quincena = {}
    for r in registros:
        key = (r.mes, r.quincena)
        pagos_raw_dict.setdefault(key, []).append(r)
        if key not in causaciones_dict and r.created_at:
            causaciones_dict[key] = r.created_at.date()
    for key, items in pagos_raw_dict.items():
        pagos_dict[key] = _desglose_registros_periodo_nomina(
            empleado, anio, key[0], key[1], registros=items
        )['registros']
    for abono in abonos:
        key = (abono.mes, abono.quincena)
        abonos_dict.setdefault(key, []).append(abono)
        abonos_totales[key] = abonos_totales.get(key, 0) + float(abono.valor_abono or 0)
    for mes in meses_habilitados:
        for quincena_check in (1, 2):
            key = (mes, quincena_check)
            aplica_quincena[key] = _empleado_aplica_periodo(empleado, anio, mes, quincena_check)
    for key, items in pagos_raw_dict.items():
        if not aplica_quincena.get(key, True):
            pagos_dict[key] = []
            estados_quincena[key] = 'no_aplica'
            continue
        desglose = _desglose_registros_periodo_nomina(empleado, anio, key[0], key[1], registros=items)
        total_causado = float(desglose['total_causado'] or 0)
        total_abonado = float(abonos_totales.get(key, 0) or 0)
        if total_abonado <= 0 and desglose['registros'] and desglose['base_pagada'] and all(
            r.fecha_pago for r in desglose['otros_registros']
        ):
            total_abonado = total_causado
        if desglose['registros'] and total_causado > 0 and total_abonado + 1 >= total_causado:
            estados_quincena[key] = 'pagado'
        elif desglose['registros']:
            mes_key, quincena_key = key
            _, periodo_fin = _rango_periodo_nomina(anio, mes_key, quincena_key)
            estados_quincena[key] = 'vencido' if periodo_fin < date.today() else 'causado'
    for key, aplica in aplica_quincena.items():
        if not aplica:
            estados_quincena[key] = 'no_aplica'
    estados_mes = {}
    for mes in meses_habilitados:
        estados_mes_actual = [
            estados_quincena.get((mes, quincena))
            for quincena in (1, 2)
            if estados_quincena.get((mes, quincena))
        ]
        if estados_mes_actual and all(estado == 'no_aplica' for estado in estados_mes_actual):
            estados_mes[mes] = 'no_aplica'
        elif 'vencido' in estados_mes_actual:
            estados_mes[mes] = 'vencido'
        elif estados_mes_actual:
            estados_mes[mes] = 'pagado' if all(estado == 'pagado' for estado in estados_mes_actual) else 'causado'
    saldos_anteriores = SaldoAnteriorNomina.query.filter_by(empleado_id=id).order_by(
        SaldoAnteriorNomina.anio, SaldoAnteriorNomina.mes, SaldoAnteriorNomina.quincena, SaldoAnteriorNomina.id
    ).all()
    saldos_pago_pendientes = _items_pago_historico_empleado(empleado, _periodo_actual_nomina_clave())
    total_saldos_pago_pendientes = sum(float(item['valor_deuda'] or 0) for item in saldos_pago_pendientes)
    return render_template('nomina/detalle_v2.html', empleado=empleado, anio=anio,
                           meses=MESES, pagos=pagos_dict, causaciones=causaciones_dict,
                           abonos=abonos_dict, abonos_totales=abonos_totales, abonos_lista=abonos,
                           meses_habilitados=meses_habilitados,
                           aplica_quincena=aplica_quincena,
                           estados_quincena=estados_quincena,
                           estados_mes=estados_mes,
                           saldos_anteriores=saldos_anteriores,
                           saldos_pago_pendientes=saldos_pago_pendientes,
                           total_saldos_pago_pendientes=total_saldos_pago_pendientes,
                           nomina_inicio_anio=NOMINA_INICIO_ANIO,
                           nomina_inicio_mes=NOMINA_INICIO_MES)


@nomina_bp.route('/<int:id>/pagar-saldos-historicos', methods=['GET', 'POST'])
def pagar_saldos_historicos_empleado(id):
    empleado = Empleado.query.get_or_404(id)
    anio_retorno = request.values.get('anio_retorno', request.values.get('anio', date.today().year), type=int)

    if request.method == 'POST':
        valor_total = float(request.form.get('valor_total') or 0)
        fecha_pago = _date_or_none(request.form.get('fecha_pago'))
        medio_pago_id = request.form.get('medio_pago_id') or None
        observaciones = (request.form.get('observaciones') or '').strip()
        medio_pago = MedioPago.query.get(medio_pago_id) if medio_pago_id else None

        if valor_total <= 0:
            flash('Debe indicar el valor total a aplicar.', 'danger')
            return redirect(url_for('nomina.pagar_saldos_historicos_empleado', id=empleado.id, anio_retorno=anio_retorno))

        if not fecha_pago:
            flash('Debe indicar una fecha de pago valida.', 'danger')
            return redirect(url_for('nomina.pagar_saldos_historicos_empleado', id=empleado.id, anio_retorno=anio_retorno))

        try:
            payload = json.loads(request.form.get('saldos_payload') or '[]')
        except json.JSONDecodeError:
            payload = []

        if not payload:
            flash('Seleccione al menos una quincena para aplicar el pago.', 'danger')
            return redirect(url_for('nomina.pagar_saldos_historicos_empleado', id=empleado.id, anio_retorno=anio_retorno))

        periodo_limite = _periodo_actual_nomina_clave()
        disponibles = {
            (item['anio'], item['mes'], item['quincena']): item
            for item in _items_pago_historico_empleado(empleado, periodo_limite)
        }
        items_aplicados = []
        total_aplicado = 0

        for item in payload:
            anio_item = int(item.get('anio', 0) or 0)
            mes_item = int(item.get('mes', 0) or 0)
            quincena_item = int(item.get('quincena', 0) or 0)
            valor_aplicado = float(item.get('valor_aplicado', 0) or 0)
            key = (anio_item, mes_item, quincena_item)
            disponible = disponibles.get(key)
            if not disponible or valor_aplicado <= 0:
                continue
            if valor_aplicado - float(disponible['valor_deuda'] or 0) > 1:
                flash(f'El valor aplicado a {disponible["periodo"]} supera el saldo pendiente.', 'danger')
                return redirect(url_for('nomina.pagar_saldos_historicos_empleado', id=empleado.id, anio_retorno=anio_retorno))
            items_aplicados.append({
                'data': disponible,
                'valor_aplicado': valor_aplicado,
            })
            total_aplicado += valor_aplicado

        if not items_aplicados:
            flash('No se encontraron quincenas validas para aplicar el pago.', 'danger')
            return redirect(url_for('nomina.pagar_saldos_historicos_empleado', id=empleado.id, anio_retorno=anio_retorno))

        if total_aplicado - valor_total > 1:
            flash('La suma aplicada supera el valor total ingresado.', 'danger')
            return redirect(url_for('nomina.pagar_saldos_historicos_empleado', id=empleado.id, anio_retorno=anio_retorno))

        if valor_total - total_aplicado > 1:
            flash('Hay valor sin aplicar. Ajuste el monto o marque mas quincenas.', 'danger')
            return redirect(url_for('nomina.pagar_saldos_historicos_empleado', id=empleado.id, anio_retorno=anio_retorno))

        items_aplicados.sort(key=lambda row: (row['data']['anio'], row['data']['mes'], row['data']['quincena']))
        periodos_actualizados = 0

        for item in items_aplicados:
            data = item['data']
            valor_aplicado = float(item['valor_aplicado'] or 0)
            saldo = data.get('saldo')
            registros = data.get('registros') or []
            nota = _nota_pago_historico_nomina(valor_aplicado, fecha_pago, medio_pago=medio_pago, observaciones=observaciones)

            if data['origen'] == 'manual' and not registros:
                pendiente_actual = float(saldo.saldo_pendiente or 0) if saldo else 0
                if pendiente_actual <= 0:
                    continue
                nuevo_pendiente = max(pendiente_actual - valor_aplicado, 0)
                saldo.saldo_pendiente = nuevo_pendiente
                saldo.estado = 'pagado' if nuevo_pendiente <= 0 else 'parcial'
                saldo.observaciones = _append_observacion(saldo.observaciones, nota)
                _registrar_abono_nomina(
                    empleado_id=empleado.id,
                    saldo_anterior_nomina_id=saldo.id if saldo else None,
                    anio=data['anio'],
                    mes=data['mes'],
                    quincena=data['quincena'],
                    valor_abono=valor_aplicado,
                    fecha_pago=fecha_pago,
                    medio_pago_id=medio_pago_id,
                    descripcion=nota
                )
                periodos_actualizados += 1
                continue

            deuda_actual = float(data['valor_deuda'] or 0)
            total_causado = float(data['valor_causado'] or 0)
            if deuda_actual <= 0 or total_causado <= 0:
                continue

            nuevo_pendiente = max(deuda_actual - valor_aplicado, 0)

            if nuevo_pendiente <= 0:
                for registro in registros:
                    if not registro.fecha_pago:
                        registro.fecha_pago = fecha_pago
                    if medio_pago_id:
                        registro.medio_pago_id = medio_pago_id
                    registro.observaciones = _append_observacion(registro.observaciones, nota)
                if saldo:
                    saldo.saldo_pendiente = 0
                    saldo.estado = 'pagado'
                    saldo.observaciones = _append_observacion(saldo.observaciones, nota)
            else:
                if saldo:
                    saldo.valor_inicial = saldo.valor_inicial or total_causado
                    saldo.saldo_pendiente = nuevo_pendiente
                    saldo.estado = 'parcial'
                    saldo.observaciones = _append_observacion(saldo.observaciones, nota)

                for registro in registros:
                    registro.observaciones = _append_observacion(registro.observaciones, nota)

            _registrar_abono_nomina(
                empleado_id=empleado.id,
                saldo_anterior_nomina_id=saldo.id if saldo and not registros else None,
                anio=data['anio'],
                mes=data['mes'],
                quincena=data['quincena'],
                valor_abono=valor_aplicado,
                fecha_pago=fecha_pago,
                medio_pago_id=medio_pago_id,
                descripcion=nota
            )

            periodos_actualizados += 1

        db.session.commit()
        flash(f'Se aplico el pago a {periodos_actualizados} quincena(s) de {empleado.nombre}.', 'success')
        return redirect(url_for('nomina.detalle', id=empleado.id, anio=anio_retorno))

    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    saldos_pendientes = _items_pago_historico_empleado(empleado, _periodo_actual_nomina_clave())
    total_pendiente = sum(float(item['valor_deuda'] or 0) for item in saldos_pendientes)
    saldos_pendientes_json = [
        {
            'anio': item['anio'],
            'mes': item['mes'],
            'quincena': item['quincena'],
            'valor_deuda': float(item['valor_deuda'] or 0),
        }
        for item in saldos_pendientes
    ]
    return render_template(
        'nomina/pagar_saldos_historicos.html',
        empleado=empleado,
        anio_retorno=anio_retorno,
        medios=medios,
        saldos_pendientes=saldos_pendientes,
        saldos_pendientes_json=saldos_pendientes_json,
        total_pendiente=total_pendiente,
        meses=MESES,
    )


@nomina_bp.route('/registrar', methods=['GET', 'POST'])
def registrar_quincena():
    if request.method == 'POST':
        anio = int(request.form['anio'])
        mes = int(request.form['mes'])
        quincena = int(request.form['quincena'])
        anio, mes, quincena = _normalizar_periodo_nomina(anio, mes, quincena)
        _normalizar_conceptos_base_periodo_nomina(anio, mes, quincena)
        draft_key = _preliquidacion_session_key(anio, mes, quincena)
        draft = session.get(draft_key, {})
        draft_rows = draft.get('rows', {}) if draft else {}
        conceptos_activos = ConceptoNomina.query.filter_by(activo=True).order_by(
            ConceptoNomina.tipo, ConceptoNomina.nombre
        ).all()
        conceptos_dict = {concepto.id: concepto for concepto in conceptos_activos}
        conceptos_base_ids = {
            concepto.id for concepto in conceptos_activos
            if _es_concepto_base_nomina(concepto)
        }

        empleados_ids = request.form.getlist('empleado_ids')
        count = 0
        omitidos_no_aplican = 0
        omitidos_pagados = 0
        for emp_id in empleados_ids:
            empleado = Empleado.query.get(int(emp_id))
            if not empleado:
                continue
            concepto_id = request.form.get(f'concepto_{emp_id}')
            valor = request.form.get(f'valor_{emp_id}')
            registros_existentes = RegistroNomina.query.filter_by(
                empleado_id=empleado.id,
                anio=anio,
                mes=mes,
                quincena=quincena
            ).order_by(RegistroNomina.id).all()
            concepto_periodo = _concepto_principal_periodo_nomina(
                empleado, anio, mes, quincena, conceptos_activos, registros=registros_existentes
            )
            if not concepto_id and concepto_periodo:
                concepto_id = str(concepto_periodo.id)
            concepto_id_int = int(concepto_id) if concepto_id else None
            if concepto_id_int in conceptos_base_ids and concepto_periodo and _es_concepto_base_nomina(concepto_periodo):
                concepto_id_int = concepto_periodo.id
            registros_a_guardar = {}

            if concepto_id_int and valor:
                registros_a_guardar[concepto_id_int] = {
                    'valor': float(valor),
                    'observaciones': []
                }

            draft_row = draft_rows.get(str(emp_id), {})
            forma_aplicada = _normalizar_forma_pago_nomina(
                draft_row.get('forma_pago_aplicada', empleado.forma_pago or 'quincenal')
            )
            if not _empleado_aplica_periodo(empleado, anio, mes, quincena, forma_aplicada):
                omitidos_no_aplican += 1
                continue
            resumen_periodo = _resumen_pago_periodo_nomina(empleado.id, anio, mes, quincena)
            if resumen_periodo['esta_pagado']:
                omitidos_pagados += 1
                continue
            novedades_resumen = _parse_novedades_periodo(
                request.form.get(f'novedades_{emp_id}'),
                conceptos_dict
            )
            for novedad in novedades_resumen['items']:
                concepto_novedad_id = int(novedad.get('concepto_id') or 0)
                if not concepto_novedad_id:
                    continue
                valor_novedad = float(novedad.get('valor') or 0)
                if novedad.get('tipo') == 'deduccion':
                    valor_novedad *= -1

                if concepto_novedad_id not in registros_a_guardar:
                    registros_a_guardar[concepto_novedad_id] = {
                        'valor': 0,
                        'observaciones': []
                    }

                registros_a_guardar[concepto_novedad_id]['valor'] += valor_novedad
                if novedad.get('justificacion'):
                    registros_a_guardar[concepto_novedad_id]['observaciones'].append(novedad['justificacion'])

            for concepto_guardar_id, data in registros_a_guardar.items():
                if not data['valor']:
                    continue
                existe = RegistroNomina.query.filter_by(
                    empleado_id=emp_id,
                    concepto_nomina_id=concepto_guardar_id,
                    anio=anio,
                    mes=mes,
                    quincena=quincena
                ).first()
                if existe:
                    existe.valor = data['valor']
                    for observacion in data['observaciones']:
                        existe.observaciones = _append_observacion(existe.observaciones, observacion)
                    count += 1
                else:
                    registro = RegistroNomina(
                        empleado_id=emp_id,
                        concepto_nomina_id=concepto_guardar_id,
                        anio=anio,
                        mes=mes,
                        quincena=quincena,
                        valor=data['valor'],
                        observaciones=' | '.join(data['observaciones']) if data['observaciones'] else None
                    )
                    db.session.add(registro)
                    count += 1

        db.session.commit()
        flash(f'{count} registros de nómina guardados.', 'success')
        if omitidos_no_aplican:
            flash(
                f'{omitidos_no_aplican} empleado(s) se omitieron porque no aplican a esa quincena por fecha de ingreso/retiro o forma de pago.',
                'warning'
            )
        if omitidos_pagados:
            flash(
                f'{omitidos_pagados} empleado(s) se omitieron porque esa quincena ya estaba completamente pagada.',
                'info'
            )
        session.pop(draft_key, None)
        return redirect(url_for('nomina.pagos', anio=anio, mes=mes, quincena=quincena))

    anio = request.args.get('anio', date.today().year, type=int)
    mes = request.args.get('mes', date.today().month, type=int)
    quincena = request.args.get('quincena', 1, type=int)
    empleado_id_filtro = request.args.get('empleado_id', type=int)
    anio, mes, quincena = _normalizar_periodo_nomina(anio, mes, quincena)
    normalizados = _normalizar_conceptos_base_periodo_nomina(anio, mes, quincena, empleado_id=empleado_id_filtro)
    if normalizados:
        db.session.commit()
    empleado_seleccionado = None
    if empleado_id_filtro:
        empleado_seleccionado = Empleado.query.filter_by(activo=True, id=empleado_id_filtro).first_or_404()
        if not _empleado_aplica_periodo(empleado_seleccionado, anio, mes, quincena):
            flash('Ese empleado no aplica para la quincena seleccionada.', 'warning')
            return redirect(url_for('nomina.pagos', anio=anio, mes=mes, quincena=quincena))
    empleados_periodo = _empleados_nomina_periodo(anio, mes, quincena, empleado_id=empleado_id_filtro)
    empleados = []
    for empleado in empleados_periodo:
        resumen_periodo = _resumen_pago_periodo_nomina(empleado.id, anio, mes, quincena)
        if resumen_periodo['esta_pagado']:
            continue
        empleados.append(empleado)
    if empleado_id_filtro and not empleados:
        flash('Ese empleado ya tiene la quincena completamente pagada y por eso no aparece en Causar.', 'info')
        return redirect(url_for('nomina.pagos', anio=anio, mes=mes, quincena=quincena))
    conceptos = ConceptoNomina.query.filter_by(activo=True).order_by(ConceptoNomina.tipo, ConceptoNomina.nombre).all()
    draft = session.get(_preliquidacion_session_key(anio, mes, quincena), {})
    draft_rows = draft.get('rows', {}) if draft else {}
    valores_periodo = {
        e.id: _valor_periodo_empleado(e, anio, mes, quincena)
        for e in empleados
    }
    conceptos_sugeridos = {}
    for empleado in empleados:
        concepto_sugerido = _concepto_principal_periodo_nomina(empleado, anio, mes, quincena, conceptos)
        conceptos_sugeridos[empleado.id] = concepto_sugerido.id if concepto_sugerido else None

    return render_template('nomina/registrar_quincena_v2.html',
                           empleados=empleados, conceptos=conceptos,
                           anio=anio, mes=mes,
                           quincena=quincena, meses=MESES,
                           empleado_id_filtro=empleado_id_filtro,
                           empleado_seleccionado=empleado_seleccionado,
                           formas_pago_labels=FORMAS_PAGO_LABELS,
                           valores_periodo=valores_periodo,
                           conceptos_sugeridos=conceptos_sugeridos,
                           preliquidacion_rows=draft_rows,
                           meses_habilitados=_meses_habilitados_nomina(anio),
                           nomina_inicio_anio=NOMINA_INICIO_ANIO,
                           nomina_inicio_mes=NOMINA_INICIO_MES)


@nomina_bp.route('/pagar', methods=['GET', 'POST'])
def pagar_quincena():
    if request.method == 'POST':
        anio = int(request.form['anio'])
        mes = int(request.form['mes'])
        quincena = int(request.form['quincena'])
        anio, mes, quincena = _normalizar_periodo_nomina(anio, mes, quincena)
        empleado_id_filtro = request.form.get('empleado_id_filtro', type=int)
        _normalizar_conceptos_base_periodo_nomina(anio, mes, quincena, empleado_id=empleado_id_filtro)
        fecha_pago = _date_or_none(request.form.get('fecha_pago'))
        medio_pago_id = request.form.get('medio_pago_id') or None
        observaciones = (request.form.get('observaciones') or '').strip()
        medio_pago = MedioPago.query.get(medio_pago_id) if medio_pago_id else None
        redirect_kwargs = {'anio': anio, 'mes': mes, 'quincena': quincena}
        if empleado_id_filtro:
            redirect_kwargs['empleado_id'] = empleado_id_filtro

        if not fecha_pago:
            flash('Debe indicar una fecha de pago valida.', 'danger')
            return redirect(url_for('nomina.pagar_quincena', **redirect_kwargs))

        empleados_ids = request.form.getlist('empleado_ids')
        if not empleados_ids:
            flash('Seleccione al menos un empleado para registrar el pago.', 'warning')
            return redirect(url_for('nomina.pagar_quincena', **redirect_kwargs))

        pagos_preparados = []
        for emp_id in empleados_ids:
            empleado = Empleado.query.get(int(emp_id))
            if not empleado or not _empleado_aplica_periodo(empleado, anio, mes, quincena):
                continue

            registros = RegistroNomina.query.filter_by(
                empleado_id=empleado.id, anio=anio, mes=mes, quincena=quincena
            ).all()
            if not registros:
                continue

            desglose = _desglose_registros_periodo_nomina(empleado, anio, mes, quincena, registros=registros)
            total_causado = float(desglose['total_causado'] or 0)
            total_abonado = sum(
                float(a.valor_abono or 0)
                for a in AbonoNomina.query.filter_by(
                    empleado_id=empleado.id, anio=anio, mes=mes, quincena=quincena
                ).all()
            )
            if total_abonado <= 0 and desglose['registros'] and desglose['base_pagada'] and all(
                r.fecha_pago for r in desglose['otros_registros']
            ):
                total_abonado = total_causado
            saldo_pendiente = max(total_causado - total_abonado, 0)
            if saldo_pendiente <= 0:
                continue

            valor_pago = float(request.form.get(f'valor_{emp_id}') or 0)
            if valor_pago <= 0:
                valor_pago = saldo_pendiente
            if valor_pago - saldo_pendiente > 1:
                flash(f'El valor a pagar de {empleado.nombre} supera el saldo pendiente de la quincena.', 'danger')
                return redirect(url_for('nomina.pagar_quincena', **redirect_kwargs))

            pagos_preparados.append({
                'empleado': empleado,
                'registros': registros,
                'valor_pago': valor_pago,
                'total_causado': total_causado,
                'total_abonado': total_abonado,
            })

        if not pagos_preparados:
            flash('No se encontraron causaciones pendientes para pagar en esa quincena.', 'warning')
            return redirect(url_for('nomina.pagar_quincena', **redirect_kwargs))

        periodos_pagados = 0
        for pago in pagos_preparados:
            empleado = pago['empleado']
            registros = pago['registros']
            valor_pago = pago['valor_pago']
            total_causado = pago['total_causado']
            total_abonado = pago['total_abonado']
            nota = _nota_pago_periodo_nomina(valor_pago, fecha_pago, medio_pago=medio_pago, observaciones=observaciones)

            _registrar_abono_nomina(
                empleado_id=empleado.id,
                anio=anio,
                mes=mes,
                quincena=quincena,
                valor_abono=valor_pago,
                fecha_pago=fecha_pago,
                medio_pago_id=medio_pago_id,
                descripcion=nota
            )

            total_abonado_nuevo = total_abonado + valor_pago
            for registro in registros:
                registro.observaciones = _append_observacion(registro.observaciones, nota)
                if medio_pago_id and not registro.medio_pago_id and total_abonado_nuevo + 1 >= total_causado:
                    registro.medio_pago_id = medio_pago_id
                if total_abonado_nuevo + 1 >= total_causado and not registro.fecha_pago:
                    registro.fecha_pago = fecha_pago

            periodos_pagados += 1

        db.session.commit()
        flash(f'Se registraron pagos para {periodos_pagados} empleado(s) en la quincena.', 'success')
        return redirect(url_for('nomina.pagos', anio=anio, mes=mes, quincena=quincena))

    anio = request.args.get('anio', date.today().year, type=int)
    mes = request.args.get('mes', date.today().month, type=int)
    quincena = request.args.get('quincena', 1 if date.today().day <= 15 else 2, type=int)
    empleado_id_filtro = request.args.get('empleado_id', type=int)
    anio, mes, quincena = _normalizar_periodo_nomina(anio, mes, quincena)
    meses_habilitados = _meses_habilitados_nomina(anio)
    normalizados = _normalizar_conceptos_base_periodo_nomina(anio, mes, quincena, empleado_id=empleado_id_filtro)
    if normalizados:
        db.session.commit()

    empleado_seleccionado = None
    if empleado_id_filtro:
        empleado_seleccionado = Empleado.query.filter_by(activo=True, id=empleado_id_filtro).first_or_404()
        if not _empleado_aplica_periodo(empleado_seleccionado, anio, mes, quincena):
            flash('Ese empleado no aplica para la quincena seleccionada.', 'warning')
            return redirect(url_for('nomina.pagos', anio=anio, mes=mes, quincena=quincena))

    empleados_periodo = _empleados_nomina_periodo(anio, mes, quincena, empleado_id=empleado_id_filtro)
    empleados_periodo_ids = [e.id for e in empleados_periodo]
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()

    registros_quincena = RegistroNomina.query.filter_by(anio=anio, mes=mes, quincena=quincena).all()
    registros_por_empleado = {}
    for registro in registros_quincena:
        if registro.empleado_id not in empleados_periodo_ids:
            continue
        registros_por_empleado.setdefault(registro.empleado_id, []).append(registro)

    abonos_quincena = AbonoNomina.query.filter_by(anio=anio, mes=mes, quincena=quincena).all()
    abonos_por_empleado = {}
    for abono in abonos_quincena:
        abonos_por_empleado[abono.empleado_id] = abonos_por_empleado.get(abono.empleado_id, 0) + float(abono.valor_abono or 0)

    rows = []
    total_causado = 0
    total_abonado = 0
    total_saldo = 0
    for empleado in empleados_periodo:
        registros = registros_por_empleado.get(empleado.id, [])
        if not registros:
            continue
        desglose = _desglose_registros_periodo_nomina(empleado, anio, mes, quincena, registros=registros)
        registros_visibles = desglose['registros']
        causado = float(desglose['total_causado'] or 0)
        abonado = float(abonos_por_empleado.get(empleado.id, 0) or 0)
        if abonado <= 0 and registros_visibles and desglose['base_pagada'] and all(
            r.fecha_pago for r in desglose['otros_registros']
        ):
            abonado = causado
        saldo = max(causado - abonado, 0)
        conceptos = desglose['conceptos']
        total_causado += causado
        total_abonado += abonado
        total_saldo += saldo
        rows.append({
            'empleado': empleado,
            'registros': registros_visibles,
            'conceptos': conceptos,
            'total_causado': causado,
            'total_abonado': abonado,
            'saldo': saldo,
            'incluir': saldo > 0,
            'tiene_novedades': len(registros_visibles) > 1,
        })

    if empleado_id_filtro and not rows:
        flash('Ese empleado todavia no tiene una causacion registrada en esa quincena. Primero use Causar.', 'info')

    return render_template(
        'nomina/pagar_quincena.html',
        empleados_pago=rows,
        medios=medios,
        anio=anio,
        mes=mes,
        quincena=quincena,
        meses=MESES,
        meses_habilitados=meses_habilitados,
        empleado_id_filtro=empleado_id_filtro,
        empleado_seleccionado=empleado_seleccionado,
        total_causado=total_causado,
        total_abonado=total_abonado,
        total_saldo=total_saldo,
        nomina_inicio_anio=NOMINA_INICIO_ANIO,
        nomina_inicio_mes=NOMINA_INICIO_MES,
    )
