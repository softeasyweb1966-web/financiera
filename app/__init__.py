from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import inspect, text

db = SQLAlchemy()
migrate = Migrate()


def _ensure_schema():
    inspector = inspect(db.engine)
    if not inspector.has_table('tipo_tercero'):
        db.create_all()
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
        if 'referencia' not in columnas_obligaciones:
            db.session.execute(text('ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS referencia VARCHAR(50)'))
        if 'frecuencia_pago' not in columnas_obligaciones:
            db.session.execute(text("ALTER TABLE obligaciones ADD COLUMN IF NOT EXISTS frecuencia_pago VARCHAR(20) DEFAULT 'mensual'"))
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
