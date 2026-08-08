# Documento de Requisitos — Sistema Financiero de Gastos Fijos

## Introducción

Rediseño completo de un sistema de gestión financiera que reemplaza hojas de cálculo Excel. El sistema administra Servicios Públicos, Obligaciones Financieras (Bancos), Nómina, Compras y Gastos de una empresa colombiana. El objetivo es usar estructura relacional con tablas maestras (catálogos), evitar la lógica de cuadrícula de Excel, y construir una base sólida y extensible.

La aplicación corre en Python/Flask con PostgreSQL (`financiera_gastos`), bootstrap 5, y vive en `c:\python\financiera` usando el venv existente. La base de datos es completamente independiente y **no debe tocar** `prevent_utf8` ni ninguna otra base existente.

---

## Glosario

- **Sistema**: La aplicación web Flask de gestión financiera.
- **Tercero**: Persona natural o jurídica registrada en el catálogo maestro (empleado, proveedor, entidad financiera, empresa de servicios, prestamista personal).
- **Tipo_Tercero**: Clasificación de un Tercero. Valores: `Empleado`, `Proveedor`, `Entidad Financiera`, `Empresa de Servicios`, `Prestamista Personal`.
- **Categoría**: Agrupación contable de conceptos. Valores iniciales: `Servicios Públicos`, `Obligaciones Bancarias`, `Nómina`, `Compras`, `Gastos`.
- **Concepto**: Denominación de un concepto de pago (Arriendo, Energía, Hipoteca, Salario, etc.) ligado a una Categoría.
- **Concepto_Nómina**: Concepto específico de liquidación de nómina. Valores: `Salario`, `Seguridad Social empleado`, `Parafiscales`, `Auxilio Transporte`, `Prima`, `Vacaciones`, `Bonificación`, `Deducción`, `Anticipo`, `Novedad`.
- **Medio_Pago**: Forma de pago de un movimiento. Valores: `Efectivo`, `Transferencia`, `Consignación`, `Cheque`.
- **Servicio**: Servicio público o fijo registrado en el catálogo de servicios.
- **Obligacion**: Obligación financiera (crédito, cadena, préstamo) registrada en el catálogo de obligaciones.
- **Modalidad_Obligacion**: Tipo de estructura de pago de una Obligación. Valores: `Solo interés mensual`, `Cadena`, `Pago total pactado`, `Bancario cuota fija`.
- **Empleado**: Tercero con tipo `Empleado` vinculado a la nómina.
- **Tipo_Contrato**: Clasificación del vínculo laboral. Valores: `Contrato laboral`, `Prestación de servicios`.
- **Pago**: Registro de un desembolso efectuado contra una obligación, servicio, concepto de nómina, compra o gasto.
- **Registro_Nomina**: Registro de pago de un concepto de nómina a un Empleado para una quincena específica.
- **Usuario**: Persona que opera el sistema (para trazabilidad futura multiusuario).
- **Periodo**: Combinación de año y mes (ej. 2026-01) que identifica una ejecución mensual.
- **Quincena**: Primera (días 1–15) o segunda (días 16–fin de mes) mitad de un mes.

---

## Requisitos

---

### Requisito 1: Catálogo de Terceros

**Historia de usuario:** Como administrador, quiero mantener un catálogo único de terceros (personas y empresas), para reutilizar su información en todos los módulos del sistema sin duplicar datos.

#### Criterios de Aceptación

1. THE Sistema SHALL gestionar un catálogo de Terceros con los atributos: nombre, tipo (Tipo_Tercero), identificación (NIT/cédula), teléfono, correo electrónico, dirección y observaciones.
2. WHEN el usuario registra un nuevo Tercero, THE Sistema SHALL validar que el nombre y el Tipo_Tercero sean obligatorios antes de guardar.
3. WHEN el usuario intenta guardar un Tercero con un nombre idéntico y mismo Tipo_Tercero ya existente, THE Sistema SHALL mostrar una advertencia de posible duplicado y solicitar confirmación antes de guardar.
4. THE Sistema SHALL permitir marcar un Tercero como inactivo sin eliminarlo, preservando su historial de pagos.
5. WHEN el usuario escribe en un campo de búsqueda de Tercero, THE Sistema SHALL presentar sugerencias de autocompletado filtrando por nombre o identificación.
6. THE Sistema SHALL permitir filtrar el listado de Terceros por Tipo_Tercero.

---

### Requisito 2: Catálogo de Conceptos y Categorías

**Historia de usuario:** Como administrador, quiero gestionar categorías y conceptos de pago reutilizables, para clasificar consistentemente todos los movimientos del sistema.

#### Criterios de Aceptación

1. THE Sistema SHALL gestionar un catálogo de Categorías con nombre y descripción.
2. THE Sistema SHALL gestionar un catálogo de Conceptos, donde cada Concepto pertenece a exactamente una Categoría y tiene nombre, descripción y estado activo/inactivo.
3. WHEN el usuario registra cualquier Pago, THE Sistema SHALL requerir la selección de un Concepto del catálogo.
4. WHEN el usuario escribe en un campo de Concepto, THE Sistema SHALL presentar sugerencias de autocompletado filtradas por la Categoría del módulo activo.
5. THE Sistema SHALL incluir los siguientes Conceptos preconfigurados al inicializar la base de datos:
   - Categoría *Servicios Públicos*: Acueducto, Energía, Gas, Teléfono, Internet, Celular, Arriendo, Vigilancia, Otro Servicio.
   - Categoría *Obligaciones Bancarias*: Cuota hipotecaria, Cuota consumo, Interés préstamo personal, Cadena, Abono capital, Otro bancario.
   - Categoría *Nómina*: Salario, Auxilio Transporte, Prima, Vacaciones, Seguridad Social empleado, Parafiscales, Bonificación, Deducción, Anticipo, Novedad.
   - Categoría *Compras*: Materiales, Equipos, Insumos, Otro.
   - Categoría *Gastos*: Alimentación, Transporte, Papelería, Representación, Otro gasto.

---

### Requisito 3: Módulo de Servicios Públicos

**Historia de usuario:** Como tesorero, quiero registrar los servicios públicos y fijos de la empresa con su información completa, para hacer seguimiento puntual de cada pago mensual.

#### Criterios de Aceptación

1. THE Sistema SHALL gestionar un catálogo de Servicios con los atributos: Tercero (empresa prestadora), Concepto, número de referencia o cuenta, tipo de medidor, dirección del inmueble, estrato, periodicidad (mensual, bimestral, anual), valor estimado, día límite de pago, activo/inactivo y observaciones.
2. WHEN el usuario registra un nuevo Servicio, THE Sistema SHALL requerir como mínimo: Tercero y Concepto.
3. THE Sistema SHALL registrar Pagos de Servicios con los atributos: Servicio, año, mes, valor pagado, fecha de pago, Medio_Pago, estado (pendiente / pagado / n/a), usuario que registra y observaciones.
4. WHEN el usuario registra un Pago de Servicio, THE Sistema SHALL validar que el valor pagado sea mayor que cero cuando el estado sea "pagado".
5. THE Sistema SHALL presentar una vista de matriz anual (filas = servicios, columnas = meses) mostrando el estado de pago de cada servicio en cada mes del año seleccionado.
6. WHEN el usuario selecciona una celda de la matriz, THE Sistema SHALL permitir registrar o actualizar el Pago de ese Servicio y Periodo directamente desde la vista de matriz.
7. IF el usuario intenta registrar un segundo Pago para el mismo Servicio, año y mes, THEN THE Sistema SHALL actualizar el registro existente en lugar de crear un duplicado.
8. THE Sistema SHALL mostrar en la vista de lista de servicios el total pagado en el año y mes actual para cada servicio activo.

---

### Requisito 4: Módulo de Obligaciones Financieras

**Historia de usuario:** Como tesorero, quiero registrar las obligaciones financieras de la empresa con su modalidad de pago específica, para controlar el saldo, los intereses y las cuotas pendientes de cada crédito.

#### Criterios de Aceptación

1. THE Sistema SHALL gestionar un catálogo de Obligaciones con los atributos: Tercero (acreedor), Concepto, Modalidad_Obligacion, capital inicial, saldo actual, tasa de interés mensual, plazo pactado (meses), cuotas totales, cuotas pagadas, cuotas pendientes, fecha de inicio, fecha de vencimiento pactada, titular, información de refinanciación (sí/no, fecha, condiciones), activo/inactivo y observaciones.
2. WHEN el usuario selecciona la modalidad `Bancario cuota fija`, THE Sistema SHALL calcular automáticamente y mostrar la cuota mensual estimada usando la fórmula de amortización francesa: `C = K * i / (1 – (1+i)^-n)`, donde K es el capital, i es la tasa mensual y n es el número de cuotas.
3. WHEN el usuario selecciona la modalidad `Solo interés mensual`, THE Sistema SHALL calcular y mostrar el interés mensual como `K * i` y recordar que el capital se devuelve íntegramente al vencimiento.
4. WHEN el usuario selecciona la modalidad `Cadena`, THE Sistema SHALL requerir el valor fijo de la cuota periódica y mostrar el saldo proyectado.
5. WHEN el usuario selecciona la modalidad `Pago total pactado`, THE Sistema SHALL registrar la fecha pactada de pago total y mostrar el total a cancelar (capital + intereses acumulados).
6. THE Sistema SHALL registrar Pagos de Obligaciones con los atributos: Obligación, año, mes, valor pagado, componente capital, componente interés, fecha de pago, Medio_Pago, estado (pendiente / pagado), número de cuota, usuario que registra y observaciones.
7. WHEN el usuario registra un Pago de Obligación con estado "pagado", THE Sistema SHALL actualizar automáticamente el saldo actual de la Obligación restando el componente capital del pago.
8. WHEN el usuario registra un Pago de Obligación, THE Sistema SHALL incrementar el contador de cuotas pagadas y recalcular las cuotas pendientes.
9. THE Sistema SHALL presentar una vista de matriz anual (filas = obligaciones, columnas = meses) mostrando el estado y valor de cada pago.
10. IF el usuario intenta registrar un segundo Pago para la misma Obligación, año y mes, THEN THE Sistema SHALL actualizar el registro existente.
11. THE Sistema SHALL mostrar en el listado de obligaciones el saldo actual, cuotas pendientes y próxima fecha de vencimiento de cada obligación activa.

---

### Requisito 5: Módulo de Nómina

**Historia de usuario:** Como tesorero, quiero registrar los pagos de nómina quincenales de cada empleado con sus conceptos desglosados, para tener un libro de nómina preciso y auditable.

#### Criterios de Aceptación

1. THE Sistema SHALL gestionar un catálogo de Empleados (Terceros con Tipo_Tercero = `Empleado`) con los atributos: nombre completo, número de identificación, cargo, salario base, Tipo_Contrato, fecha de ingreso, fecha de retiro (opcional), activo/inactivo y observaciones.
2. WHEN el usuario registra un nuevo Empleado, THE Sistema SHALL requerir como mínimo: nombre, identificación, salario base y Tipo_Contrato.
3. THE Sistema SHALL registrar Registros_Nomina con los atributos: Empleado, año, mes, Quincena (1 o 2), Concepto_Nómina, valor, Medio_Pago, fecha de pago, usuario que registra y observaciones.
4. THE Sistema SHALL permitir registrar múltiples Registros_Nomina para el mismo Empleado, año, mes y Quincena, uno por cada Concepto_Nómina diferente (ej. Salario + Auxilio Transporte + Deducción = 3 registros para la misma quincena).
5. WHEN el usuario visualiza el resumen de nómina de una quincena, THE Sistema SHALL mostrar el total bruto, total deducciones y total neto por empleado.
6. THE Sistema SHALL presentar una vista de matriz por año (filas = empleados, columnas = quincenas del año) mostrando el total neto pagado en cada quincena.
7. WHEN el usuario registra un Anticipo a un Empleado, THE Sistema SHALL crear un Registro_Nomina con Concepto_Nómina = `Anticipo` y mostrar ese anticipo como deducción en la siguiente quincena hasta que sea absorbido.
8. IF el usuario intenta registrar un Registro_Nomina para un Empleado inactivo, THEN THE Sistema SHALL mostrar un aviso de confirmación antes de guardar.
9. THE Sistema SHALL diferenciar visualmente en los reportes los empleados con Tipo_Contrato `Contrato laboral` de los de `Prestación de servicios`.
10. THE Sistema SHALL registrar los Parafiscales como Registros_Nomina con Concepto_Nómina = `Parafiscales` asociados al mes correspondiente, no a un empleado individual, sino al período.

---

### Requisito 6: Módulo de Compras

**Historia de usuario:** Como administrador, quiero registrar las compras de la empresa, para controlar el flujo de egresos por adquisición de bienes.

#### Criterios de Aceptación

1. THE Sistema SHALL registrar Compras con los atributos: fecha, Tercero (proveedor), Concepto, descripción libre, valor, Medio_Pago, fecha de pago, estado (pendiente / pagado), usuario que registra y observaciones.
2. WHEN el usuario registra una Compra, THE Sistema SHALL requerir como mínimo: fecha, descripción y valor mayor que cero.
3. THE Sistema SHALL presentar el listado de Compras filtrable por Tercero, Concepto, rango de fechas y estado.
4. THE Sistema SHALL mostrar en el listado el total de compras del período seleccionado.

---

### Requisito 7: Módulo de Gastos

**Historia de usuario:** Como administrador, quiero registrar los gastos operativos varios, para tener visibilidad completa del gasto corriente de la empresa.

#### Criterios de Aceptación

1. THE Sistema SHALL registrar Gastos con los atributos: fecha, Tercero (opcional, quien generó el gasto), Concepto, descripción libre, valor, Medio_Pago, fecha de pago, responsable (texto libre), usuario que registra y observaciones.
2. WHEN el usuario registra un Gasto, THE Sistema SHALL requerir como mínimo: fecha, Concepto y valor mayor que cero.
3. THE Sistema SHALL presentar el listado de Gastos filtrable por Concepto, rango de fechas y responsable.
4. THE Sistema SHALL mostrar en el listado el total de gastos del período seleccionado.

---

### Requisito 8: Dashboard y Resumen Financiero

**Historia de usuario:** Como gerente, quiero ver un resumen del estado financiero del mes en curso, para tomar decisiones rápidas sobre pagos pendientes y flujo de caja.

#### Criterios de Aceptación

1. THE Sistema SHALL presentar un dashboard principal que muestre, para el mes y año seleccionados: total pagado en servicios, total pagado en obligaciones, total pagado en nómina, total en compras, total en gastos y gran total de egresos del período.
2. THE Sistema SHALL mostrar en el dashboard el número y lista de servicios con estado "pendiente" para el período seleccionado.
3. THE Sistema SHALL mostrar en el dashboard el número y lista de obligaciones con estado "pendiente" para el período seleccionado.
4. WHEN el usuario cambia el mes o año en el dashboard, THE Sistema SHALL actualizar todos los indicadores sin recargar la página completa.
5. THE Sistema SHALL mostrar en el dashboard un resumen de la nómina pendiente de pago para la quincena actual.

---

### Requisito 9: Trazabilidad y Auditoría

**Historia de usuario:** Como auditor, quiero que todos los registros tengan información de quién y cuándo los creó o modificó, para garantizar trazabilidad del sistema.

#### Criterios de Aceptación

1. THE Sistema SHALL registrar en todos los registros de Pago (servicios, obligaciones, nómina, compras y gastos) los campos: `created_at` (fecha/hora de creación), `updated_at` (fecha/hora de última modificación) y `registrado_por` (nombre o ID del usuario que lo creó).
2. THE Sistema SHALL registrar en todos los catálogos maestros (Terceros, Conceptos, Servicios, Obligaciones, Empleados) los campos `created_at` y `updated_at`.
3. WHERE el sistema opere en modo multiusuario, THE Sistema SHALL registrar el usuario autenticado como `registrado_por` en cada nuevo registro de Pago.
4. WHILE el sistema opere en modo monousuario (fase inicial), THE Sistema SHALL permitir ingresar el nombre del responsable como texto libre en el campo `registrado_por`.

---

### Requisito 10: Migración de Datos desde Excel

**Historia de usuario:** Como administrador, quiero importar los datos históricos del Excel de gastos 2026, para no perder la información del año en curso al pasar al nuevo sistema.

#### Criterios de Aceptación

1. THE Sistema SHALL proveer un script de migración que lea el archivo `GASTOS FIJOS MENSUALES 2026 .xlsx` y lo importe a la base de datos `financiera_gastos`.
2. WHEN el script procesa la hoja `SERVICIOS`, THE Sistema SHALL crear los Terceros, Conceptos y Servicios correspondientes si no existen, y registrar los Pagos de Servicios para los meses con valor distinto de cero.
3. WHEN el script procesa la hoja `BANCOS`, THE Sistema SHALL crear los Terceros y Obligaciones correspondientes si no existen, y registrar los Pagos de Obligaciones para los meses con valor distinto de cero, infiriendo la modalidad con base en el nombre de la obligación.
4. WHEN el script procesa la hoja `NOMINA`, THE Sistema SHALL crear los Empleados (Terceros) si no existen y registrar los Registros_Nomina para las quincenas con valor distinto de cero, clasificando las filas de `parafiscales` como Concepto_Nómina = `Parafiscales`.
5. IF el script encuentra un registro duplicado (misma entidad, mismo período) durante la migración, THEN THE Sistema SHALL omitir la inserción y registrar el conflicto en un log de migración, sin abortar el proceso completo.
6. THE Script SHALL generar un reporte de migración en consola indicando: total registros procesados, total insertados, total omitidos por duplicado y total errores.

---

### Requisito 11: Seguridad y Aislamiento de Base de Datos

**Historia de usuario:** Como administrador de sistemas, quiero garantizar que el sistema financiero use exclusivamente su propia base de datos, para no afectar otras aplicaciones en el mismo servidor PostgreSQL.

#### Criterios de Aceptación

1. THE Sistema SHALL conectarse única y exclusivamente a la base de datos `financiera_gastos` en el servidor `127.0.0.1:5432`.
2. THE Sistema SHALL leer la cadena de conexión desde la variable de entorno `DATABASE_URL`, usando `postgresql+psycopg2://postgres:PreventPg2026Local1@127.0.0.1:5432/financiera_gastos` como valor por defecto si la variable no está definida.
3. IF la base de datos `financiera_gastos` no existe al iniciar las migraciones, THEN THE Sistema SHALL mostrar un mensaje claro indicando que debe crearse manualmente antes de continuar.
4. THE Sistema SHALL definir todos sus modelos con `__bind_key__` o sin él, pero siempre sobre el `SQLALCHEMY_DATABASE_URI` de `financiera_gastos`, nunca haciendo referencia a otras bases de datos del servidor.

---

### Requisito 12: Usabilidad e Interfaz

**Historia de usuario:** Como usuario no técnico, quiero una interfaz simple, responsiva y con ayudas contextuales, para registrar pagos con rapidez y sin errores.

#### Criterios de Aceptación

1. THE Sistema SHALL usar Bootstrap 5 en todas las páginas, con diseño responsivo que funcione correctamente en pantallas de escritorio y tablets.
2. THE Sistema SHALL presentar navegación principal con acceso directo a: Dashboard, Servicios, Obligaciones, Nómina, Compras, Gastos y Catálogos (Terceros, Conceptos).
3. WHEN el usuario completa un formulario con errores de validación, THE Sistema SHALL resaltar los campos con error y mostrar un mensaje descriptivo junto a cada campo, sin borrar los datos ya ingresados.
4. WHEN el usuario registra o actualiza un registro exitosamente, THE Sistema SHALL mostrar un mensaje de confirmación (flash success) visible en la parte superior de la página.
5. THE Sistema SHALL incluir campos de búsqueda/filtro en todos los listados con más de 10 registros potenciales.
6. WHEN el usuario ingresa un valor monetario, THE Sistema SHALL formatear automáticamente el campo con separador de miles al salir del campo (blur), para facilitar la lectura de montos colombianos.
7. THE Sistema SHALL presentar las vistas de matriz de pagos (servicios, obligaciones, nómina) con colores diferenciados: verde para "pagado", amarillo para "pendiente" y gris para "n/a".
