"""
Script para generar el SQL que restaura los pagos de servicios Ene-Jul 2026
en la BD de Railway. Ejecute este script localmente y copie el resultado
en la consola web de Railway.
"""
from app import create_app, db
from app.models import Servicio, PagoServicio

app = create_app()
with app.app_context():
    pagos = PagoServicio.query.filter(
        PagoServicio.anio == 2026, PagoServicio.mes <= 7
    ).order_by(PagoServicio.servicio_id, PagoServicio.mes).all()

    print(f'-- Restaurar {len(pagos)} pagos de servicios (Ene-Jul 2026)')
    print(f'-- Generado desde BD local')
    print()

    # Primero necesitamos saber el mapeo de servicios por tercero
    # porque los IDs pueden ser diferentes en Railway
    # Mejor generar por servicio_id directamente y confiar que son iguales
    print("DELETE FROM pagos_servicios WHERE anio = 2026 AND mes <= 7;")
    print()
    print("INSERT INTO pagos_servicios (servicio_id, anio, mes, valor_causado, valor_pagado, estado, fecha_causacion, created_at) VALUES")

    lines = []
    for p in pagos:
        val_causado = str(float(p.valor_causado)) if p.valor_causado else 'NULL'
        val_pagado = str(float(p.valor_pagado)) if p.valor_pagado else 'NULL'
        estado = p.estado or 'pagado'
        fecha_c = "'" + str(p.fecha_causacion) + "'" if p.fecha_causacion else 'NULL'
        created = "'" + str(p.created_at) + "'" if p.created_at else 'NOW()'
        lines.append(
            f"({p.servicio_id}, {p.anio}, {p.mes}, {val_causado}, {val_pagado}, "
            f"'{estado}', {fecha_c}, {created})"
        )

    print(',\n'.join(lines) + ';')
    print()
    print(f'-- Total: {len(lines)} registros')
