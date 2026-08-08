from app.routes.main import main_bp
from app.routes.terceros import terceros_bp
from app.routes.catalogos import catalogos_bp
from app.routes.servicios import servicios_bp
from app.routes.obligaciones import obligaciones_bp
from app.routes.nomina import nomina_bp
from app.routes.compras import compras_bp
from app.routes.gastos import gastos_bp

all_blueprints = [
    main_bp,
    terceros_bp,
    catalogos_bp,
    servicios_bp,
    obligaciones_bp,
    nomina_bp,
    compras_bp,
    gastos_bp,
]
