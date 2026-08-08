# Tareas de Implementación — Sistema Financiero de Gastos Fijos

## Tarea 1: Limpiar BD anterior y crear nuevo modelo de datos
- [x] Eliminar la BD `financiera_gastos` existente y recrearla limpia
- [x] Reescribir `app/models.py` con todas las tablas del diseño (17 tablas)
- [x] Eliminar la carpeta `migrations/` existente
- [x] Inicializar Flask-Migrate y generar migración inicial
- [x] Ejecutar migración para crear todas las tablas

## Tarea 2: Crear script de datos semilla (seeds.py)
- [x] Crear `seeds.py` con: tipos de tercero, categorías, conceptos, medios de pago, conceptos de nómina, conceptos de compras, conceptos de gastos
- [x] Ejecutar el script para poblar catálogos base

## Tarea 3: Reestructurar rutas en Blueprints por módulo
- [x] Crear carpeta `app/routes/` con `__init__.py`
- [x] Crear `routes/main.py` (dashboard)
- [x] Crear `routes/terceros.py` (CRUD terceros)
- [x] Crear `routes/catalogos.py` (CRUD medios de pago, conceptos, categorías)
- [x] Crear `routes/servicios.py` (CRUD servicios + pagos + matriz)
- [x] Crear `routes/obligaciones.py` (CRUD obligaciones + refinanciaciones + pagos + matriz)
- [x] Crear `routes/nomina.py` (CRUD empleados + conceptos nómina + registros + matriz)
- [x] Crear `routes/compras.py` (CRUD conceptos compras + CRUD compras)
- [x] Crear `routes/gastos.py` (CRUD conceptos gastos + CRUD gastos)
- [x] Registrar todos los blueprints en `app/__init__.py`
- [x] Eliminar archivos y templates del modelo anterior

## Tarea 4: Crear plantillas base y navegación
- [x] Reescribir `templates/base.html` con navbar actualizada (todos los módulos + catálogos)
- [x] Crear `templates/index.html` (dashboard con resumen del mes)
- [ ] Crear `static/css/style.css` (estilos custom)
- [ ] Crear `static/js/app.js` (autocompletado, formato moneda, dinámicas de formulario)

## Tarea 5: Implementar módulo Terceros
- [x] Template `terceros/lista.html` con filtro por tipo
- [x] Template `terceros/form.html` con validaciones
- [x] Endpoint API `/api/terceros/buscar` para autocompletado dinámico

## Tarea 6: Implementar módulo Catálogos (Medios de Pago, Conceptos, Categorías)
- [x] Template `catalogos/medios_pago.html` (lista + formulario inline)
- [x] Template `catalogos/conceptos.html` (lista agrupada por categoría + form)
- [x] Template `catalogos/conceptos_nomina.html`
- [x] Template `catalogos/conceptos_compras.html`
- [x] Template `catalogos/conceptos_gastos.html`
- [x] Endpoints API para autocompletado de conceptos y medios de pago

## Tarea 7: Implementar módulo Servicios
- [x] Template `servicios/lista.html` con servicios activos
- [x] Template `servicios/form.html` (selección dinámica de tercero + concepto)
- [x] Template `servicios/pagos.html` (matriz anual con modal de registro que incluye medio de pago)
- [x] Lógica de creación/actualización de pagos (upsert)

## Tarea 8: Implementar módulo Obligaciones
- [x] Template `obligaciones/lista.html` con saldo, cuotas y modalidad
- [x] Template `obligaciones/form.html` (campos dinámicos según modalidad seleccionada)
- [x] Template `obligaciones/pagos.html` (matriz anual con componente capital/interés)
- [x] Template `obligaciones/refinanciaciones.html` (formulario y listado de refinanciaciones)
- [x] Lógica de cálculo de cuota (amortización francesa), interés mensual
- [x] Lógica de actualización automática de saldo al registrar pago
- [x] Lógica de refinanciación (registrar nueva condición, actualizar obligación)

## Tarea 9: Implementar módulo Nómina
- [x] Template `nomina/lista.html` (empleados activos con tipo de contrato)
- [x] Template `nomina/form.html` (datos empleado vinculado a tercero)
- [x] Template `nomina/pagos.html` (matriz quincenal con totales)
- [x] Template `nomina/registrar_quincena.html` (formulario masivo: seleccionar empleados + conceptos)
- [x] Lógica de múltiples conceptos por quincena por empleado

## Tarea 10: Implementar módulo Compras
- [x] Template `compras/lista.html` con filtros por concepto y estado
- [x] Template `compras/form.html` con selección dinámica de conceptos de compras y terceros
- [x] Totales del período seleccionado

## Tarea 11: Implementar módulo Gastos
- [x] Template `gastos/lista.html` con filtros por concepto y responsable
- [x] Template `gastos/form.html` con selección dinámica de conceptos de gastos y terceros
- [x] Totales del período seleccionado

## Tarea 12: Implementar Dashboard
- [x] Calcular totales del mes por módulo (servicios, obligaciones, nómina, compras, gastos)
- [x] Mostrar pendientes de servicios y obligaciones del mes
- [x] Selector de mes/año

## Tarea 13: Script de migración de datos desde Excel
- [ ] Reescribir `importar_excel.py` usando el nuevo modelo relacional
- [ ] Crear terceros a partir de empresas del Excel
- [ ] Crear servicios vinculados a terceros y conceptos
- [ ] Crear obligaciones con modalidad inferida según nombre
- [ ] Crear empleados y registros de nómina con conceptos
- [ ] Generar reporte de migración en consola (insertados, omitidos, errores)
- [ ] Ejecutar migración y verificar datos
