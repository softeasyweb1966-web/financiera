from flask import Blueprint, render_template, request
from app import db
from app.models import (
    Servicio, PagoServicio, Obligacion, PagoObligacion,
    Empleado, RegistroNomina, Compra, Gasto
)
from datetime import date

main_bp = Blueprint('main', __name__)

MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
         'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


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
