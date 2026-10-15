import unittest
import importlib.util
from pathlib import Path
from datetime import date
from decimal import Decimal

import test_abonos_obligaciones as fixtures
from app import db
from app.models import PagoObligacion, AjusteObligacion, AbonoCapitalObligacion
from app.routes.obligaciones import (
    _fechas_programadas_obligacion, _valor_programado_mes_obligacion,
    _valor_deuda_periodo_obligacion, _componentes_programados_periodo,
    _obligacion_visible_mes, _filas_deuda,
)
from app.routes.main import _items_obligaciones_mes
from app.permissions import permission_from_endpoint
from sqlalchemy import create_engine, text, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations


class InteresesTest(unittest.TestCase):
    setUp = fixtures.AbonosTest.setUp
    tearDown = fixtures.AbonosTest.tearDown

    def prestamo(self, tipo='anticipado'):
        self.o.modalidad = 'solo_interes'
        self.o.tipo_interes = tipo
        self.o.fecha_inicio = date(2026, 7, 10)
        self.o.fecha_vencimiento = date(2026, 10, 10)
        self.o.saldo_actual = 1000000
        self.o.capital_inicial = 1000000
        self.o.valor_cuota_fija = 100000
        self.o.requiere_desglose_pago = False
        db.session.commit()

    def pagar_capital(self):
        return self.client.post(f'/obligaciones/{self.o.id}/pagar-capital-intereses', data={
            'fecha_pago': '2026-10-10', 'capital_confirmado': '1000000', 'motivo': 'Transferencia capital'})

    def anular(self, mes=9, saldo='100000', motivo='Cobro que no corresponde'):
        return self.client.post(f'/obligaciones/{self.o.id}/anular-deuda', data={
            'anio': 2026, 'mes': mes, 'saldo_confirmado': saldo, 'motivo': motivo})

    def test_anticipado_excluye_mes_de_vencimiento(self):
        self.prestamo()
        self.assertEqual(_fechas_programadas_obligacion(self.o, 2026, 7), [date(2026, 7, 10)])
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 9), 100000)
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 10), 0)
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 11), 0)

    def test_vencido_empieza_mes_siguiente_y_cobra_al_final(self):
        self.prestamo('vencido')
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 7), 0)
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 10), 100000)
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 11), 0)

    def test_fin_mes_no_desplaza_aniversario(self):
        self.prestamo()
        self.o.fecha_inicio = date(2026, 1, 31)
        self.assertEqual(_fechas_programadas_obligacion(self.o, 2026, 2), [date(2026, 2, 28)])
        self.assertEqual(_fechas_programadas_obligacion(self.o, 2026, 3), [date(2026, 3, 31)])

    def test_legacy_no_cambia(self):
        self.prestamo(None)
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 10), 100000)

    def test_capital_cero_conserva_una_cuota_sin_inventar_pago(self):
        self.prestamo()
        for mes in (7, 8):
            db.session.add(PagoObligacion(obligacion_id=self.o.id, anio=2026, mes=mes,
                valor_causado=100000, valor_pagado=100000, componente_interes=100000,
                estado='pagado', fecha_pago=date(2026, mes, 10)))
        db.session.commit()
        self.assertEqual(self.pagar_capital().status_code, 302)
        self.assertEqual(self.o.saldo_actual, 0)
        self.assertEqual(_filas_deuda(self.o), [{'anio': 2026, 'mes': 9, 'saldo': 100000}])
        self.assertTrue(_obligacion_visible_mes(self.o, 2026, 11))
        p = self.o.pagos.filter_by(mes=9).one()
        self.assertEqual(p.valor_pagado, 0)
        self.assertEqual(_componentes_programados_periodo(self.o, 2026, 9)['interes'], 100000)
        self.assertEqual(AbonoCapitalObligacion.query.count(), 1)
        self.pagar_capital()
        self.assertEqual(AbonoCapitalObligacion.query.count(), 1)
        self.assertEqual(self.client.get(f'/obligaciones/{self.o.id}/gestionar-deuda').status_code, 200)
        self.assertEqual(self.client.get('/obligaciones/pagos/2026/10').status_code, 200)

    def test_anular_cuota_no_es_pago_y_se_puede_revertir(self):
        self.prestamo()
        self.anular()
        p = self.o.pagos.filter_by(mes=9).one()
        self.assertEqual(p.valor_pagado, 0)
        self.assertEqual(p.estado, 'saldo_anulado')
        self.assertEqual(_valor_deuda_periodo_obligacion(self.o, p, 2026, 9), 0)
        a = AjusteObligacion.query.one()
        self.assertEqual(a.valor, 100000)
        self.anular()
        self.assertEqual(AjusteObligacion.query.count(), 1)
        self.client.post(f'/obligaciones/{self.o.id}/revertir-deuda/{a.id}')
        self.assertTrue(a.revertido)
        self.assertEqual(_valor_deuda_periodo_obligacion(self.o, p, 2026, 9), 100000)

    def test_anular_residual_conserva_dinero_y_componentes(self):
        self.prestamo()
        p = PagoObligacion(obligacion_id=self.o.id, anio=2026, mes=9,
            valor_causado=100000, valor_pagado=40000, componente_interes=40000, estado='parcial')
        db.session.add(p)
        db.session.commit()
        self.anular(saldo='60000')
        self.assertEqual(p.valor_pagado, 40000)
        self.assertEqual(p.componente_interes, 40000)
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 9), 40000)
        self.assertEqual(_valor_deuda_periodo_obligacion(self.o, p, 2026, 9), 0)
        items, resumen = _items_obligaciones_mes(2026, 9, date(2026, 10, 15))
        self.assertEqual(items[0]['vencido'], 0)
        a = AjusteObligacion.query.one()
        self.client.post(f'/obligaciones/{self.o.id}/revertir-deuda/{a.id}')
        self.assertEqual(p.estado, 'parcial')
        self.assertEqual(_valor_deuda_periodo_obligacion(self.o, p, 2026, 9), 60000)

    def test_anulacion_requiere_motivo_y_saldo_actual(self):
        self.prestamo()
        self.anular(motivo='')
        self.anular(saldo='99999')
        self.assertEqual(AjusteObligacion.query.count(), 0)

    def test_cobro_ya_causado_no_desaparece_al_cambiar_tipo(self):
        self.prestamo()
        p = PagoObligacion(obligacion_id=self.o.id, anio=2026, mes=10,
            valor_causado=100000, valor_pagado=0, estado='causado')
        db.session.add(p)
        db.session.commit()
        self.assertEqual(_valor_deuda_periodo_obligacion(self.o, p, 2026, 10), 100000)
        self.assertTrue(_obligacion_visible_mes(self.o, 2026, 10))
        self.anular(mes=10)
        self.assertEqual(_valor_deuda_periodo_obligacion(self.o, p, 2026, 10), 0)

    def test_no_crear_cuota_extra_al_vencimiento(self):
        self.prestamo()
        response = self.client.post('/obligaciones/pago', data={
            'obligacion_id': self.o.id, 'anio': 2026, 'mes': 10})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PagoObligacion.query.count(), 0)

    def test_pagar_interes_despues_de_capital_no_cambia_capital(self):
        self.prestamo()
        self.pagar_capital()
        response = self.client.post('/obligaciones/pago', data={
            'obligacion_id': self.o.id, 'anio': 2026, 'mes': 9,
            'accion': 'pagar', 'valor_pagado': '100000', 'valor_causado': '100000',
            'estado': 'pagado', 'fecha_pago': '2026-10-15'})
        self.assertEqual(response.status_code, 302)
        p = self.o.pagos.filter_by(mes=9).one()
        self.assertEqual(p.componente_interes, 100000)
        self.assertEqual(self.o.saldo_actual, 0)
        self.assertEqual(_valor_deuda_periodo_obligacion(self.o, p, 2026, 9), 0)

    def test_permisos_de_anulacion_y_pago(self):
        self.assertEqual(permission_from_endpoint('obligaciones.anular_deuda', 'POST'), ('obligaciones', 'anular'))
        self.assertEqual(permission_from_endpoint('obligaciones.revertir_deuda', 'POST'), ('obligaciones', 'anular'))
        self.assertEqual(permission_from_endpoint('obligaciones.pagar_capital_intereses', 'POST'), ('obligaciones', 'pagar'))

    def test_bloquea_modificar_pago_con_saldo_anulado(self):
        self.prestamo()
        self.anular()
        p = self.o.pagos.filter_by(mes=9).one()
        self.client.post('/obligaciones/pago', data={
            'obligacion_id': self.o.id, 'anio': 2026, 'mes': 9,
            'accion': 'pagar', 'valor_pagado': '100000', 'fecha_pago': '2026-10-15'})
        self.assertEqual(p.estado, 'saldo_anulado')
        self.assertEqual(p.valor_pagado, 0)

    def test_intereses_calculados_se_conservan_al_saldar_capital(self):
        self.prestamo()
        self.o.valor_cuota_fija = None
        self.o.tasa_interes_mensual = Decimal('2')
        db.session.commit()
        self.pagar_capital()
        self.assertEqual(_valor_programado_mes_obligacion(self.o, 2026, 9), 20000)
        self.assertEqual(self.o.saldo_actual, 0)

    def test_formulario_muestra_parametro(self):
        response = self.client.get(f'/obligaciones/{self.o.id}/editar')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="tipo_interes"', response.data)


class MigracionInteresesTest(unittest.TestCase):
    def test_upgrade_idempotente_preserva_saldos(self):
        archivo = Path(__file__).parents[1] / 'migrations/versions/20261015_01_intereses_ajustes.py'
        spec = importlib.util.spec_from_file_location('migracion_intereses', archivo)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        engine = create_engine('sqlite://')
        with engine.begin() as conexion:
            conexion.execute(text('CREATE TABLE obligaciones (id INTEGER PRIMARY KEY, saldo_actual NUMERIC)'))
            conexion.execute(text('INSERT INTO obligaciones VALUES (1, 1000000)'))
            with Operations.context(MigrationContext.configure(conexion)):
                modulo.upgrade()
                modulo.upgrade()
            self.assertTrue(inspect(conexion).has_table('ajustes_obligaciones'))
            fila = conexion.execute(text('SELECT saldo_actual, tipo_interes, fecha_pago_capital FROM obligaciones')).one()
            self.assertEqual(tuple(fila), (1000000, None, None))


if __name__ == '__main__':
    unittest.main()
