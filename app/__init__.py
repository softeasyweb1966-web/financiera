from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

db = SQLAlchemy()
migrate = Migrate()


def _ensure_schema():
    from app.models import AmortizacionObligacion, HistorialPagoObligacion, SaldoAnteriorNomina, AbonoNomina

    inspector = inspect(db.engine)
    if not inspector.has_table('tipo_tercero'):
        db.create_all()
        inspector = inspect(db.engine)

    if not inspector.has_table('historial_pagos_obligaciones'):
        HistorialPagoObligacion.__table__.create(bind=db.engine, checkfirst=True)
        inspector = inspect(db.engine)

    if not inspector.has_table('amortizaciones_obligaciones'):
        try:
            AmortizacionObligacion.__table__.create(bind=db.engine, checkfirst=True)
        except SQLAlchemyError:
            db.session.rollback()
            db.session.execute(text('DROP SEQUENCE IF EXISTS amortizaciones_obligaciones_id_seq CASCADE'))
            db.session.commit()
            AmortizacionObligacion.__table__.create(bind=db.engine, checkfirst=True)
        inspector = inspect(db.engine)

    if not inspector.has_table('saldos_anteriores_nomina'):
        SaldoAnteriorNomina.__table__.create(bind=db.engine, checkfirst=True)
        inspector = inspect(db.engine)

    if not inspector.has_table('abonos_nomina'):
        AbonoNomina.__table__.create(bind=db.engine, checkfirst=True)
        inspector = inspect(db.engine)

    if inspector.has_table('historial_estados'):
        columnas = {col['name'] for col in inspector.get_columns('historial_estados')}
        if 'vigencia_desde' not in columnas:
            db.session.execute(text('ALTER TABLE historial_estados ADD COLUMN IF NOT EXISTS vigencia_desde DATE'))
            db.session.commit()

    if inspector.has_table('obligaciones'):
        columnas_obligaciones = {col['name'] for col in inspector.get_columns('obligaciones')}
        if 'fecha_recibe' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS fecha_recibe DATE'))
        if 'fecha_finalizacion' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS fecha_finalizacion DATE'))
        if 'fecha_inicio_amortizacion' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS fecha_inicio_amortizacion DATE'))
        if 'referencia' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS referencia VARCHAR(50)'))
        if 'soporte_amortizacion_nombre' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS soporte_amortizacion_nombre VARCHAR(255)'))
        if 'soporte_amortizacion_mime' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS soporte_amortizacion_mime VARCHAR(120)'))
        if 'soporte_amortizacion_archivo' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS soporte_amortizacion_archivo BYTEA'))
        if 'frecuencia_pago' not in columnas_obligaciones:
            db.session.execute(text("ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS frecuencia_pago VARCHAR(20) DEFAULT 'mensual'"))
        if 'requiere_desglose_pago' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS requiere_desglose_pago BOOLEAN DEFAULT FALSE'))
        if 'valor_cuota_capital' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS valor_cuota_capital NUMERIC(14, 2)'))
        if 'valor_cuota_interes' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS valor_cuota_interes NUMERIC(14, 2)'))
        db.session.commit()

    if inspector.has_table('amortizaciones_obligaciones'):
        columnas_amortizaciones = {col['name'] for col in inspector.get_columns('amortizaciones_obligaciones')}
        if 'seguro_vida' not in columnas_amortizaciones:
            db.session.execute(text('ALTER TABLE amortizaciones_obligaciones ADD COLUMN IF NOT EXISTS seguro_vida NUMERIC(14, 2) DEFAULT 0'))
        if 'otros' not in columnas_amortizaciones:
            db.session.execute(text('ALTER TABLE amortizaciones_obligaciones ADD COLUMN IF NOT EXISTS otros NUMERIC(14, 2) DEFAULT 0'))
        if 'tasa_namv' not in columnas_amortizaciones:
            db.session.execute(text('ALTER TABLE amortizaciones_obligaciones ADD COLUMN IF NOT EXISTS tasa_namv NUMERIC(8, 4)'))
        if 'saldo_capital' not in columnas_amortizaciones:
            db.session.execute(text('ALTER TABLE amortizaciones_obligaciones ADD COLUMN IF NOT EXISTS saldo_capital NUMERIC(14, 2)'))
        if 'updated_at' not in columnas_amortizaciones:
            db.session.execute(text('ALTER TABLE amortizaciones_obligaciones ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP'))
        db.session.commit()

    if inspector.has_table('refinanciaciones'):
        columnas_refinanciaciones = {col['name'] for col in inspector.get_columns('refinanciaciones')}
        if 'nuevo_valor_cuota_capital' not in columnas_refinanciaciones:
            db.session.execute(text('ALTER TABLE refinanciaciones ADD COLUMN IF NOT EXISTS nuevo_valor_cuota_capital NUMERIC(14, 2)'))
        if 'nuevo_valor_cuota_interes' not in columnas_refinanciaciones:
            db.session.execute(text('ALTER TABLE refinanciaciones ADD COLUMN IF NOT EXISTS nuevo_valor_cuota_interes NUMERIC(14, 2)'))
        db.session.commit()

    if inspector.has_table('pagos_servicios'):
        columnas_pagos_servicios = {col['name'] for col in inspector.get_columns('pagos_servicios')}
        if 'dia_pago_reportado' not in columnas_pagos_servicios:
            db.session.execute(text('ALTER TABLE pagos_servicios ADD COLUMN IF NOT EXISTS dia_pago_reportado INTEGER'))
        if 'comprobante_nombre' not in columnas_pagos_servicios:
            db.session.execute(text('ALTER TABLE pagos_servicios ADD COLUMN IF NOT EXISTS comprobante_nombre VARCHAR(255)'))
        if 'comprobante_mime' not in columnas_pagos_servicios:
            db.session.execute(text('ALTER TABLE pagos_servicios ADD COLUMN IF NOT EXISTS comprobante_mime VARCHAR(120)'))
        if 'comprobante_archivo' not in columnas_pagos_servicios:
            db.session.execute(text('ALTER TABLE pagos_servicios ADD COLUMN IF NOT EXISTS comprobante_archivo BYTEA'))
        db.session.commit()

    if inspector.has_table('pagos_obligaciones'):
        columnas_pagos_obligaciones = {col['name'] for col in inspector.get_columns('pagos_obligaciones')}
        if 'dia_pago_reportado' not in columnas_pagos_obligaciones:
            db.session.execute(text('ALTER TABLE pagos_obligaciones ADD COLUMN IF NOT EXISTS dia_pago_reportado INTEGER'))
        if 'componente_seguro_vida' not in columnas_pagos_obligaciones:
            db.session.execute(text('ALTER TABLE pagos_obligaciones ADD COLUMN IF NOT EXISTS componente_seguro_vida NUMERIC(14, 2)'))
        if 'componente_otros' not in columnas_pagos_obligaciones:
            db.session.execute(text('ALTER TABLE pagos_obligaciones ADD COLUMN IF NOT EXISTS componente_otros NUMERIC(14, 2)'))
        if 'componente_anticipo' not in columnas_pagos_obligaciones:
            db.session.execute(text('ALTER TABLE pagos_obligaciones ADD COLUMN IF NOT EXISTS componente_anticipo NUMERIC(14, 2)'))
        if 'comprobante_nombre' not in columnas_pagos_obligaciones:
            db.session.execute(text('ALTER TABLE pagos_obligaciones ADD COLUMN IF NOT EXISTS comprobante_nombre VARCHAR(255)'))
        if 'comprobante_mime' not in columnas_pagos_obligaciones:
            db.session.execute(text('ALTER TABLE pagos_obligaciones ADD COLUMN IF NOT EXISTS comprobante_mime VARCHAR(120)'))
        if 'comprobante_archivo' not in columnas_pagos_obligaciones:
            db.session.execute(text('ALTER TABLE pagos_obligaciones ADD COLUMN IF NOT EXISTS comprobante_archivo BYTEA'))
        db.session.commit()

    if inspector.has_table('historial_pagos_obligaciones'):
        columnas_historial_pagos = {col['name'] for col in inspector.get_columns('historial_pagos_obligaciones')}
        if 'componente_seguro_vida' not in columnas_historial_pagos:
            db.session.execute(text('ALTER TABLE historial_pagos_obligaciones ADD COLUMN IF NOT EXISTS componente_seguro_vida NUMERIC(14, 2)'))
        if 'componente_otros' not in columnas_historial_pagos:
            db.session.execute(text('ALTER TABLE historial_pagos_obligaciones ADD COLUMN IF NOT EXISTS componente_otros NUMERIC(14, 2)'))
        if 'componente_anticipo' not in columnas_historial_pagos:
            db.session.execute(text('ALTER TABLE historial_pagos_obligaciones ADD COLUMN IF NOT EXISTS componente_anticipo NUMERIC(14, 2)'))
        db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    db.init_app(app)
    migrate.init_app(app, db)

    # Importar modelos para que Alembic los detecte
    from app import models  # noqa: F401

    # Registrar todos los blueprints
    from app.routes import all_blueprints
    for bp in all_blueprints:
        app.register_blueprint(bp)

    # En despliegues nuevos, Railway puede partir de una base vacía.
    # Creamos el esquema base para evitar 500s por tablas inexistentes.
    with app.app_context():
        _ensure_schema()

    return app
