from calendar import monthrange
from datetime import date

from flask import Blueprint, current_app, render_template, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import (
    Compra,
    Empleado,
    Gasto,
    Obligacion,
    PagoObligacion,
    PagoServicio,
    RegistroNomina,
    Servicio,
)
from app import compras_credito
from app.conceptos_estado import cargar_historial_servicios, servicio_activo_en_periodo
from app.routes import nomina as nomina_service
from app.routes import obligaciones as obligaciones_service
from app.routes.compras import _abonos_por_compra, _totales_compra

main_bp = Blueprint('main', __name__)

MESES = [
    'Enero',
    'Febrero',
    'Marzo',
    'Abril',
    'Mayo',
    'Junio',
    'Julio',
    'Agosto',
    'Septiembre',
    'Octubre',
    'Noviembre',
    'Diciembre',
]


def _nuevo_total():
    return {'total': 0, 'cancelado': 0, 'vencido': 0, 'por_vencer': 0, 'items': 0}


def _sumar_total(destino, item):
    destino['total'] += item['total']
    destino['cancelado'] += item['cancelado']
    destino['vencido'] += item['vencido']
    destino['por_vencer'] += item['por_vencer']
    destino['items'] += 1


def _agregar_item(items, resumen, item):
    item['pendiente'] = item['vencido'] + item['por_vencer']
    items.append(item)
    _sumar_total(resumen.setdefault(item['modulo'], _nuevo_total()), item)


def _fecha_limite_servicio(servicio, anio, mes):
    if servicio.periodicidad == 'anual':
        fecha_anual = servicio.fecha_pago_anual
        if not fecha_anual or fecha_anual.month != mes:
            return None
        dia = servicio.dia_limite_pago or fecha_anual.day
    elif servicio.periodicidad == 'bimestral':
        inicio = servicio.mes_inicio_bimestral or 1
        if (mes - inicio) % 2 != 0:
            return None
        dia = servicio.dia_limite_pago or 1
    else:
        dia = servicio.dia_limite_pago or 1
    return date(anio, mes, min(int(dia), monthrange(anio, mes)[1]))


def _valor_estimado_servicio(servicio, ultimo_pago=None):
    if servicio.periodicidad == 'anual' and servicio.provision_mensual:
        return float(servicio.provision_mensual or 0)
    if servicio.valor_estimado:
        return float(servicio.valor_estimado or 0)
    return float(ultimo_pago or 0)


def _items_servicios_mes(anio, mes, hoy):
    items = []
    resumen = {}
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.dia_limite_pago, Servicio.id).all()
    historiales = cargar_historial_servicios([s.id for s in servicios])
    pagos = PagoServicio.query.filter_by(anio=anio, mes=mes).all()
    pagos_por_servicio = {p.servicio_id: p for p in pagos}
    ultimos = {}
    historicos = PagoServicio.query.filter(PagoServicio.valor_pagado.isnot(None)).order_by(
        PagoServicio.anio.desc(), PagoServicio.mes.desc(), PagoServicio.id.desc()
    ).all()
    for pago in historicos:
        ultimos.setdefault(pago.servicio_id, pago.valor_pagado)

    for servicio in servicios:
        if not servicio_activo_en_periodo(servicio, anio, mes, historiales.get(servicio.id, [])):
            continue
        fecha_limite = _fecha_limite_servicio(servicio, anio, mes)
        pago = pagos_por_servicio.get(servicio.id)
        if not fecha_limite and not pago:
            continue
        if pago and pago.estado == 'n/a':
            continue
        total = float((pago.valor_causado or pago.valor_pagado) or 0) if pago else 0
        if total <= 0:
            total = _valor_estimado_servicio(servicio, ultimos.get(servicio.id))
        cancelado = float(pago.valor_pagado or 0) if pago else 0
        saldo = max(total - cancelado, 0)
        item = {
            'modulo': 'Servicios',
            'nombre': servicio.concepto.nombre if servicio.concepto else 'Servicio',
            'tercero': servicio.tercero.nombre if servicio.tercero else '',
            'fecha': fecha_limite,
            'total': total,
            'cancelado': cancelado,
            'vencido': saldo if fecha_limite and fecha_limite < hoy else 0,
            'por_vencer': 0 if fecha_limite and fecha_limite < hoy else saldo,
            'estado': pago.estado if pago else 'sin_causar',
            'url': None,
        }
        _agregar_item(items, resumen, item)
    return items, resumen


def _items_obligaciones_mes(anio, mes, hoy):
    items = []
    resumen = {}
    obligaciones = Obligacion.query.filter_by(activo=True).order_by(Obligacion.id).all()
    pagos = {(p.obligacion_id, p.anio, p.mes): p for p in PagoObligacion.query.filter_by(anio=anio, mes=mes).all()}
    for obligacion in obligaciones:
        if not obligaciones_service._obligacion_aplica_mes(obligacion, anio, mes):
            continue
        fechas = obligaciones_service._fechas_programadas_obligacion(obligacion, anio, mes)
        if not fechas:
            continue
        pago = pagos.get((obligacion.id, anio, mes))
        componentes = obligaciones_service._componentes_programados_periodo(obligacion, anio, mes)
        total = float((pago.valor_causado if pago and pago.valor_causado else None) or componentes.get('total') or 0)
        cancelado = float(pago.valor_pagado or 0) if pago else 0
        saldo = max(total - cancelado, 0)
        fecha_limite = min(fechas)
        item = {
            'modulo': 'Obligaciones',
            'nombre': obligacion.concepto.nombre if obligacion.concepto else 'Obligacion',
            'tercero': obligacion.tercero.nombre if obligacion.tercero else '',
            'fecha': fecha_limite,
            'total': total,
            'cancelado': cancelado,
            'vencido': saldo if fecha_limite < hoy else 0,
            'por_vencer': 0 if fecha_limite < hoy else saldo,
            'estado': obligaciones_service._estado_visible_pago(pago, total),
            'url': None,
        }
        _agregar_item(items, resumen, item)
    return items, resumen


def _items_nomina_mes(anio, mes, hoy):
    items = []
    resumen = {}
    for empleado in Empleado.query.filter_by(activo=True).order_by(Empleado.cargo, Empleado.id).all():
        for quincena, dia in ((1, 15), (2, monthrange(anio, mes)[1])):
            if not nomina_service._empleado_aplica_periodo(empleado, anio, mes, quincena):
                continue
            resumen_pago = nomina_service._resumen_pago_periodo_nomina(empleado.id, anio, mes, quincena)
            total = float(resumen_pago['total_registrado'] or 0)
            if total <= 0:
                total = float(nomina_service._valor_esperado_periodo_nomina(empleado, anio, mes, quincena) or 0)
            cancelado = float(resumen_pago['total_pagado'] or 0)
            saldo = max(total - cancelado, 0)
            fecha_limite = date(anio, mes, dia)
            item = {
                'modulo': 'Nomina',
                'nombre': f'{empleado.tercero.nombre if empleado.tercero else empleado.id} - Q{quincena}',
                'tercero': empleado.cargo or '',
                'fecha': fecha_limite,
                'total': total,
                'cancelado': cancelado,
                'vencido': saldo if fecha_limite < hoy else 0,
                'por_vencer': 0 if fecha_limite < hoy else saldo,
                'estado': 'pagado' if saldo <= 0 and total > 0 else 'pendiente',
                'url': None,
            }
            _agregar_item(items, resumen, item)
    return items, resumen


def _items_compras_mes(anio, mes, hoy):
    items = []
    resumen = {}
    compras = Compra.query.filter(Compra.estado != 'anulado').order_by(Compra.fecha.desc(), Compra.id.desc()).all()
    resumen_abonos = _abonos_por_compra([c.id for c in compras])
    for compra in compras:
        if compra.condicion_pago == 'credito' and compra.cuotas.count():
            for fila in compras_credito.calendario(compra, hoy=hoy):
                cuota = fila['cuota']
                if cuota.es_inicial or (cuota.fecha_vencimiento.year, cuota.fecha_vencimiento.month) != (anio, mes):
                    continue
                saldo = float(fila['saldo'] or 0)
                total = float(cuota.valor or 0)
                item = {
                    'modulo': 'Compras',
                    'nombre': compra.producto_compra.nombre if compra.producto_compra else compra.descripcion,
                    'tercero': compra.tercero.nombre if compra.tercero else '',
                    'fecha': cuota.fecha_vencimiento,
                    'total': total,
                    'cancelado': float(fila['abonado'] or 0),
                    'vencido': saldo if cuota.fecha_vencimiento < hoy else 0,
                    'por_vencer': 0 if cuota.fecha_vencimiento < hoy else saldo,
                    'estado': fila['estado'].lower(),
                    'url': None,
                }
                _agregar_item(items, resumen, item)
        elif (compra.fecha.year, compra.fecha.month) == (anio, mes):
            totales = _totales_compra(compra, resumen_abonos)
            saldo = float(totales['saldo'] or 0)
            item = {
                'modulo': 'Compras',
                'nombre': compra.producto_compra.nombre if compra.producto_compra else compra.descripcion,
                'tercero': compra.tercero.nombre if compra.tercero else '',
                'fecha': compra.fecha,
                'total': float(totales['valor_total'] or 0),
                'cancelado': float(totales['abonado'] or 0),
                'vencido': saldo if compra.fecha < hoy else 0,
                'por_vencer': 0 if compra.fecha < hoy else saldo,
                'estado': totales['estado'],
                'url': None,
            }
            _agregar_item(items, resumen, item)
    return items, resumen


@main_bp.route('/healthz')
def healthz():
    return {
        'status': 'ok',
        'schema_ready': bool(current_app.extensions.get('schema_ready', False)),
    }, 200


@main_bp.route('/pendientes')
@main_bp.route('/pendientes/<int:anio>/<int:mes>')
def pendientes(anio=None, mes=None):
    anio = anio or request.args.get('anio', date.today().year, type=int)
    mes = mes or request.args.get('mes', date.today().month, type=int)
    hoy = date.today()
    items = []
    resumen = {}

    for cargar in (
        _items_servicios_mes,
        _items_nomina_mes,
        _items_obligaciones_mes,
        _items_compras_mes,
    ):
        modulo_items, modulo_resumen = cargar(anio, mes, hoy)
        items.extend(modulo_items)
        for modulo, datos in modulo_resumen.items():
            destino = resumen.setdefault(modulo, _nuevo_total())
            destino['total'] += datos['total']
            destino['cancelado'] += datos['cancelado']
            destino['vencido'] += datos['vencido']
            destino['por_vencer'] += datos['por_vencer']
            destino['items'] += datos['items']

    items.sort(key=lambda item: (item['fecha'] or date(anio, mes, 1), item['modulo'], item['nombre']))
    total_mes = _nuevo_total()
    for datos in resumen.values():
        total_mes['total'] += datos['total']
        total_mes['cancelado'] += datos['cancelado']
        total_mes['vencido'] += datos['vencido']
        total_mes['por_vencer'] += datos['por_vencer']
        total_mes['items'] += datos['items']

    return render_template(
        'pendientes.html',
        anio=anio,
        mes=mes,
        meses=MESES,
        hoy=hoy,
        items=items,
        resumen=resumen,
        total_mes=total_mes,
    )


@main_bp.route('/restaurar-pagos-2026')
def restaurar_pagos():
    """Ruta temporal para restaurar pagos de servicios Ene-Jul 2026. Eliminar despues de usar."""
    datos = [
        (1, 1, 222000), (1, 2, 436000), (1, 3, 369000), (1, 4, 360000), (1, 5, 336000), (1, 6, 324000), (1, 7, 298500),
        (2, 1, 283488), (2, 2, 283488), (2, 3, 283258), (2, 4, 255000), (2, 5, 255584), (2, 6, 255584),
        (3, 1, 60000), (3, 2, 60000), (3, 3, 60000), (3, 4, 77500), (3, 5, 86700), (3, 6, 116600), (3, 7, 66000),
        (4, 1, 6581000), (4, 2, 6581000), (4, 3, 6581000), (4, 4, 6581000), (4, 5, 6581000), (4, 6, 6581000), (4, 7, 6581000),
        (7, 1, 57000), (7, 2, 57000), (7, 3, 57000), (7, 4, 57000), (7, 5, 57000), (7, 6, 57000),
        (8, 1, 75500), (8, 2, 79013), (8, 3, 79132), (8, 4, 79000), (8, 5, -119), (8, 6, 78894), (8, 7, 90040),
        (9, 1, 178650), (9, 2, 187650), (9, 3, 188900), (9, 4, 201120), (9, 5, 291090), (9, 6, 290650), (9, 7, 310100),
        (10, 1, 426390), (10, 2, 426390), (10, 3, 492460), (10, 4, 409650), (10, 5, 456390), (10, 6, 452420), (10, 7, 470880),
        (11, 1, 241740), (11, 2, 149840), (11, 3, 133800), (11, 4, 133800), (11, 5, 133800), (11, 6, 135710), (11, 7, 135440),
        (12, 1, 65500), (12, 2, 65420), (12, 3, 53000), (12, 4, 119000), (12, 5, 43100), (12, 6, 39290), (12, 7, 55280),
        (13, 1, 55912), (13, 2, 55912), (13, 3, 53900), (13, 4, 54221), (13, 5, 53900), (13, 6, 53900), (13, 7, 54216),
        (14, 1, 46000), (14, 2, 46000), (14, 3, 54374), (14, 4, 54000), (14, 5, 109645), (14, 7, 48381),
        (15, 1, 43900), (15, 2, 43900),
        (16, 1, 45201), (16, 2, 45201), (16, 3, 45000), (16, 4, 45000),
        (19, 1, 283488), (19, 2, 283488), (19, 3, 283258), (19, 4, 255000), (19, 5, 255584), (19, 6, 255584),
        (20, 1, 60000), (20, 2, 60000), (20, 3, 60000), (20, 4, 77500), (20, 5, 86700), (20, 6, 116600), (20, 7, 66000),
    ]
    na_datos = [
        (5, 1), (5, 3), (5, 5), (5, 7), (6, 1), (6, 3), (6, 5), (6, 7),
        (15, 3), (15, 4), (15, 5), (15, 6), (15, 7), (16, 5), (16, 6), (16, 7),
    ]
    bim_pagados = [
        (5, 2, 569370), (5, 4, 170000), (5, 6, 182740),
        (6, 2, 279830), (6, 4, 150900), (6, 6, 182740),
    ]

    count = 0
    with db.engine.connect() as conn:
        for sid, mes, valor in datos:
            exists = conn.execute(
                text("SELECT id FROM pagos_servicios WHERE servicio_id=:sid AND anio=2026 AND mes=:mes"),
                {'sid': sid, 'mes': mes},
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        "INSERT INTO pagos_servicios (servicio_id, anio, mes, valor_pagado, estado) "
                        "VALUES (:sid, 2026, :mes, :val, 'pagado')"
                    ),
                    {'sid': sid, 'mes': mes, 'val': valor},
                )
                count += 1

        for sid, mes, valor in bim_pagados:
            exists = conn.execute(
                text("SELECT id FROM pagos_servicios WHERE servicio_id=:sid AND anio=2026 AND mes=:mes"),
                {'sid': sid, 'mes': mes},
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        "INSERT INTO pagos_servicios (servicio_id, anio, mes, valor_pagado, estado) "
                        "VALUES (:sid, 2026, :mes, :val, 'pagado')"
                    ),
                    {'sid': sid, 'mes': mes, 'val': valor},
                )
                count += 1

        for sid, mes in na_datos:
            exists = conn.execute(
                text("SELECT id FROM pagos_servicios WHERE servicio_id=:sid AND anio=2026 AND mes=:mes"),
                {'sid': sid, 'mes': mes},
            ).fetchone()
            if not exists:
                conn.execute(
                    text("INSERT INTO pagos_servicios (servicio_id, anio, mes, estado) VALUES (:sid, 2026, :mes, 'n/a')"),
                    {'sid': sid, 'mes': mes},
                )
                count += 1

        conn.commit()

    return f'<h3>Restauracion completada</h3><p>Registros insertados: {count}</p><p><a href="/">Volver al inicio</a></p>'


@main_bp.route('/')
def index():
    anio = request.args.get('anio', date.today().year, type=int)
    mes = request.args.get('mes', date.today().month, type=int)

    database_warning = None

    try:
        servicios_activos = Servicio.query.filter_by(activo=True).count()
        obligaciones_activas = Obligacion.query.filter_by(activo=True).count()
        empleados_activos = Empleado.query.filter_by(activo=True).count()

        total_servicios = db.session.query(
            db.func.coalesce(db.func.sum(PagoServicio.valor_pagado), 0)
        ).filter_by(anio=anio, mes=mes, estado='pagado').scalar()

        total_servicios += db.session.query(
            db.func.coalesce(db.func.sum(PagoServicio.valor_pagado), 0)
        ).filter_by(anio=anio, mes=mes, estado='parcial').scalar()

        total_obligaciones = db.session.query(
            db.func.coalesce(db.func.sum(PagoObligacion.valor_pagado), 0)
        ).filter_by(anio=anio, mes=mes, estado='pagado').scalar()

        total_nomina = db.session.query(
            db.func.coalesce(db.func.sum(RegistroNomina.valor), 0)
        ).filter_by(anio=anio, mes=mes).scalar()

        total_compras = db.session.query(
            db.func.coalesce(db.func.sum(Compra.valor), 0)
        ).filter(
            db.extract('year', Compra.fecha) == anio,
            db.extract('month', Compra.fecha) == mes,
        ).scalar()

        total_gastos = db.session.query(
            db.func.coalesce(db.func.sum(Gasto.valor), 0)
        ).filter(
            db.extract('year', Gasto.fecha) == anio,
            db.extract('month', Gasto.fecha) == mes,
        ).scalar()
        total_compras_gastos = total_compras + total_gastos

        servicios_pendientes = PagoServicio.query.filter(
            PagoServicio.anio == anio,
            PagoServicio.mes == mes,
            PagoServicio.estado.in_(['causado', 'vencido', 'sin_causar', 'parcial']),
        ).count()
        obligaciones_pendientes = PagoObligacion.query.filter_by(
            anio=anio,
            mes=mes,
            estado='pendiente',
        ).count()
    except SQLAlchemyError:
        current_app.logger.exception('No fue posible cargar el dashboard por un problema de base de datos.')
        db.session.remove()
        servicios_activos = 0
        obligaciones_activas = 0
        empleados_activos = 0
        total_servicios = 0
        total_obligaciones = 0
        total_nomina = 0
        total_compras = 0
        total_gastos = 0
        total_compras_gastos = 0
        servicios_pendientes = 0
        obligaciones_pendientes = 0
        database_warning = (
            'La base de datos no respondio en este momento. '
            'La aplicacion sigue en linea y reintentara conectarse automaticamente.'
        )

    return render_template(
        'index.html',
        anio=anio,
        mes=mes,
        meses=MESES,
        servicios_activos=servicios_activos,
        obligaciones_activas=obligaciones_activas,
        empleados_activos=empleados_activos,
        total_servicios=total_servicios,
        total_obligaciones=total_obligaciones,
        total_nomina=total_nomina,
        total_compras=total_compras,
        total_gastos=total_gastos,
        total_compras_gastos=total_compras_gastos,
        servicios_pendientes=servicios_pendientes,
        obligaciones_pendientes=obligaciones_pendientes,
        database_warning=database_warning,
    )
