import importlib.util
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from flask import Flask
from werkzeug.datastructures import MultiDict
from sqlalchemy import create_engine, inspect, text
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import db
from app.compras_credito import calendario
from app.models import Compra, CuotaCompra, AbonoCompra, ConceptoCompra
from app.routes import all_blueprints


class ComprasCreditoTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder='../app/templates', static_folder='../app/static')
        self.app.config.update(TESTING=True, SECRET_KEY='test', SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        for bp in all_blueprints: self.app.register_blueprint(bp)
        self.ctx = self.app.app_context(); self.ctx.push()
        db.create_all()
        self.concepto = ConceptoCompra(nombre='Equipos')
        db.session.add(self.concepto); db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def form(self, **changes):
        data = MultiDict({'fecha': '2026-09-01', 'concepto_compra_id': str(self.concepto.id),
            'descripcion': 'Computador', 'valor': '1000000', 'condicion_pago': 'credito',
            'paga_inicial': 'si', 'valor_abono_inicial': '200000', 'fecha_pago': '2026-09-02',
            'cuota_fecha': ['2026-10-10', '2026-11-10'], 'cuota_valor': ['400000', '400000']})
        for k, v in changes.items(): data.setlist(k, v if isinstance(v, list) else [v])
        return data

    def crear(self, **changes):
        response = self.client.post('/compras/nueva', data=self.form(**changes))
        self.assertEqual(response.status_code, 302, response.text)
        return Compra.query.one()

    def test_credito_con_inicial_y_fechas_persistidas(self):
        c = self.crear()
        self.assertEqual(c.condicion_pago, 'credito')
        self.assertEqual(c.estado, 'parcial')
        self.assertEqual(AbonoCompra.query.one().fecha_pago, date(2026,9,2))
        plan = calendario(c)
        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[0]['estado'], 'Pagada')
        self.assertEqual(plan[1]['cuota'].fecha_vencimiento, date(2026,10,10))
        self.assertEqual(sum(f['saldo'] for f in plan), 800000)
        for path in (f'/compras/detalle/{c.id}', '/compras/2026/10', f'/compras/{c.id}/editar', '/compras/nueva'):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertIn('Computador', self.client.get('/compras/2026/10').text)

    def test_credito_sin_abono_no_registra_dinero_ni_fecha_real(self):
        c = self.crear(paga_inicial='no', valor_abono_inicial='999999', fecha_pago='invalida',
                       cuota_valor=['500000','500000'])
        self.assertEqual(c.estado, 'pendiente')
        self.assertIsNone(c.fecha_pago)
        self.assertEqual(AbonoCompra.query.count(), 0)
        self.assertEqual(CuotaCompra.query.count(), 2)
        self.assertEqual(sum(f['saldo'] for f in calendario(c)), 1000000)

    def test_contado_paga_total_sin_cuotas(self):
        c = self.crear(condicion_pago='contado', valor_abono_inicial='20')
        self.assertEqual(c.estado, 'pagado')
        self.assertEqual(AbonoCompra.query.one().valor_abono, 1000000)
        self.assertEqual(CuotaCompra.query.count(), 0)

    def test_pago_parcial_varias_fechas_y_pago_total(self):
        c = self.crear()
        for valor, fecha in [('150000', '2026-09-03'), ('300000', '2026-09-04')]:
            self.client.post(f'/compras/{c.id}/abonar', data={'valor_abono': valor, 'fecha_pago': fecha})
        plan = calendario(c)
        self.assertEqual(plan[1]['saldo'], 0)
        self.assertEqual([p['fecha'] for p in plan[1]['pagos']], [date(2026,9,3), date(2026,9,4)])
        self.assertEqual(plan[2]['saldo'], 350000)
        self.client.post(f'/compras/{c.id}/abonar', data={'valor_abono':'350000','fecha_pago':'2026-09-05'})
        db.session.refresh(c)
        self.assertEqual(c.estado, 'pagado')
        self.assertEqual(sum(f['saldo'] for f in calendario(c)), 0)

    def test_rechaza_calendario_incompleto_sin_escribir(self):
        for cambios in ({'cuota_valor':['300000','400000']}, {'cuota_fecha':[],'cuota_valor':[]},
                        {'cuota_fecha':['','2026-11-10']}, {'cuota_valor':['-1','800001']},
                        {'fecha_pago':''}, {'valor':'NaN'}, {'valor_abono_inicial':'1000001'},
                        {'cuota_fecha':['2026-08-01','2026-11-10']}, {'paga_inicial':''}):
            with self.subTest(cambios=cambios):
                response = self.client.post('/compras/nueva', data=self.form(**cambios))
                self.assertEqual(response.status_code, 400)
                self.assertIn('Computador', response.text)
                self.assertEqual(Compra.query.count(), 0)
                self.assertEqual(AbonoCompra.query.count(), 0)

    def test_abono_invalido_no_paga_saldo_por_defecto(self):
        c = self.crear()
        for valor in ('0','-1','NaN','800001', '1.001'):
            self.client.post(f'/compras/{c.id}/abonar', data={'valor_abono':valor,'fecha_pago':'2026-09-03'})
        self.assertEqual(AbonoCompra.query.count(), 1)
        self.assertEqual(sum(f['saldo'] for f in calendario(c)), 800000)

    def test_editar_no_desajusta_calendario(self):
        c = self.crear()
        response = self.client.post(f'/compras/{c.id}/editar', data=self.form(valor='2000000'))
        self.assertEqual(response.status_code, 400)
        db.session.refresh(c)
        self.assertEqual(c.valor, 1000000)
        self.assertEqual(sum(q.valor for q in c.cuotas), 1000000)

    def test_legacy_pagado_conserva_historial(self):
        c = Compra(fecha=date(2026,9,1), concepto_compra_id=self.concepto.id,
                   descripcion='Anterior', valor=500000, estado='pagado', fecha_pago=date(2026,9,1))
        db.session.add(c); db.session.commit()
        response = self.client.get(f'/compras/detalle/{c.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calendario(c), [])
        self.assertIn('dato legado', response.text)

    def test_valores_con_centavos_cuadran(self):
        c = self.crear(valor='1000.75', valor_abono_inicial='100.25', cuota_valor=['400.25','500.25'])
        self.assertEqual(sum(f['saldo'] for f in calendario(c)), Decimal('900.50'))


class MigracionComprasTest(unittest.TestCase):
    def test_migracion_idempotente_conserva_compras(self):
        ruta = Path(__file__).resolve().parents[1] / 'migrations/versions/20260917_02_cuotas_compras.py'
        spec = importlib.util.spec_from_file_location('migracion_compras', ruta)
        modulo = importlib.util.module_from_spec(spec); spec.loader.exec_module(modulo)
        engine = create_engine('sqlite://')
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE compras (id INTEGER PRIMARY KEY, valor NUMERIC(14,2))'))
            conn.execute(text('INSERT INTO compras VALUES (1, 500000)'))
            modulo.op = Operations(MigrationContext.configure(conn))
            modulo.upgrade(); modulo.upgrade()
            self.assertTrue(inspect(conn).has_table('cuotas_compras'))
            self.assertEqual(conn.execute(text('SELECT valor, condicion_pago FROM compras')).one(), (500000,None))
        engine.dispose()


if __name__ == '__main__': unittest.main()
