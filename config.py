import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'financiera-dev-key-2026')
    
    # Base de datos INDEPENDIENTE - no toca prevent_utf8 ni ninguna otra
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql+psycopg2://postgres:PreventPg2026Local1@127.0.0.1:5432/financiera_gastos'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
