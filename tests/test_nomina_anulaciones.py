import importlib.util
import unittest
from datetime import date
from pathlib import Path

from flask import Flask
from sqlalchemy import create_engine, inspect, text
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import db
from app.models import (
    AbonoNomina,
    ConceptoNomina,
    Empleado,
    HistorialCausacionNomina,
    HistorialPagoNomina,
    MedioPago,
    RegistroNomina,
    SaldoAnteriorNomina,
    Tercero,
    TipoTercero,
)
from app.routes import all_blueprints


class NominaAnulacionesTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder='../app/templates', static_folder='../app/static')
        self.app.config.update(TESTING=True, SECRET_KEY='test', SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        for bp in all_blueprints:
            self.app.register_blueprint(bp)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        tipo = TipoTercero(nombre='Empleado')
        tercero = Tercero(tipo_tercero_rel=tipo, nombre='JUAN NOMINA')
        concepto = ConceptoNomina(nombre='Salario', tipo='devengado')
        medio = MedioPago(nombre='Banco', activo=True)
        db.session.add_all([tipo, tercero, concepto, medio])
        db.session.flush()
        self.empleado = Empleado(
            tercero_id=tercero.id,
            cargo='Auxiliar',
            salario_base=1000000,
            tipo_contrato='laboral',
            forma_pago='quincenal',
        )
        db.session.add(self.empleado)
        db.session.commit()
        self.concepto = concepto
        self.medio = medio
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def registro(self, fecha_pago=None):
        r = RegistroNomina(
            empleado_id=self.empleado.id,
            concepto_nomina_id=self.concepto.id,
            anio=2026,
            mes=9,
            quincena=1,
            valor=1000000,
            fecha_pago=fecha_pago,
            medio_pago_id=self.medio.id if fecha_pago else None,
        )
        db.session.add(r)
        db.session.commit()
        return r

    def test_anula_abono_de_quincena_y_conserva_historial(self):
        r = self.registro(fecha_pago=date(2026, 9, 15))
        abono = AbonoNomina(
            empleado_id=self.empleado.id,
            anio=2026,
            mes=9,
            quincena=1,
            valor_abono=1000000,
            fecha_pago=date(2026, 9, 15),
            medio_pago_id=self.medio.id,
            descripcion='Pago quincena',
        )
        db.session.add(abono)
        db.session.commit()
        response = self.client.post(
            f'/nomina/abonos/{abono.id}/anular',
            data={'motivo': 'Pago duplicado', 'next': f'/nomina/detalle/{self.empleado.id}?anio=2026'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AbonoNomina.query.count(), 0)
        db.session.refresh(r)
        self.assertIsNone(r.fecha_pago)
        historial = HistorialPagoNomina.query.one()
        self.assertEqual(historial.tipo_pago, 'abono_periodo')
        self.assertEqual(historial.motivo, 'Pago duplicado')
        self.assertEqual(float(historial.valor_pagado), 1000000)

    def test_anula_pago_de_saldo_anterior_y_restaura_saldo(self):
        saldo = SaldoAnteriorNomina(
            empleado_id=self.empleado.id,
            anio=2026,
            mes=8,
            quincena=2,
            valor_inicial=500000,
            saldo_pendiente=0,
            estado='pagado',
        )
        db.session.add(saldo)
        db.session.flush()
        abono = AbonoNomina(
            empleado_id=self.empleado.id,
            saldo_anterior_nomina_id=saldo.id,
            anio=2026,
            mes=8,
            quincena=2,
            valor_abono=500000,
            fecha_pago=date(2026, 9, 10),
        )
        db.session.add(abono)
        db.session.commit()
        self.client.post(f'/nomina/abonos/{abono.id}/anular', data={'motivo': 'No correspondia'})
        db.session.refresh(saldo)
        self.assertEqual(float(saldo.saldo_pendiente), 500000)
        self.assertEqual(saldo.estado, 'pendiente')
        self.assertEqual(AbonoNomina.query.count(), 0)
        self.assertEqual(HistorialPagoNomina.query.one().tipo_pago, 'saldo_anterior')

    def test_anula_pago_directo_del_mes(self):
        r = self.registro(fecha_pago=date(2026, 9, 15))
        response = self.client.post(
            f'/nomina/{self.empleado.id}/periodo/anular-pago',
            data={'anio': '2026', 'mes': '9', 'quincena': '1', 'motivo': 'Pago mal registrado'},
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(r)
        self.assertIsNone(r.fecha_pago)
        self.assertIsNone(r.medio_pago_id)
        historial = HistorialPagoNomina.query.one()
        self.assertEqual(historial.tipo_pago, 'periodo_directo')
        self.assertEqual(historial.fecha_pago, date(2026, 9, 15))

    def test_modifica_causacion_sin_pago_y_guarda_historial(self):
        r = self.registro()
        response = self.client.post(
            f'/nomina/{self.empleado.id}/periodo/modificar-causacion',
            data={
                'anio': '2026',
                'mes': '9',
                'quincena': '1',
                'registro_id': str(r.id),
                'valor_causado': '1200000',
                'motivo': 'Valor causado errado',
                'next': f'/nomina/detalle/{self.empleado.id}?anio=2026',
            },
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(r)
        self.assertEqual(float(r.valor), 1200000)
        historial = HistorialCausacionNomina.query.one()
        self.assertEqual(float(historial.valor_anterior), 1000000)
        self.assertEqual(float(historial.valor_nuevo), 1200000)
        self.assertEqual(historial.motivo, 'Valor causado errado')
        self.assertIn('Valor causado errado', r.observaciones)

    def test_modifica_novedad_especifica_sin_sumar_al_concepto_base(self):
        concepto_novedad = ConceptoNomina(nombre='Novedad Enero', tipo='devengado')
        db.session.add(concepto_novedad)
        db.session.flush()
        base = self.registro()
        novedad = RegistroNomina(
            empleado_id=self.empleado.id,
            concepto_nomina_id=concepto_novedad.id,
            anio=2026,
            mes=9,
            quincena=1,
            valor=1750000,
        )
        db.session.add(novedad)
        db.session.commit()

        response = self.client.post(
            f'/nomina/{self.empleado.id}/periodo/modificar-causacion',
            data={
                'anio': '2026',
                'mes': '9',
                'quincena': '1',
                'registro_id': str(novedad.id),
                'valor_causado': '1800000',
                'motivo': 'Correccion novedad enero',
            },
        )

        self.assertEqual(response.status_code, 302)
        db.session.refresh(base)
        db.session.refresh(novedad)
        self.assertEqual(float(base.valor), 1000000)
        self.assertEqual(float(novedad.valor), 1800000)
        historial = HistorialCausacionNomina.query.one()
        self.assertEqual(float(historial.valor_anterior), 1750000)
        self.assertEqual(float(historial.valor_nuevo), 1800000)
        self.assertEqual(historial.concepto_principal_id, concepto_novedad.id)

    def test_no_modifica_causacion_con_pago_activo(self):
        r = self.registro(fecha_pago=date(2026, 9, 15))
        abono = AbonoNomina(
            empleado_id=self.empleado.id,
            anio=2026,
            mes=9,
            quincena=1,
            valor_abono=1000000,
            fecha_pago=date(2026, 9, 15),
            medio_pago_id=self.medio.id,
        )
        db.session.add(abono)
        db.session.commit()
        response = self.client.post(
            f'/nomina/{self.empleado.id}/periodo/modificar-causacion',
            data={
                'anio': '2026',
                'mes': '9',
                'quincena': '1',
                'registro_id': str(r.id),
                'valor_causado': '1200000',
                'motivo': 'Valor causado errado',
            },
        )
        self.assertEqual(response.status_code, 302)
        db.session.refresh(r)
        self.assertEqual(float(r.valor), 1000000)
        self.assertEqual(HistorialCausacionNomina.query.count(), 0)

    def test_detalle_muestra_opciones_e_historial(self):
        self.registro(fecha_pago=date(2026, 9, 15))
        html = self.client.get(f'/nomina/detalle/{self.empleado.id}?anio=2026').text
        self.assertIn('modalAnularPagoNomina', html)
        self.assertIn('modalModificarCausacionNomina', html)
        self.assertIn('Historial de anulaciones de pagos', html)
        self.assertIn('Historial de modificaciones de causacion', html)
        self.assertIn('modificar-causacion', html)
        self.assertIn('anular-pago', html)


class MigracionHistorialPagoNominaTest(unittest.TestCase):
    def test_migracion_es_idempotente(self):
        ruta = Path(__file__).resolve().parents[1] / 'migrations/versions/20260917_04_historial_pagos_nomina.py'
        spec = importlib.util.spec_from_file_location('migracion_historial_nomina', ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        engine = create_engine('sqlite://')
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE empleados (id INTEGER PRIMARY KEY)'))
            conn.execute(text('CREATE TABLE registros_nomina (id INTEGER PRIMARY KEY)'))
            conn.execute(text('CREATE TABLE saldos_anteriores_nomina (id INTEGER PRIMARY KEY)'))
            conn.execute(text('CREATE TABLE medios_pago (id INTEGER PRIMARY KEY)'))
            modulo.op = Operations(MigrationContext.configure(conn))
            modulo.upgrade()
            modulo.upgrade()
            inspector = inspect(conn)
            self.assertTrue(inspector.has_table('historial_pagos_nomina'))
            columnas = {c['name'] for c in inspector.get_columns('historial_pagos_nomina')}
            self.assertIn('motivo', columnas)
            self.assertIn('tipo_pago', columnas)
        engine.dispose()


class MigracionHistorialCausacionNominaTest(unittest.TestCase):
    def test_migracion_es_idempotente(self):
        ruta = Path(__file__).resolve().parents[1] / 'migrations/versions/20260917_05_historial_causaciones_nomina.py'
        spec = importlib.util.spec_from_file_location('migracion_historial_causacion_nomina', ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        engine = create_engine('sqlite://')
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE empleados (id INTEGER PRIMARY KEY)'))
            conn.execute(text('CREATE TABLE conceptos_nomina (id INTEGER PRIMARY KEY)'))
            modulo.op = Operations(MigrationContext.configure(conn))
            modulo.upgrade()
            modulo.upgrade()
            inspector = inspect(conn)
            self.assertTrue(inspector.has_table('historial_causaciones_nomina'))
            columnas = {c['name'] for c in inspector.get_columns('historial_causaciones_nomina')}
            self.assertIn('motivo', columnas)
            self.assertIn('valor_anterior', columnas)
            self.assertIn('valor_nuevo', columnas)
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
