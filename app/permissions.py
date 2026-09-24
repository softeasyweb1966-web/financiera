MENU_PERMISOS = [
    {
        'key': 'servicios',
        'label': 'Servicios',
        'icon': 'bi-lightning',
        'acciones': ['ver', 'crear', 'editar', 'pagar'],
    },
    {
        'key': 'obligaciones',
        'label': 'Obligaciones',
        'icon': 'bi-bank',
        'acciones': ['ver', 'crear', 'editar', 'pagar', 'anular'],
    },
    {
        'key': 'nomina',
        'label': 'Nomina',
        'icon': 'bi-people',
        'acciones': ['ver', 'crear', 'editar', 'pagar', 'anular'],
    },
    {
        'key': 'compras',
        'label': 'Compras y Gastos',
        'icon': 'bi-cart',
        'acciones': ['ver', 'crear', 'editar', 'pagar', 'anular'],
    },
    {
        'key': 'pendientes',
        'label': 'Pendientes',
        'icon': 'bi-calendar-check',
        'acciones': ['ver'],
    },
    {
        'key': 'terceros',
        'label': 'Terceros',
        'icon': 'bi-person-lines-fill',
        'acciones': ['ver', 'crear', 'editar'],
    },
    {
        'key': 'catalogos',
        'label': 'Catalogos',
        'icon': 'bi-tags',
        'acciones': ['ver', 'crear', 'editar'],
    },
    {
        'key': 'admin',
        'label': 'Usuarios y roles',
        'icon': 'bi-shield-lock',
        'acciones': ['ver', 'crear', 'editar'],
    },
]

ACCION_LABELS = {
    'ver': 'Ver',
    'crear': 'Crear',
    'editar': 'Editar',
    'pagar': 'Pagar',
    'anular': 'Anular',
}

PERMISSION_ACTIONS = set(ACCION_LABELS)
PERMISSION_MENUS = {menu['key'] for menu in MENU_PERMISOS}

ENDPOINT_MENU = {
    'servicios': 'servicios',
    'obligaciones': 'obligaciones',
    'nomina': 'nomina',
    'compras': 'compras',
    'gastos': 'compras',
    'catalogos': 'catalogos',
    'terceros': 'terceros',
}

MAIN_ENDPOINT_MENU = {
    'pendientes': 'pendientes',
}

CREATE_ENDPOINTS = {
    'nuevo',
    'nueva',
    'guardar',
    'registrar',
    'crear_concepto',
    'crear_item',
}

EDIT_ENDPOINTS = {
    'editar',
    'cambiar_estado',
    'toggle',
    'eliminar',
    'modificar_causacion',
    'refinanciar',
    'abonar_capital',
    'revertir_abono',
}

PAY_ENDPOINTS = {
    'pago',
    'registrar_pago',
    'pagar',
    'pagos',
    'pagar_saldos_historicos',
    'abonar',
}

CANCEL_ENDPOINTS = {
    'anular',
    'anular_pago',
    'ajustar_pago',
}


def permission_from_endpoint(endpoint, method='GET'):
    if not endpoint or '.' not in endpoint:
        return None

    blueprint, view = endpoint.split('.', 1)
    if blueprint == 'auth':
        if view == 'usuarios':
            return 'admin', 'ver'
        if view in {'guardar_usuario', 'toggle_usuario'}:
            return 'admin', 'editar'
        return None

    if blueprint == 'main':
        menu = MAIN_ENDPOINT_MENU.get(view)
        return (menu, 'ver') if menu else None

    menu = ENDPOINT_MENU.get(blueprint)
    if not menu:
        return None

    if method == 'GET':
        return menu, 'ver'

    if view in CANCEL_ENDPOINTS or 'anular' in view:
        return menu, 'anular'
    if view in PAY_ENDPOINTS or 'pago' in view or 'abono' in view:
        return menu, 'pagar'
    if view in CREATE_ENDPOINTS:
        return menu, 'crear'
    if view in EDIT_ENDPOINTS:
        return menu, 'editar'
    return menu, 'editar'
