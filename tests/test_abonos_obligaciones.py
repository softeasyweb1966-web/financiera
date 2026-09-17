import re
import unittest
import importlib.util
from pathlib import Path
from datetime import date
from decimal import Decimal
from sqlalchemy import create_engine, text, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations

from flask import Flask, url_for
from werkzeug.datastructures import MultiDict
from app import db
from app import abonos_obligaciones as service
from app.models import (Obligacion, TipoTercero, Tercero, Categoria, Concepto,
                        PagoObligacion, AbonoCapitalObligacion, AmortizacionObligacion)
from app.routes import all_blueprints
from app.routes.obligaciones import (_valor_programado_mes_obligacion, _resumen_vencido_obligacion,
                                     _fechas_programadas_obligacion, _siguiente_fecha_programada)


class AbonosTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder='../app/templates', static_folder='../app/static')
        self.app.config.update(TESTING=True, SECRET_KEY='test-only', SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        for bp in all_blueprints:
            self.app.register_blueprint(bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        t = TipoTercero(nombre='Acreedor')
        c = Categoria(nombre='Obligaciones')
        db.session.add_all([t, c]); db.session.flush()
        tercero = Tercero(nombre='MAMÁ YELI', tipo_tercero_id=t.id)
        concepto = Concepto(nombre='Avance', categoria_id=c.id)
        db.session.add_all([tercero, concepto]); db.session.flush()
        self.o = Obligacion(tercero_id=tercero.id, concepto_id=concepto.id,
            modalidad='prestamo_corto_plazo', saldo_actual=9600000, capital_inicial=9600000,
            cuotas_totales=4, cuotas_pagadas=0, valor_cuota_fija=2400000,
            fecha_inicio=date(2026, 9, 10), fecha_vencimiento=date(2026, 12, 10),
            dia_limite_pago=10, requiere_desglose_pago=True)
        db.session.add(self.o); db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def datos(self, **kwargs):
        form = MultiDict(dict(opcion_recalculo='acuerdo', fecha_abono='2026-09-17',
            valor_abono='6400000', descuento_intereses='800000', observaciones='Descuento confirmado por el banco',
            cuota_fecha='2026-10-10', cuota_valor='2400000'))
        form.update(kwargs)
        for k, v in kwargs.items(): form.setlist(k, v if isinstance(v, list) else [v])
        return form

    def aplicar(self, form=None):
        a = service.aplicar(self.o, service.preparar(self.o, form if form is not None else self.datos()))
        db.session.commit()
        return a

    def test_caso_yeli_saldo_calendario_sin_atraso(self):
        a = self.aplicar()
        self.assertEqual(self.o.saldo_actual, Decimal('2400000'))
        self.assertEqual(self.o.cuotas_pendientes, 1)
        self.assertEqual(self.o.fecha_vencimiento, date(2026, 10, 10))
        self.assertEqual(a.valor_abono, Decimal('6400000'))
        self.assertEqual(a.descuento_intereses, 800000)
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 9), 0)
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 10), 2400000)
        self.assertEqual(_fechas_programadas_obligacion(self.o, 2026, 11), [])
        self.assertEqual(_siguiente_fecha_programada(self.o, date(2026, 9, 17)), date(2026, 10, 10))
        self.assertEqual(_resumen_vencido_obligacion(self.o, {}, 2026, 9, date(2026, 9, 17))['total_vencido'], 0)
        for url in ('/obligaciones/pagos/2026/9', '/obligaciones/pagos/2026/10',
                    f'/obligaciones/{self.o.id}/refinanciaciones', f'/obligaciones/detalle/{self.o.id}'):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_previa_no_escribe_confirmacion_no_duplica(self):
        url = f'/obligaciones/{self.o.id}/abonos'
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, data=self.datos())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AbonoCapitalObligacion.query.count(), 0)
        self.assertEqual(self.o.saldo_actual, Decimal('9600000'))
        token = re.search(r'name="confirmacion" value="([^"]+)"', response.text)[1]
        self.assertEqual(self.client.post(url, data={'confirmacion': token}).status_code, 302)
        self.client.post(url, data={'confirmacion': token})
        self.assertEqual(AbonoCapitalObligacion.query.count(), 1)

    def test_enlace_abonar_abre_formulario(self):
        with self.app.test_request_context():
            url = url_for('obligaciones.abonar_capital', id=self.o.id)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_reversion_restauracion_de_causado_y_pago_parcial(self):
        p = PagoObligacion(obligacion_id=self.o.id, anio=2026, mes=9, estado='parcial',
                          valor_causado=2400000, valor_pagado=100000, componente_capital=50000)
        db.session.add(p); db.session.commit()
        a = self.aplicar()
        self.assertEqual(p.estado, 'pagado')
        self.assertEqual(p.valor_pagado, 100000)
        service.revertir(self.o, a, 'Corrección'); db.session.commit()
        self.assertEqual(self.o.saldo_actual, 9600000)
        self.assertEqual(self.o.cuotas_pendientes, 4)
        self.assertEqual(p.estado, 'parcial')
        self.assertEqual(p.valor_causado, 2400000)
        self.assertTrue(a.revertido)

    def test_validaciones(self):
        for changes in ({'cuota_valor': '2300000'}, {'descuento_intereses': '-1'},
                        {'valor_abono': '10000000'}, {'valor_abono': 'NaN'},
                        {'cuota_fecha': '2026-09-20'}, {'observaciones': ''},
                        {'cuota_fecha': ['2026-10-10', '2026-10-20'], 'cuota_valor': ['1200000', '1200000']}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.preparar(self.o, self.datos(**changes))
        self.assertEqual(AbonoCapitalObligacion.query.count(), 0)

    def test_rechaza_previa_obsoleta_y_reversion_con_cambios(self):
        datos = service.preparar(self.o, self.datos())
        self.o.saldo_actual = 9500000; db.session.commit()
        with self.assertRaises(ValueError): service.aplicar(self.o, datos)
        self.o.saldo_actual = 9600000; db.session.commit()
        a = self.aplicar()
        db.session.add(PagoObligacion(obligacion_id=self.o.id, anio=2026, mes=10, estado='causado', valor_causado=2400000))
        db.session.commit()
        with self.assertRaises(ValueError): service.revertir(self.o, a, 'Prueba')

    def test_pago_final_descuenta_total_pactado_incluyendo_intereses(self):
        self.aplicar()
        response = self.client.post('/obligaciones/pago', data={
            'obligacion_id': self.o.id, 'anio': 2026, 'mes': 10, 'accion': 'pagar',
            'valor_causado': '2400000', 'valor_pagado': '2400000', 'componente_capital': '2000000',
            'componente_interes': '400000', 'fecha_pago': '2026-10-10', 'estado': 'pagado'})
        self.assertEqual(response.status_code, 302)
        db.session.refresh(self.o)
        self.assertEqual(self.o.saldo_actual, 0)
        self.assertEqual(self.o.cuotas_pendientes, 0)

    def banco(self):
        self.o.modalidad = 'bancario_cuota_fija'
        self.o.fecha_inicio = date(2026, 10, 10)
        self.o.fecha_vencimiento = date(2027, 1, 10)
        self.o.tasa_interes_mensual = 0
        # Crédito existente sin cuota vencida a la fecha del abono.
        self.o.fecha_inicio = date(2026, 9, 1)
        self.o.dia_limite_pago = 25
        db.session.commit()
        return self.datos(opcion_recalculo='reducir_cuota', fecha_abono='2026-09-17',
            valor_abono='4800000', descuento_intereses='0', saldo_es_capital='1', primera_cuota='2026-09-25')

    def test_reducir_cuota_sin_interes(self):
        form = self.banco()
        a = self.aplicar(form)
        self.assertEqual(a.cuota_nueva, 1200000)
        self.assertEqual(a.cuotas_pendientes_despues, 4)
        self.assertEqual(sum(Decimal(f['capital']) for f in a.datos['plan']), Decimal('4800000'))

    def test_reducir_plazo_sin_interes(self):
        form = self.banco(); form['opcion_recalculo'] = 'reducir_plazo'
        a = self.aplicar(form)
        self.assertEqual(a.cuota_nueva, 2400000)
        self.assertEqual(a.cuotas_pendientes_despues, 2)

    def test_descuento_total_sin_cuotas(self):
        self.aplicar(self.datos(valor_abono='8800000', cuota_fecha=[], cuota_valor=[]))
        self.assertEqual(self.o.saldo_actual, 0)
        self.assertEqual(self.o.cuotas_pendientes, 0)

    def test_tasa_positiva_redondeo_y_pago_con_centavos(self):
        form = self.banco()
        self.o.tasa_interes_mensual = Decimal('1.25'); db.session.commit()
        a = self.aplicar(form)
        plan = a.datos['plan']
        self.assertEqual(len(plan), 4)
        self.assertEqual(sum(Decimal(f['capital']) for f in plan), Decimal('4800000'))
        self.assertGreater(sum(Decimal(f['total']) for f in plan), Decimal('4800000'))
        primera = plan[0]
        self.client.post('/obligaciones/pago', data={
            'obligacion_id': self.o.id, 'anio': 2026, 'mes': 9, 'accion': 'pagar',
            'valor_pagado': primera['total'], 'componente_capital': primera['capital'],
            'componente_interes': primera['interes'], 'fecha_pago': '2026-09-25', 'estado': 'pagado'})
        db.session.refresh(self.o)
        self.assertEqual(self.o.saldo_actual, Decimal('4800000') - Decimal(primera['capital']))
        self.assertEqual(self.o.cuotas_pendientes, 3)
        for fila in plan[1:]:
            fecha = date.fromisoformat(fila['fecha'])
            self.client.post('/obligaciones/pago', data={
                'obligacion_id': self.o.id, 'anio': fecha.year, 'mes': fecha.month, 'accion': 'pagar',
                'valor_pagado': fila['total'], 'componente_capital': fila['capital'],
                'componente_interes': fila['interes'], 'fecha_pago': fila['fecha'], 'estado': 'pagado'})
        db.session.refresh(self.o)
        self.assertEqual(self.o.saldo_actual, 0)
        self.assertEqual(self.o.cuotas_pendientes, 0)

    def test_acuerdo_reemplaza_cuotas_futuras_causadas(self):
        for mes in (9, 10, 11, 12):
            db.session.add(PagoObligacion(obligacion_id=self.o.id, anio=2026, mes=mes,
                                         estado='causado', valor_causado=2400000))
        db.session.commit()
        a = self.aplicar()
        self.assertEqual(PagoObligacion.query.filter_by(mes=10).one().estado, 'pendiente')
        self.assertEqual(PagoObligacion.query.filter_by(mes=11).one().estado, 'acordado')
        self.assertEqual(_resumen_vencido_obligacion(self.o, {(p.anio,p.mes): p for p in self.o.pagos},
                         2026, 9, date(2026, 9, 17))['total_vencido'], 0)
        service.revertir(self.o, a, 'Restaurar'); db.session.commit()
        self.assertTrue(all(p.estado == 'causado' for p in self.o.pagos))

    def test_cuotas_antiguas_no_se_pueden_pagar_tras_acuerdo(self):
        self.aplicar()
        response = self.client.post('/obligaciones/pago', data={
            'obligacion_id': self.o.id, 'anio': 2026, 'mes': 9, 'valor_pagado': '2400000'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PagoObligacion.query.count(), 0)
        self.assertEqual(self.o.saldo_actual, 2400000)

    def test_tabla_importada_no_se_recalcula_sin_acuerdo(self):
        form = self.banco()
        db.session.add(AmortizacionObligacion(obligacion_id=self.o.id, fecha_pago=date(2026,9,25),
                                             capital=2300000, intereses=100000, seguro_vida=12000))
        db.session.commit()
        with self.assertRaisesRegex(ValueError, 'tabla importada'):
            service.preparar(self.o, form)

    def test_confirmacion_no_reutilizable_despues_de_revertir(self):
        datos = service.preparar(self.o, self.datos())
        a = service.aplicar(self.o, datos); db.session.commit()
        service.revertir(self.o, a, 'Prueba'); db.session.commit()
        with self.assertRaises(ValueError): service.aplicar(self.o, datos)

    def test_obligacion_sin_abonos_conserva_calculos(self):
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 9), 2400000)
        self.assertEqual(_resumen_vencido_obligacion(self.o, {}, 2026, 9, date(2026,9,17))['total_vencido'], 2400000)

    def test_no_permite_desplazar_primera_cuota_automatica(self):
        form = self.banco(); form['primera_cuota'] = '2026-10-25'
        with self.assertRaisesRegex(ValueError, 'primer vencimiento'):
            service.preparar(self.o, form)

    def test_abono_total_bancario_no_exige_proximo_vencimiento(self):
        form = self.banco(); form['valor_abono'] = '9600000'; form['primera_cuota'] = ''
        self.aplicar(form)
        self.assertEqual(self.o.saldo_actual, 0)
        self.assertEqual(self.o.cuotas_pendientes, 0)


class MigracionAbonosTest(unittest.TestCase):
    def test_agrega_columna_sin_modificar_abonos_y_es_idempotente(self):
        ruta = Path(__file__).resolve().parents[1] / 'migrations/versions/20260917_01_abonos_con_plan.py'
        spec = importlib.util.spec_from_file_location('migracion_abonos', ruta)
        modulo = importlib.util.module_from_spec(spec); spec.loader.exec_module(modulo)
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE abonos_capital_obligaciones (id INTEGER PRIMARY KEY, valor_abono NUMERIC(14,2))'))
            connection.execute(text('INSERT INTO abonos_capital_obligaciones VALUES (1, 123456)'))
            modulo.op = Operations(MigrationContext.configure(connection))
            modulo.upgrade(); modulo.upgrade()
            self.assertIn('datos_movimiento', {c['name'] for c in inspect(connection).get_columns('abonos_capital_obligaciones')})
            self.assertEqual(connection.execute(text('SELECT valor_abono, datos_movimiento FROM abonos_capital_obligaciones')).one(), (123456, None))
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
