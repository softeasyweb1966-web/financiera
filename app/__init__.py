import logging
import os
import time

from flask import Flask, current_app
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

logger = logging.getLogger(__name__)

db = SQLAlchemy()
migrate = Migrate()


def _env_int(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _ensure_schema():
    from app.models import (
        AbonoCompra,
        AbonoGasto,
        AbonoNomina,
        AmortizacionObligacion,
        HistorialPagoObligacion,
        SaldoAnteriorNomina,
    )

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

    if not inspector.has_table('abonos_compras'):
        AbonoCompra.__table__.create(bind=db.engine, checkfirst=True)
        inspector = inspect(db.engine)

    if not inspector.has_table('abonos_gastos'):
        AbonoGasto.__table__.create(bind=db.engine, checkfirst=True)
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


def _ensure_schema_with_retries(max_attempts=None, retry_delay=None, strict=None):
    attempts = max_attempts if max_attempts is not None else _env_int('SCHEMA_INIT_MAX_ATTEMPTS', 2)
    delay_seconds = retry_delay if retry_delay is not None else _env_float('SCHEMA_INIT_RETRY_DELAY', 2.0)
    fail_hard = strict if strict is not None else _env_flag('SCHEMA_INIT_STRICT', False)
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            _ensure_schema()
            if attempt > 1:
                logger.info('Database schema initialization recovered on attempt %s.', attempt)
            return True
        except (OperationalError, SQLAlchemyError) as exc:
            last_error = exc
            db.session.remove()
            logger.warning(
                'Database schema initialization failed on attempt %s/%s: %s',
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts and delay_seconds > 0:
                time.sleep(delay_seconds)

    if fail_hard and last_error is not None:
        raise last_error

    logger.error(
        'Skipping startup schema initialization after %s failed attempt(s): %s. '
        'The application will stay online and retry later.',
        attempts,
        last_error,
    )
    return False


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

    app.extensions['schema_ready'] = False
    app.extensions['schema_retry_after'] = 0.0
    app.extensions['schema_retry_cooldown'] = _env_float('SCHEMA_INIT_REQUEST_RETRY_DELAY', 30.0)

    with app.app_context():
        app.extensions['schema_ready'] = _ensure_schema_with_retries()

    @app.before_request
    def ensure_schema_when_needed():
        if current_app.extensions.get('schema_ready'):
            return None

        now = time.time()
        retry_after = current_app.extensions.get('schema_retry_after', 0.0)
        if now < retry_after:
            return None

        current_app.extensions['schema_retry_after'] = (
            now + current_app.extensions.get('schema_retry_cooldown', 30.0)
        )
        current_app.extensions['schema_ready'] = _ensure_schema_with_retries(
            max_attempts=1,
            retry_delay=0,
            strict=False,
        )
        return None

    return app
