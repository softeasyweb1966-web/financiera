"""Calendario mensual de intereses; los pagos conservan su período original."""
from calendar import monthrange
from datetime import date


def mes_desde(fecha, n):
    year, month = divmod(fecha.year * 12 + fecha.month - 1 + n, 12)
    return date(year, month + 1, min(fecha.day, monthrange(year, month + 1)[1]))


def aplica(o):
    return o.modalidad == 'solo_interes' and o.tipo_interes in ('anticipado', 'vencido')


def fechas(o, anio, mes):
    if not o.fecha_inicio:
        return []
    inicio = o.fecha_inicio
    fin = o.fecha_pago_capital or o.fecha_vencimiento
    n = (anio - inicio.year) * 12 + mes - inicio.month
    if n < 0:
        return []
    fecha = mes_desde(inicio, n)
    if o.tipo_interes == 'anticipado':
        return [fecha] if not fin or fecha < fin else []
    if n == 0:
        return [fin] if fin and inicio < fin and (fin.year, fin.month) == (anio, mes) else []
    # Un período incompleto se liquida al cierre, sin prorrateo automático.
    if fin and fecha > fin:
        anterior = mes_desde(inicio, n - 1)
        return [fin] if anterior < fin and (fin.year, fin.month) == (anio, mes) else []
    return [fecha]
