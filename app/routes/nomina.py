from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app import db
from app.models import (
    Empleado, Tercero, TipoTercero, RegistroNomina,
    ConceptoNomina, MedioPago, HistorialEstado, SaldoAnteriorNomina,
    HistorialSalario
)
from datetime import date, datetime
import calendar
import json
from sqlalchemy import func

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


def _date_or_none(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


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


def _aplicar_saldos_anteriores_manuales(empleado_id, monto):
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
        total_aplicado += aplicado
        monto_restante -= aplicado

    return total_aplicado


def _dias_periodo_nomina(anio, mes, quincena):
    dias_mes = calendar.monthrange(anio, mes)[1]
    return 15 if quincena == 1 else max(dias_mes - 15, 0)


def _rango_periodo_nomina(anio, mes, quincena):
    inicio_dia = 1 if quincena == 1 else 16
    fin_dia = 15 if quincena == 1 else calendar.monthrange(anio, mes)[1]
    return date(anio, mes, inicio_dia), date(anio, mes, fin_dia)


def _empleado_aplica_periodo(empleado, anio, mes, quincena):
    periodo_inicio, periodo_fin = _rango_periodo_nomina(anio, mes, quincena)
    if empleado.fecha_ingreso and empleado.fecha_ingreso > periodo_fin:
        return False
    if empleado.fecha_retiro and empleado.fecha_retiro < periodo_inicio:
        return False
    return True


def _valor_periodo_empleado(empleado, anio, mes, quincena, forma_pago=None):
    salario = float(empleado.salario_base or 0)
    frecuencia = forma_pago or empleado.forma_pago or 'quincenal'
    dias_mes = calendar.monthrange(anio, mes)[1]
    dias_periodo = _dias_periodo_nomina(anio, mes, quincena)

    if not _empleado_aplica_periodo(empleado, anio, mes, quincena):
        return 0
    if not salario:
        return 0
    if frecuencia == 'mensual':
        return salario if quincena == 2 else 0
    if frecuencia in ('diaria', 'semanal'):
        return salario / dias_mes * dias_periodo if dias_mes else 0
    return salario / 2


def _pendiente_anterior_empleado(empleado, anio, mes, quincena):
    total = sum(float(s.saldo_pendiente or 0) for s in _saldos_anteriores_manuales_hasta(empleado.id, anio, mes, quincena).all())
    meses_habilitados = _meses_habilitados_nomina(anio)
    if not meses_habilitados:
        return total

    for m_check in range(meses_habilitados[0], mes + 1):
        q_range = [1, 2] if m_check < mes else list(range(1, quincena))
        for q_check in q_range:
            if not _empleado_aplica_periodo(empleado, anio, m_check, q_check):
                continue
            tiene_registro = RegistroNomina.query.filter_by(
                empleado_id=empleado.id, anio=anio, mes=m_check, quincena=q_check
            ).first()
            if not tiene_registro and empleado.salario_base:
                total += _valor_periodo_empleado(empleado, anio, m_check, q_check)
    return total


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
        empleados_laborales_count=sum(1 for e in empleados_activos if (e.tipo_contrato or 'laboral') == 'laboral'),
        empleados_servicios_count=sum(1 for e in empleados_activos if e.tipo_contrato == 'prestacion_servicios'),
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
            salario_base=request.form.get('salario_base') or None,
            tipo_contrato=request.form.get('tipo_contrato', 'laboral'),
            forma_pago=request.form.get('forma_pago', 'quincenal'),
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
        nuevo_salario_str = request.form.get('salario_base', '').strip()
        nuevo_salario = float(nuevo_salario_str) if nuevo_salario_str else None
        salario_anterior = float(empleado.salario_base) if empleado.salario_base else None

        if nuevo_salario and salario_anterior and nuevo_salario != salario_anterior:
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
        empleado.tipo_contrato = request.form.get('tipo_contrato', 'laboral')
        empleado.forma_pago = request.form.get('forma_pago', 'quincenal')
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

    empleados = Empleado.query.filter_by(activo=True).order_by(Empleado.cargo).all()
    conceptos = ConceptoNomina.query.filter_by(activo=True).order_by(ConceptoNomina.tipo, ConceptoNomina.nombre).all()
    conceptos_dict = {c.id: c for c in conceptos}
    draft_key = _preliquidacion_session_key(anio, mes, quincena)

    if request.method == 'POST':
        draft_rows = {}
        actualizados = 0
        total_novedades_periodo = 0

        for e in empleados:
            incluir = bool(request.form.get(f'incluir_{e.id}'))
            forma_aplicada = request.form.get(f'forma_pago_{e.id}', e.forma_pago or 'quincenal')
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

    for e in empleados:
        draft_row = draft.get('rows', {}).get(str(e.id), {})
        forma_aplicada = draft_row.get('forma_pago_aplicada', e.forma_pago or 'quincenal')
        valor_preliquidado = float(draft_row.get('valor_preliquidado', _valor_periodo_empleado(e, anio, mes, quincena, forma_aplicada)))
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

    empleados = Empleado.query.filter_by(activo=True).order_by(Empleado.cargo).all()
    empleados_periodo = [
        e for e in empleados
        if _empleado_aplica_periodo(e, anio, mes, quincena)
    ]
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

    # Acumulado pagado meses anteriores
    acum_pagado_anterior = db.session.query(
        func.coalesce(func.sum(RegistroNomina.valor), 0)
    ).filter(
        RegistroNomina.anio == anio,
        RegistroNomina.fecha_pago.isnot(None),
        db.or_(
            RegistroNomina.mes < mes,
            db.and_(RegistroNomina.mes == mes, RegistroNomina.quincena < quincena)
        )
    ).scalar()

    # Pagado en la quincena actual
    pagado_quincena_actual = db.session.query(
        func.coalesce(func.sum(RegistroNomina.valor), 0)
    ).filter(
        RegistroNomina.anio == anio, RegistroNomina.mes == mes,
        RegistroNomina.quincena == quincena,
        RegistroNomina.fecha_pago.isnot(None)
    ).scalar()

    # Total esperado del periodo segun la frecuencia configurada
    esperado_quincena = sum(
        _valor_periodo_empleado(e, anio, mes, quincena) for e in empleados_periodo
    )

    # Quincenas sin pagar de periodos anteriores
    pendientes_anteriores = []
    total_deuda_anterior = 0

    saldos_manuales = SaldoAnteriorNomina.query.filter(
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
    ).all()

    for saldo in saldos_manuales:
        valor_pendiente = float(saldo.saldo_pendiente or 0)
        if valor_pendiente <= 0:
            continue
        total_deuda_anterior += valor_pendiente
        pendientes_anteriores.append({
            'empleado': saldo.empleado,
            'mes_nombre': MESES[saldo.mes - 1],
            'anio': saldo.anio,
            'quincena': saldo.quincena,
            'valor_esperado': valor_pendiente,
            'detalle': saldo.observaciones,
            'manual': True,
        })

    for e in empleados_periodo:
        # Check si hay quincenas anteriores sin registros
        for m_check in range(meses_habilitados[0], mes + 1):
            q_range = [1, 2] if m_check < mes else list(range(1, quincena))
            for q_check in q_range:
                if not _empleado_aplica_periodo(e, anio, m_check, q_check):
                    continue
                registros_previos = RegistroNomina.query.filter_by(
                    empleado_id=e.id, anio=anio, mes=m_check, quincena=q_check
                ).all()
                esta_pagado = bool(registros_previos) and all(r.fecha_pago for r in registros_previos)
                if not esta_pagado and e.salario_base:
                    valor_esperado = (
                        sum(float(r.valor) for r in registros_previos)
                        if registros_previos else
                        _valor_periodo_empleado(e, anio, m_check, q_check)
                    )
                    total_deuda_anterior += valor_esperado
                    pendientes_anteriores.append({
                        'empleado': e,
                        'mes_nombre': MESES[m_check - 1],
                        'anio': anio,
                        'quincena': q_check,
                        'valor_esperado': valor_esperado,
                        'detalle': None,
                        'manual': False,
                    })

    # Resumen por concepto de nómina
    resumen_conceptos = {}
    for r in registros_quincena:
        concepto_nombre = r.concepto_nomina.nombre if r.concepto_nomina else 'Sin concepto'
        tipo = r.concepto_nomina.tipo if r.concepto_nomina else 'otro'
        if concepto_nombre not in resumen_conceptos:
            resumen_conceptos[concepto_nombre] = {
                'nombre': concepto_nombre,
                'tipo': tipo,
                'color': '#10b981' if tipo == 'devengado' else '#ef4444',
                'total': 0,
                'cantidad': 0
            }
        resumen_conceptos[concepto_nombre]['total'] += float(r.valor)
        resumen_conceptos[concepto_nombre]['cantidad'] += 1

    resumen_grupos = list(resumen_conceptos.values())

    # Tarjetas por empleado
    empleados_mes = []
    for e in empleados_periodo:
        registros_emp = registros_por_empleado.get(e.id, [])
        total_registrado = sum(float(r.valor) for r in registros_emp)
        total_pagado = sum(float(r.valor) for r in registros_emp if r.fecha_pago)
        tiene_registro = len(registros_emp) > 0
        esta_pagado = tiene_registro and all(r.fecha_pago for r in registros_emp)
        aplica_periodo = _empleado_aplica_periodo(e, anio, mes, quincena)
        valor_quincena = _valor_periodo_empleado(e, anio, mes, quincena)

        empleados_mes.append({
            'empleado': e,
            'registros': registros_emp,
            'total_registrado': total_registrado,
            'total_pagado': total_pagado,
            'tiene_pago': esta_pagado,
            'tiene_registro': tiene_registro,
            'aplica_periodo': aplica_periodo,
            'valor_quincena': valor_quincena,
            'estado': 'pagado' if esta_pagado else 'causado' if tiene_registro else 'pendiente' if aplica_periodo else 'no_aplica',
        })

    empleados_pagados_count = sum(1 for item in empleados_mes if item['tiene_pago'])
    empleados_pendientes_count = sum(1 for item in empleados_mes if item['estado'] in ('pendiente', 'causado'))
    registros_quincena_count = len(registros_quincena)

    # Acumulado pagado por empleado (para drill-down)
    from sqlalchemy import func as sqlfunc
    acum_por_empleado = db.session.query(
        RegistroNomina.empleado_id,
        sqlfunc.sum(RegistroNomina.valor).label('total')
    ).filter(
        RegistroNomina.anio == anio,
        RegistroNomina.fecha_pago.isnot(None),
        db.or_(
            RegistroNomina.mes < mes,
            db.and_(RegistroNomina.mes == mes, RegistroNomina.quincena < quincena)
        )
    ).group_by(RegistroNomina.empleado_id).all()

    acum_empleados_dict = {row[0]: float(row[1]) for row in acum_por_empleado}
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
    meses_habilitados = _meses_habilitados_nomina(anio)
    registros = RegistroNomina.query.filter_by(empleado_id=id, anio=anio).order_by(
        RegistroNomina.mes, RegistroNomina.quincena, RegistroNomina.created_at
    ).all()
    # Group by (mes, quincena)
    pagos_dict = {}
    causaciones_dict = {}
    estados_quincena = {}
    aplica_quincena = {}
    for r in registros:
        key = (r.mes, r.quincena)
        if key not in pagos_dict:
            pagos_dict[key] = []
        pagos_dict[key].append(r)
        if key not in causaciones_dict and r.created_at:
            causaciones_dict[key] = r.created_at.date()
    for mes in meses_habilitados:
        for quincena_check in (1, 2):
            key = (mes, quincena_check)
            aplica_quincena[key] = _empleado_aplica_periodo(empleado, anio, mes, quincena_check)
    for key, items in pagos_dict.items():
        if items and all(r.fecha_pago for r in items):
            estados_quincena[key] = 'pagado'
        elif items:
            estados_quincena[key] = 'causado'
    for key, aplica in aplica_quincena.items():
        if not aplica and key not in estados_quincena:
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
        elif estados_mes_actual:
            estados_mes[mes] = 'pagado' if all(estado == 'pagado' for estado in estados_mes_actual) else 'causado'
    saldos_anteriores = SaldoAnteriorNomina.query.filter_by(empleado_id=id).order_by(
        SaldoAnteriorNomina.anio, SaldoAnteriorNomina.mes, SaldoAnteriorNomina.quincena, SaldoAnteriorNomina.id
    ).all()
    return render_template('nomina/detalle.html', empleado=empleado, anio=anio,
                           meses=MESES, pagos=pagos_dict, causaciones=causaciones_dict,
                           meses_habilitados=meses_habilitados,
                           aplica_quincena=aplica_quincena,
                           estados_quincena=estados_quincena,
                           estados_mes=estados_mes,
                           saldos_anteriores=saldos_anteriores,
                           nomina_inicio_anio=NOMINA_INICIO_ANIO,
                           nomina_inicio_mes=NOMINA_INICIO_MES)


@nomina_bp.route('/registrar', methods=['GET', 'POST'])
def registrar_quincena():
    if request.method == 'POST':
        anio = int(request.form['anio'])
        mes = int(request.form['mes'])
        quincena = int(request.form['quincena'])
        anio, mes, quincena = _normalizar_periodo_nomina(anio, mes, quincena)
        medio_pago_id = request.form.get('medio_pago_id') or None
        fecha_pago = request.form.get('fecha_pago') or None
        draft_key = _preliquidacion_session_key(anio, mes, quincena)
        draft = session.get(draft_key, {})
        draft_rows = draft.get('rows', {}) if draft else {}

        empleados_ids = request.form.getlist('empleado_ids')
        count = 0
        for emp_id in empleados_ids:
            empleado = Empleado.query.get(int(emp_id))
            if not empleado:
                continue
            concepto_id = request.form.get(f'concepto_{emp_id}')
            valor = request.form.get(f'valor_{emp_id}')
            registros_a_guardar = {}
            observaciones_extra = []

            if concepto_id and valor:
                registros_a_guardar[int(concepto_id)] = {
                    'valor': float(valor),
                    'observaciones': []
                }

            draft_row = draft_rows.get(str(emp_id), {})
            forma_aplicada = draft_row.get('forma_pago_aplicada', empleado.forma_pago or 'quincenal')
            for novedad in draft_row.get('novedades', []):
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

            valor_pagado_total = float(valor or 0)
            base_periodo = float(draft_row.get(
                'valor_preliquidado',
                _valor_periodo_empleado(empleado, anio, mes, quincena, forma_aplicada)
            ))
            total_novedades = float(draft_row.get('total_novedades', 0))
            excedente_saldos = max(0, valor_pagado_total - max(0, base_periodo + total_novedades))
            saldos_aplicados = False

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
                if excedente_saldos > 0 and not saldos_aplicados and fecha_pago:
                    aplicado_saldos = _aplicar_saldos_anteriores_manuales(empleado.id, excedente_saldos)
                    if aplicado_saldos > 0:
                        observaciones_extra.append(f'Aplico ${aplicado_saldos:,.0f} a saldos anteriores cargados.')
                    saldos_aplicados = True
                if existe:
                    if fecha_pago and not existe.fecha_pago:
                        existe.fecha_pago = fecha_pago
                    if medio_pago_id and not existe.medio_pago_id:
                        existe.medio_pago_id = medio_pago_id
                    if observaciones_extra:
                        observacion_nueva = ' | '.join(observaciones_extra)
                        if existe.observaciones:
                            if observacion_nueva not in existe.observaciones:
                                existe.observaciones = f'{existe.observaciones} | {observacion_nueva}'
                        else:
                            existe.observaciones = observacion_nueva
                else:
                    if excedente_saldos > 0 and not saldos_aplicados:
                        aplicado_saldos = _aplicar_saldos_anteriores_manuales(empleado.id, excedente_saldos)
                        if aplicado_saldos > 0:
                            observaciones_extra.append(f'Aplico ${aplicado_saldos:,.0f} a saldos anteriores cargados.')
                        saldos_aplicados = True
                    registro = RegistroNomina(
                        empleado_id=emp_id,
                        concepto_nomina_id=concepto_guardar_id,
                        anio=anio,
                        mes=mes,
                        quincena=quincena,
                        valor=data['valor'],
                        medio_pago_id=medio_pago_id,
                        fecha_pago=fecha_pago,
                        observaciones=' | '.join(data['observaciones'] + observaciones_extra) if (data['observaciones'] or observaciones_extra) else None
                    )
                    db.session.add(registro)
                    count += 1

        db.session.commit()
        flash(f'{count} registros de nómina guardados.', 'success')
        session.pop(draft_key, None)
        return redirect(url_for('nomina.pagos', anio=anio, mes=mes, quincena=quincena))

    anio = request.args.get('anio', date.today().year, type=int)
    mes = request.args.get('mes', date.today().month, type=int)
    quincena = request.args.get('quincena', 1, type=int)
    empleado_id_filtro = request.args.get('empleado_id', type=int)
    anio, mes, quincena = _normalizar_periodo_nomina(anio, mes, quincena)
    empleados_query = Empleado.query.filter_by(activo=True)
    empleado_seleccionado = None
    if empleado_id_filtro:
        empleado_seleccionado = empleados_query.filter_by(id=empleado_id_filtro).first_or_404()
        if not _empleado_aplica_periodo(empleado_seleccionado, anio, mes, quincena):
            flash('Ese empleado no aplica para la quincena seleccionada.', 'warning')
            return redirect(url_for('nomina.pagos', anio=anio, mes=mes, quincena=quincena))
        empleados_query = empleados_query.filter_by(id=empleado_id_filtro)
    empleados = [
        e for e in empleados_query.order_by(Empleado.cargo).all()
        if _empleado_aplica_periodo(e, anio, mes, quincena)
    ]
    conceptos = ConceptoNomina.query.filter_by(activo=True).order_by(ConceptoNomina.tipo, ConceptoNomina.nombre).all()
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    draft = session.get(_preliquidacion_session_key(anio, mes, quincena), {})
    draft_rows = draft.get('rows', {}) if draft else {}
    valores_periodo = {
        e.id: _valor_periodo_empleado(e, anio, mes, quincena)
        for e in empleados
    }

    return render_template('nomina/registrar_quincena_v2.html',
                           empleados=empleados, conceptos=conceptos,
                           medios=medios, anio=anio, mes=mes,
                           quincena=quincena, meses=MESES,
                           empleado_id_filtro=empleado_id_filtro,
                           empleado_seleccionado=empleado_seleccionado,
                           formas_pago_labels=FORMAS_PAGO_LABELS,
                           valores_periodo=valores_periodo,
                           preliquidacion_rows=draft_rows,
                           meses_habilitados=_meses_habilitados_nomina(anio),
                           nomina_inicio_anio=NOMINA_INICIO_ANIO,
                           nomina_inicio_mes=NOMINA_INICIO_MES)
