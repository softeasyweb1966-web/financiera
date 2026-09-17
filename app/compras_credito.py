"""Validación de condiciones de compra y distribución de pagos por vencimiento."""
from datetime import date
from decimal import Decimal, InvalidOperation


def importe(value):
    try:
        numero = Decimal(str(value or '0').replace(',', ''))
        if not numero.is_finite() or numero < 0 or numero > Decimal('999999999999.99'):
            raise ValueError()
        if numero != numero.quantize(Decimal('0.01')):
            raise ValueError()
        return numero.quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise ValueError('Ingrese valores válidos, no negativos y con máximo dos decimales.')


def fecha(value, nombre):
    try:
        return date.fromisoformat(value or '')
    except ValueError:
        raise ValueError(f'Indique una fecha válida para {nombre}.')


def preparar(form):
    condicion = form.get('condicion_pago')
    if condicion not in ('credito', 'contado'):
        raise ValueError('Seleccione contado o crédito.')
    compra_fecha = fecha(form.get('fecha'), 'la compra')
    total = importe(form.get('valor'))
    if total <= 0:
        raise ValueError('El valor de la compra debe ser mayor que cero.')
    paga = condicion == 'contado' or form.get('paga_inicial') == 'si'
    if condicion == 'credito' and form.get('paga_inicial') not in ('si', 'no'):
        raise ValueError('Indique si realiza un pago inicial.')
    inicial = total if condicion == 'contado' else importe(form.get('valor_abono_inicial')) if paga else Decimal(0)
    if paga and (inicial <= 0 or inicial > total):
        raise ValueError('El pago inicial debe ser positivo y no superar el valor de la compra.')
    if condicion == 'credito' and inicial >= total:
        raise ValueError('Si paga el valor completo, seleccione contado.')
    fecha_pago = fecha(form.get('fecha_pago'), 'el pago inicial') if paga else None
    if fecha_pago and (fecha_pago < compra_fecha or fecha_pago > date.today()):
        raise ValueError('La fecha del pago inicial debe estar entre la fecha de compra y hoy.')
    cuotas = []
    if condicion == 'credito':
        fechas, valores = form.getlist('cuota_fecha'), form.getlist('cuota_valor')
        if not fechas or len(fechas) != len(valores) or len(fechas) > 600:
            raise ValueError('Registre las fechas y valores de las próximas cuotas (máximo 600).')
        for f, v in zip(fechas, valores):
            vencimiento = fecha(f, 'cada cuota')
            valor = importe(v)
            if valor <= 0 or vencimiento < compra_fecha or (fecha_pago and vencimiento < fecha_pago):
                raise ValueError('Cada cuota debe ser positiva y su fecha no puede ser anterior a la compra ni al pago inicial.')
            cuotas.append({'fecha': vencimiento, 'valor': valor, 'es_inicial': False})
        if sum(c['valor'] for c in cuotas) != total - inicial:
            raise ValueError('La suma de las próximas cuotas debe ser igual al saldo: valor de compra menos pago inicial.')
        cuotas.sort(key=lambda c: c['fecha'])
        if inicial:
            cuotas.insert(0, {'fecha': fecha_pago, 'valor': inicial, 'es_inicial': True})
    return {'condicion': condicion, 'fecha': compra_fecha, 'total': total, 'inicial': inicial,
            'fecha_pago': fecha_pago, 'cuotas': cuotas}


def calendario(compra, hoy=None):
    """Aplica los abonos reales en orden a la cuota más antigua pendiente."""
    hoy = hoy or date.today()
    pagos = [{'id': p.id, 'fecha': p.fecha_pago, 'disponible': p.valor_abono}
             for p in sorted(compra.abonos.all(), key=lambda p: (p.fecha_pago, p.id))]
    resultado = []
    for cuota in compra.cuotas.all():
        saldo = cuota.valor
        aplicaciones = []
        for pago in pagos:
            aplicado = min(saldo, pago['disponible'])
            if aplicado <= 0:
                continue
            saldo -= aplicado
            pago['disponible'] -= aplicado
            aplicaciones.append({'fecha': pago['fecha'], 'valor': aplicado, 'abono_id': pago['id']})
        estado = 'Pagada' if saldo == 0 else 'Vencida' if cuota.fecha_vencimiento < hoy else 'Parcial' if saldo < cuota.valor else 'Pendiente'
        resultado.append({'cuota': cuota, 'abonado': cuota.valor - saldo, 'saldo': saldo,
                          'estado': estado, 'pagos': aplicaciones})
    return resultado
