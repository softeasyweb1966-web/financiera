from datetime import date, datetime

from app import create_app, db
from app.models import AmortizacionObligacion, Obligacion, Tercero


ROWS = [
    ('04/09/2026', 1119368, 1190700, 103587, 0, 24.0000, 58415670),
    ('04/10/2026', 1141754, 1168314, 103587, 0, 24.0000, 57273916),
    ('04/11/2026', 1164590, 1145478, 103587, 0, 24.0000, 56109326),
    ('04/12/2026', 1187881, 1122187, 103587, 0, 24.0000, 54921445),
    ('04/01/2027', 1211640, 1098428, 103587, 0, 24.0000, 53709805),
    ('04/02/2027', 1235871, 1074197, 103587, 0, 24.0000, 52473934),
    ('04/03/2027', 1260590, 1049478, 103587, 0, 24.0000, 51213344),
    ('04/04/2027', 1285801, 1024267, 103587, 0, 24.0000, 49927543),
    ('04/05/2027', 1311517, 998551, 103587, 0, 24.0000, 48616026),
    ('04/06/2027', 1337747, 972321, 103587, 0, 24.0000, 47278279),
    ('04/07/2027', 1364503, 945565, 103587, 0, 24.0000, 45913776),
    ('04/08/2027', 1391792, 918276, 103587, 0, 24.0000, 44521984),
    ('04/09/2027', 1419629, 890439, 103587, 0, 24.0000, 43102355),
    ('04/10/2027', 1448021, 862047, 103587, 0, 24.0000, 41654334),
    ('04/11/2027', 1476981, 833087, 103587, 0, 24.0000, 40177353),
    ('04/12/2027', 1506521, 803547, 103587, 0, 24.0000, 38670832),
    ('04/01/2028', 1536651, 773417, 103587, 0, 24.0000, 37134181),
    ('04/02/2028', 1567385, 742683, 103587, 0, 24.0000, 35566796),
    ('04/03/2028', 1598732, 711336, 103587, 0, 24.0000, 33968064),
    ('04/04/2028', 1630706, 679362, 103587, 0, 24.0000, 32337358),
    ('04/05/2028', 1663321, 646747, 103587, 0, 24.0000, 30674037),
    ('04/06/2028', 1696587, 613481, 103587, 0, 24.0000, 28977450),
    ('04/07/2028', 1730519, 579549, 103587, 0, 24.0000, 27246931),
    ('04/08/2028', 1765130, 544938, 103587, 0, 24.0000, 25481801),
    ('04/09/2028', 1800432, 509636, 103587, 0, 24.0000, 23681369),
    ('04/10/2028', 1836440, 473628, 103587, 0, 24.0000, 21844929),
    ('04/11/2028', 1873170, 436898, 103587, 0, 24.0000, 19971759),
    ('04/12/2028', 1910633, 399435, 103587, 0, 24.0000, 18061126),
    ('04/01/2029', 1948845, 361223, 103587, 0, 24.0000, 16112281),
    ('04/02/2029', 1987823, 322245, 103587, 0, 24.0000, 14124458),
    ('04/03/2029', 2027578, 282490, 103587, 0, 24.0000, 12096880),
    ('04/04/2029', 2068131, 241937, 103587, 0, 24.0000, 10028749),
    ('04/05/2029', 2109493, 200575, 103587, 0, 24.0000, 7919256),
    ('04/06/2029', 2151683, 158385, 103587, 0, 24.0000, 5767573),
    ('04/07/2029', 2194716, 115352, 103587, 0, 24.0000, 3572857),
    ('04/08/2029', 2238611, 71457, 103587, 0, 24.0000, 1334246),
    ('04/09/2029', 1334246, 26685, 103587, 0, 24.0000, 0),
]


def main():
    app = create_app()
    with app.app_context():
        obligacion = (
            Obligacion.query.join(Tercero)
            .filter(Tercero.nombre == 'CIELO')
            .order_by(Obligacion.id.asc())
            .first()
        )
        if not obligacion:
            raise SystemExit('No se encontro una obligacion del tercero CIELO.')

        AmortizacionObligacion.query.filter_by(obligacion_id=obligacion.id).delete()

        for fecha_pago, capital, intereses, seguro_vida, otros, tasa_namv, saldo_capital in ROWS:
            db.session.add(
                AmortizacionObligacion(
                    obligacion_id=obligacion.id,
                    fecha_pago=datetime.strptime(fecha_pago, '%d/%m/%Y').date(),
                    capital=capital,
                    intereses=intereses,
                    seguro_vida=seguro_vida,
                    otros=otros,
                    tasa_namv=tasa_namv,
                    saldo_capital=saldo_capital,
                )
            )

        obligacion.modalidad = 'bancario_tabla_amortizacion'
        obligacion.fecha_inicio_amortizacion = date(2026, 9, 1)
        obligacion.fecha_vencimiento = date(2029, 9, 4)
        obligacion.dia_limite_pago = 4
        obligacion.requiere_desglose_pago = True
        obligacion.valor_cuota_fija = None
        obligacion.valor_cuota_capital = None
        obligacion.valor_cuota_interes = None
        obligacion.cuotas_totales = len(ROWS)
        obligacion.cuotas_pagadas = 0
        obligacion.saldo_actual = ROWS[0][1] + ROWS[0][6]
        nota = 'Desde 2026-09-01 usa tabla de amortizacion cargada el 2026-08-14.'
        observaciones = (obligacion.observaciones or '').strip()
        if nota not in observaciones:
            obligacion.observaciones = f'{observaciones}\n{nota}'.strip() if observaciones else nota

        db.session.commit()
        print(
            'OK',
            obligacion.id,
            obligacion.modalidad,
            obligacion.fecha_inicio_amortizacion,
            obligacion.fecha_vencimiento,
            obligacion.saldo_actual,
        )


if __name__ == '__main__':
    main()
