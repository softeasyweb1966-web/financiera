from flask import Blueprint, render_template, request
from app import db
from app.models import (
    Servicio, PagoServicio, Obligacion, PagoObligacion,
    Empleado, RegistroNomina, Compra, Gasto
)
from datetime import date
from sqlalchemy import text

main_bp = Blueprint('main', __name__)

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


@main_bp.route('/restaurar-pagos-2026')
def restaurar_pagos():
    """Ruta temporal para restaurar pagos de servicios Ene-Jul 2026. Eliminar después de usar."""
    datos = [
        (1,1,222000),(1,2,436000),(1,3,369000),(1,4,360000),(1,5,336000),(1,6,324000),(1,7,298500),
        (2,1,283488),(2,2,283488),(2,3,283258),(2,4,255000),(2,5,255584),(2,6,255584),
        (3,1,60000),(3,2,60000),(3,3,60000),(3,4,77500),(3,5,86700),(3,6,116600),(3,7,66000),
        (4,1,6581000),(4,2,6581000),(4,3,6581000),(4,4,6581000),(4,5,6581000),(4,6,6581000),(4,7,6581000),
        (7,1,57000),(7,2,57000),(7,3,57000),(7,4,57000),(7,5,57000),(7,6,57000),
        (8,1,75500),(8,2,79013),(8,3,79132),(8,4,79000),(8,5,-119),(8,6,78894),(8,7,90040),
        (9,1,178650),(9,2,187650),(9,3,188900),(9,4,201120),(9,5,291090),(9,6,290650),(9,7,310100),
        (10,1,426390),(10,2,426390),(10,3,492460),(10,4,409650),(10,5,456390),(10,6,452420),(10,7,470880),
        (11,1,241740),(11,2,149840),(11,3,133800),(11,4,133800),(11,5,133800),(11,6,135710),(11,7,135440),
        (12,1,65500),(12,2,65420),(12,3,53000),(12,4,119000),(12,5,43100),(12,6,39290),(12,7,55280),
        (13,1,55912),(13,2,55912),(13,3,53900),(13,4,54221),(13,5,53900),(13,6,53900),(13,7,54216),
        (14,1,46000),(14,2,46000),(14,3,54374),(14,4,54000),(14,5,109645),(14,7,48381),
        (15,1,43900),(15,2,43900),
        (16,1,45201),(16,2,45201),(16,3,45000),(16,4,45000),
        (19,1,283488),(19,2,283488),(19,3,283258),(19,4,255000),(19,5,255584),(19,6,255584),
        (20,1,60000),(20,2,60000),(20,3,60000),(20,4,77500),(20,5,86700),(20,6,116600),(20,7,66000),
    ]
    # N/A entries
    na_datos = [
        (5,1),(5,3),(5,5),(5,7),(6,1),(6,3),(6,5),(6,7),
        (15,3),(15,4),(15,5),(15,6),(15,7),(16,5),(16,6),(16,7),
    ]
    # Pagado entries for bimestrales
    bim_pagados = [
        (5,2,569370),(5,4,170000),(5,6,182740),
        (6,2,279830),(6,4,150900),(6,6,182740),
    ]

    count = 0
    with db.engine.connect() as conn:
        # No borrar existentes, solo insertar los que falten
        for sid, mes, valor in datos:
            exists = conn.execute(text(
                "SELECT id FROM pagos_servicios WHERE servicio_id=:sid AND anio=2026 AND mes=:mes"
            ), {'sid': sid, 'mes': mes}).fetchone()
            if not exists:
                conn.execute(text(
                    "INSERT INTO pagos_servicios (servicio_id, anio, mes, valor_pagado, estado) VALUES (:sid, 2026, :mes, :val, 'pagado')"
                ), {'sid': sid, 'mes': mes, 'val': valor})
                count += 1

        for sid, mes, valor in bim_pagados:
            exists = conn.execute(text(
                "SELECT id FROM pagos_servicios WHERE servicio_id=:sid AND anio=2026 AND mes=:mes"
            ), {'sid': sid, 'mes': mes}).fetchone()
            if not exists:
                conn.execute(text(
                    "INSERT INTO pagos_servicios (servicio_id, anio, mes, valor_pagado, estado) VALUES (:sid, 2026, :mes, :val, 'pagado')"
                ), {'sid': sid, 'mes': mes, 'val': valor})
                count += 1

        for sid, mes in na_datos:
            exists = conn.execute(text(
                "SELECT id FROM pagos_servicios WHERE servicio_id=:sid AND anio=2026 AND mes=:mes"
            ), {'sid': sid, 'mes': mes}).fetchone()
            if not exists:
                conn.execute(text(
                    "INSERT INTO pagos_servicios (servicio_id, anio, mes, estado) VALUES (:sid, 2026, :mes, 'n/a')"
                ), {'sid': sid, 'mes': mes})
                count += 1

        conn.commit()

    return f'<h3>Restauración completada</h3><p>Registros insertados: {count}</p><p><a href="/">Volver al inicio</a></p>'


@main_bp.route('/')
def index():
    anio = request.args.get('anio', date.today().year, type=int)
    mes = request.args.get('mes', date.today().month, type=int)

    servicios_activos = Servicio.query.filter_by(activo=True).count()
    obligaciones_activas = Obligacion.query.filter_by(activo=True).count()
    empleados_activos = Empleado.query.filter_by(activo=True).count()

    # Pagos del mes actual
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
        db.extract('month', Compra.fecha) == mes
    ).scalar()

    total_gastos = db.session.query(
        db.func.coalesce(db.func.sum(Gasto.valor), 0)
    ).filter(
        db.extract('year', Gasto.fecha) == anio,
        db.extract('month', Gasto.fecha) == mes
    ).scalar()

    # Pendientes del mes (causado + vencido + sin_causar que ya pasó el día)
    servicios_pendientes = PagoServicio.query.filter(
        PagoServicio.anio == anio, PagoServicio.mes == mes,
        PagoServicio.estado.in_(['causado', 'vencido', 'sin_causar', 'parcial'])
    ).count()
    obligaciones_pendientes = PagoObligacion.query.filter_by(
        anio=anio, mes=mes, estado='pendiente').count()

    return render_template('index.html',
                           anio=anio, mes=mes, meses=MESES,
                           servicios_activos=servicios_activos,
                           obligaciones_activas=obligaciones_activas,
                           empleados_activos=empleados_activos,
                           total_servicios=total_servicios,
                           total_obligaciones=total_obligaciones,
                           total_nomina=total_nomina,
                           total_compras=total_compras,
                           total_gastos=total_gastos,
                           servicios_pendientes=servicios_pendientes,
                           obligaciones_pendientes=obligaciones_pendientes)
