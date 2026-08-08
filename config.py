import os

def _database_url():
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        # Some platforms still provide postgres:// URLs, but SQLAlchemy expects postgresql://
        return database_url.replace('postgres://', 'postgresql://', 1)

    return 'postgresql+psycopg2://postgres:PreventPg2026Local1@127.0.0.1:5432/financiera_gastos'


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'financiera-dev-key-2026')
    
    # Base de datos INDEPENDIENTE - no toca prevent_utf8 ni ninguna otra
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
