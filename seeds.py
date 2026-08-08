"""
Script de datos semilla para el Sistema Financiero.
Pobla los catálogos base: tipos de tercero, categorías, conceptos,
medios de pago, conceptos de nómina, compras y gastos.

Uso: venv\Scripts\python.exe seeds.py
"""
from app import create_app, db
from app.models import (
    TipoTercero, Categoria, Concepto, MedioPago,
    ConceptoNomina, ConceptoCompra, ConceptoGasto
)


def seed_tipos_tercero():
    tipos = [
        ('Empleado', 'Persona vinculada a la nómina'),
        ('Proveedor', 'Empresa o persona que vende bienes o servicios'),
        ('Entidad Financiera', 'Banco o entidad de crédito'),
        ('Empresa Servicios', 'Empresa prestadora de servicios públicos o fijos'),
        ('Prestamista Personal', 'Persona natural que presta dinero'),
    ]
    count = 0
    for nombre, desc in tipos:
        if not TipoTercero.query.filter_by(nombre=nombre).first():
            db.session.add(TipoTercero(nombre=nombre, descripcion=desc))
            count += 1
    db.session.commit()
    print(f'  Tipos de tercero: {count} insertados')


def seed_categorias():
    categorias = [
        ('Servicios Públicos', 'Servicios recurrentes: agua, luz, gas, teléfono, arriendo'),
        ('Obligaciones Bancarias', 'Créditos, préstamos, cadenas'),
        ('Nómina', 'Pagos de nómina y parafiscales'),
        ('Compras', 'Adquisición de bienes'),
        ('Gastos', 'Gastos operativos varios'),
    ]
    count = 0
    for nombre, desc in categorias:
        if not Categoria.query.filter_by(nombre=nombre).first():
            db.session.add(Categoria(nombre=nombre, descripcion=desc))
            count += 1
    db.session.commit()
    print(f'  Categorías: {count} insertadas')


def seed_conceptos():
    conceptos_por_cat = {
        'Servicios Públicos': [
            'Acueducto', 'Energía', 'Gas', 'Teléfono', 'Internet',
            'Celular', 'Arriendo', 'Vigilancia', 'Plan exequial',
            'Software/Plataforma', 'Otro Servicio'
        ],
        'Obligaciones Bancarias': [
            'Cuota hipotecaria', 'Cuota consumo', 'Interés préstamo personal',
            'Cadena', 'Abono capital', 'Otro bancario'
        ],
    }
    count = 0
    for cat_nombre, conceptos in conceptos_por_cat.items():
        cat = Categoria.query.filter_by(nombre=cat_nombre).first()
        if cat:
            for concepto_nombre in conceptos:
                if not Concepto.query.filter_by(categoria_id=cat.id, nombre=concepto_nombre).first():
                    db.session.add(Concepto(categoria_id=cat.id, nombre=concepto_nombre))
                    count += 1
    db.session.commit()
    print(f'  Conceptos: {count} insertados')


def seed_medios_pago():
    medios = [
        ('Efectivo', 'Pago en efectivo'),
        ('Transferencia', 'Transferencia bancaria'),
        ('Consignación', 'Consignación en ventanilla'),
        ('Cheque', 'Pago con cheque'),
        ('Nequi', 'Pago por Nequi'),
        ('Daviplata', 'Pago por Daviplata'),
        ('Tarjeta débito', 'Pago con tarjeta débito'),
        ('Tarjeta crédito', 'Pago con tarjeta de crédito'),
    ]
    count = 0
    for nombre, desc in medios:
        if not MedioPago.query.filter_by(nombre=nombre).first():
            db.session.add(MedioPago(nombre=nombre, descripcion=desc))
            count += 1
    db.session.commit()
    print(f'  Medios de pago: {count} insertados')


def seed_conceptos_nomina():
    conceptos = [
        ('Salario', 'devengado', 'Pago quincenal de salario'),
        ('Auxilio Transporte', 'devengado', 'Auxilio de transporte legal'),
        ('Bonificación', 'devengado', 'Bonificación o incentivo'),
        ('Prima', 'devengado', 'Prima de servicios'),
        ('Vacaciones', 'devengado', 'Pago de vacaciones'),
        ('Honorarios', 'devengado', 'Pago por prestación de servicios'),
        ('Seguridad Social', 'deduccion', 'Aporte a salud y pensión del empleado'),
        ('Parafiscales', 'deduccion', 'Aportes parafiscales (SENA, ICBF, Caja)'),
        ('Deducción', 'deduccion', 'Deducción general'),
        ('Anticipo', 'deduccion', 'Anticipo entregado al empleado'),
        ('Novedad', 'devengado', 'Novedad de nómina'),
    ]
    count = 0
    for nombre, tipo, desc in conceptos:
        if not ConceptoNomina.query.filter_by(nombre=nombre).first():
            db.session.add(ConceptoNomina(nombre=nombre, tipo=tipo, descripcion=desc))
            count += 1
    db.session.commit()
    print(f'  Conceptos nómina: {count} insertados')


def seed_conceptos_compras():
    conceptos = [
        ('Materiales', 'Materiales de construcción o mantenimiento'),
        ('Equipos', 'Equipos médicos, tecnológicos u operativos'),
        ('Insumos', 'Insumos médicos o de laboratorio'),
        ('Papelería', 'Artículos de papelería y oficina'),
        ('Mobiliario', 'Muebles y enseres'),
        ('Tecnología', 'Computadores, software, licencias'),
        ('Otro', 'Compra no clasificada'),
    ]
    count = 0
    for nombre, desc in conceptos:
        if not ConceptoCompra.query.filter_by(nombre=nombre).first():
            db.session.add(ConceptoCompra(nombre=nombre, descripcion=desc))
            count += 1
    db.session.commit()
    print(f'  Conceptos compras: {count} insertados')


def seed_conceptos_gastos():
    conceptos = [
        ('Alimentación', 'Gastos de alimentación y restaurantes'),
        ('Transporte', 'Gastos de transporte, taxis, combustible'),
        ('Papelería', 'Artículos de papelería'),
        ('Representación', 'Gastos de representación y eventos'),
        ('Mantenimiento', 'Mantenimiento de equipos e instalaciones'),
        ('Aseo', 'Productos y servicios de aseo'),
        ('Viáticos', 'Viáticos y gastos de viaje'),
        ('Otro gasto', 'Gasto no clasificado'),
    ]
    count = 0
    for nombre, desc in conceptos:
        if not ConceptoGasto.query.filter_by(nombre=nombre).first():
            db.session.add(ConceptoGasto(nombre=nombre, descripcion=desc))
            count += 1
    db.session.commit()
    print(f'  Conceptos gastos: {count} insertados')


def main():
    app = create_app()
    with app.app_context():
        print('\n=== Cargando datos semilla ===\n')
        seed_tipos_tercero()
        seed_categorias()
        seed_conceptos()
        seed_medios_pago()
        seed_conceptos_nomina()
        seed_conceptos_compras()
        seed_conceptos_gastos()
        print('\n✓ Datos semilla cargados exitosamente.\n')


if __name__ == '__main__':
    main()
