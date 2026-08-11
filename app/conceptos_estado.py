from collections import defaultdict
from datetime import date

from app.models import HistorialEstado


ESTADOS_CONCEPTO = ('activo', 'inactivo')


def inicio_mes(anio, mes):
    return date(anio, mes, 1)


def periodo_anterior(anio, mes):
    if mes == 1:
        return anio - 1, 12
    return anio, mes - 1


def cargar_historial_conceptos(concepto_ids):
    if not concepto_ids:
        return {}

    rows = HistorialEstado.query.filter(
        HistorialEstado.entidad == 'concepto',
        HistorialEstado.entidad_id.in_(concepto_ids)
    ).order_by(
        HistorialEstado.entidad_id,
        HistorialEstado.vigencia_desde,
        HistorialEstado.fecha_cambio,
        HistorialEstado.id
    ).all()

    historial = defaultdict(list)
    for row in rows:
        historial[row.entidad_id].append(row)
    return historial


def estado_concepto_en_periodo(concepto, anio, mes, historial_rows=None):
    rows = historial_rows or []
    if rows and rows[0].estado_anterior:
        estado = rows[0].estado_anterior
    else:
        estado = 'activo' if concepto.activo else 'inactivo'

    vigente = None
    ref = inicio_mes(anio, mes)
    for row in rows:
        vigencia = row.vigencia_desde or row.fecha_cambio.date()
        if vigencia and vigencia <= ref:
            estado = row.estado_nuevo
            vigente = row
        else:
            break
    return estado, vigente


def concepto_activo_en_periodo(concepto, anio, mes, historial_rows=None):
    estado, _ = estado_concepto_en_periodo(concepto, anio, mes, historial_rows)
    return estado == 'activo'


def siguiente_cambio_concepto(concepto, anio, mes, historial_rows=None):
    rows = historial_rows or []
    ref = inicio_mes(anio, mes)
    for row in rows:
        vigencia = row.vigencia_desde or row.fecha_cambio.date()
        if vigencia and vigencia > ref:
            return row
    return None
