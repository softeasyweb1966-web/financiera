# Diseño Técnico — Sistema Financiero de Gastos Fijos

## Resumen

Aplicación web Flask + PostgreSQL para gestión de gastos fijos mensuales. Usa modelo relacional con tablas maestras (catálogos) y tablas operativas (movimientos/pagos). Diseñada para ser extensible sin romper lo existente.

**Stack:** Python 3.11, Flask, SQLAlchemy, Flask-Migrate, Bootstrap 5, pandas/openpyxl (migración).  
**BD:** `financiera_gastos` en PostgreSQL 16 local (127.0.0.1:5432), completamente independiente.

---

## Arquitectura de la Aplicación

```
c:\python\financiera\
├── venv\                        # Ambiente virtual
├── app\
│   ├── __init__.py              # Factory Flask + extensiones
│   ├── models.py                # Modelos SQLAlchemy (todos los módulos)
│   ├── routes\                  # Blueprints por módulo
│   │   ├── __init__.py
│   │   ├── main.py             # Dashboard
│   │   ├── terceros.py         # CRUD terceros
│   │   ├── conceptos.py        # CRUD conceptos/categorías
│   │   ├── servicios.py        # CRUD servicios + pagos
│   │   ├── obligaciones.py     # CRUD obligaciones + pagos
│   │   ├── nomina.py           # CRUD empleados + registros nómina
│   │   ├── compras.py          # CRUD compras
│   │   └── gastos.py           # CRUD gastos
│   ├── templates\
│   │   ├── base.html           # Layout con navbar responsive
│   │   ├── index.html          # Dashboard
│   │   ├── terceros\           # Templates CRUD terceros
│   │   ├── conceptos\          # Templates CRUD conceptos
│   │   ├── servicios\          # Lista, form, matriz pagos
│   │   ├── obligaciones\       # Lista, form, matriz pagos
│   │   ├── nomina\             # Lista, form, matriz pagos
│   │   ├── compras\            # Lista, form
│   │   └── gastos\             # Lista, form
│   └── static\
│       ├── css\style.css       # Estilos custom mínimos
│       └── js\app.js           # Autocompletado, formato moneda
├── config.py                    # Configuración DB
├── run.py                       # Punto de entrada
├── importar_excel.py            # Script migración datos Excel
├── seeds.py                     # Script datos semilla (catálogos)
├── migrations\                  # Alembic/Flask-Migrate
└── requirements.txt
```

---

## Modelo de Base de Datos

### Diagrama Entidad-Relación (simplificado)

```
┌─────────────────┐       ┌─────────────────┐
│  tipo_tercero   │       │   categorias    │
│ (catálogo)      │       │ (catálogo)      │
└────────┬────────┘       └────────┬────────┘
         │ 1:N                     │ 1:N
┌────────▼────────┐       ┌────────▼────────┐
│    terceros     │       │    conceptos    │
│ (maestro)       │       │ (maestro)       │
└──┬──┬──┬──┬─────┘       └────────┬────────┘
   │  │  │  │                      │
   │  │  │  └──────────────────┐   │
   │  │  │                     │   │
   │  │  │  ┌─────────────┐   │   │
   │  │  └─►│  servicios   │◄──┘───┘
   │  │     └──────┬───────┘
   │  │            │ 1:N
   │  │     ┌──────▼───────┐
   │  │     │pagos_servicios│
   │  │     └──────────────┘
   │  │
   │  │     ┌──────────────┐
   │  └────►│ obligaciones │◄── concepto
   │        └──────┬───────┘
   │               │ 1:N
   │        ┌──────▼───────────┐
   │        │pagos_obligaciones│
   │        └──────────────────┘
   │
   │        ┌──────────────┐       ┌───────────────────┐
   └───────►│  empleados   │       │ conceptos_nomina  │
            └──────┬───────┘       └────────┬──────────┘
                   │ 1:N                    │
            ┌──────▼────────────────────────▼──┐
            │        registros_nomina          │
            └──────────────────────────────────┘

┌──────────────┐     ┌──────────────┐
│   compras    │     │    gastos    │
│ (puntual)    │     │ (puntual)    │
└──────────────┘     └──────────────┘
```

---

### Definición de Tablas

#### 1. tipo_tercero (catálogo)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| nombre | varchar(50) NOT NULL UNIQUE | Empleado, Proveedor, Entidad Financiera, Empresa Servicios, Prestamista Personal |
| descripcion | text | |

#### 2. terceros (maestro)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| tipo_tercero_id | int FK → tipo_tercero | NOT NULL |
| nombre | varchar(150) NOT NULL | |
| identificacion | varchar(20) | NIT o cédula |
| telefono | varchar(20) | |
| email | varchar(100) | |
| direccion | varchar(200) | |
| activo | boolean DEFAULT true | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

**Índice:** UNIQUE(nombre, tipo_tercero_id) como advertencia soft (no hard constraint, solo warning en UI).

#### 3. categorias (catálogo)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| nombre | varchar(50) NOT NULL UNIQUE | Servicios Públicos, Obligaciones Bancarias, Nómina, Compras, Gastos |
| descripcion | text | |

#### 4. conceptos (maestro)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| categoria_id | int FK → categorias | NOT NULL |
| nombre | varchar(100) NOT NULL | |
| descripcion | text | |
| activo | boolean DEFAULT true | |
| created_at | timestamp | |

**Índice:** UNIQUE(categoria_id, nombre)

#### 5. servicios
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| tercero_id | int FK → terceros | NOT NULL (empresa prestadora) |
| concepto_id | int FK → conceptos | NOT NULL |
| referencia | varchar(50) | No. cuenta o referencia de pago |
| periodicidad | varchar(20) DEFAULT 'mensual' | mensual, bimestral, anual |
| dia_limite_pago | int | Día del mes |
| valor_estimado | numeric(14,2) | |
| direccion_inmueble | varchar(200) | Para servicios asociados a un predio |
| estrato | int | |
| activo | boolean DEFAULT true | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

#### 6. pagos_servicios
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| servicio_id | int FK → servicios | NOT NULL |
| anio | int NOT NULL | |
| mes | int NOT NULL | 1-12 |
| valor_pagado | numeric(14,2) | |
| fecha_pago | date | |
| medio_pago_id | int FK → medios_pago | |
| estado | varchar(20) DEFAULT 'pendiente' | pendiente, pagado, n/a |
| registrado_por | varchar(100) | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

**Constraint:** UNIQUE(servicio_id, anio, mes)

#### 7. medios_pago (catálogo con CRUD)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| nombre | varchar(50) NOT NULL UNIQUE | Efectivo, Transferencia, Consignación, Cheque, Nequi, Daviplata... |
| descripcion | text | |
| activo | boolean DEFAULT true | |
| created_at | timestamp | |

#### 8. obligaciones
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| tercero_id | int FK → terceros | NOT NULL (acreedor) |
| concepto_id | int FK → conceptos | NOT NULL |
| modalidad | varchar(30) NOT NULL | solo_interes, cadena, pago_total_pactado, bancario_cuota_fija |
| capital_inicial | numeric(14,2) | |
| saldo_actual | numeric(14,2) | |
| tasa_interes_mensual | numeric(6,4) | Ej: 1.5% = 1.5000 |
| plazo_meses | int | |
| cuotas_totales | int | |
| cuotas_pagadas | int DEFAULT 0 | |
| valor_cuota_fija | numeric(14,2) | Para cadenas o cuota pactada |
| fecha_inicio | date | |
| fecha_vencimiento | date | |
| titular | varchar(150) | Persona/empresa responsable |
| dia_limite_pago | int | Día del mes |
| activo | boolean DEFAULT true | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

#### 9. refinanciaciones (historial por obligación)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| obligacion_id | int FK → obligaciones | NOT NULL |
| fecha_refinanciacion | date NOT NULL | Cuándo se refinanció |
| valor_refinanciado | numeric(14,2) NOT NULL | Monto que se refinancia |
| nueva_tasa_mensual | numeric(6,4) | Nueva tasa pactada |
| nuevo_plazo_meses | int | Nuevo plazo |
| nuevo_valor_cuota | numeric(14,2) | Nueva cuota mensual |
| nueva_fecha_vencimiento | date | |
| observaciones | text | Condiciones especiales |
| created_at | timestamp | |

#### 10. pagos_obligaciones
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| obligacion_id | int FK → obligaciones | NOT NULL |
| anio | int NOT NULL | |
| mes | int NOT NULL | |
| valor_pagado | numeric(14,2) | Total desembolsado |
| componente_capital | numeric(14,2) | Parte que abona a capital |
| componente_interes | numeric(14,2) | Parte de interés |
| numero_cuota | int | |
| fecha_pago | date | |
| medio_pago_id | int FK → medios_pago | |
| estado | varchar(20) DEFAULT 'pendiente' | |
| registrado_por | varchar(100) | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

**Constraint:** UNIQUE(obligacion_id, anio, mes)

#### 11. empleados
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| tercero_id | int FK → terceros | NOT NULL (Tipo_Tercero = Empleado) |
| cargo | varchar(100) | |
| salario_base | numeric(14,2) | |
| tipo_contrato | varchar(30) | laboral, prestacion_servicios |
| fecha_ingreso | date | |
| fecha_retiro | date | NULL si activo |
| activo | boolean DEFAULT true | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

#### 12. conceptos_nomina (catálogo con CRUD)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| nombre | varchar(50) NOT NULL UNIQUE | Salario, Seg.Social, Parafiscales, Aux.Transporte, etc. |
| tipo | varchar(20) NOT NULL | devengado, deduccion |
| descripcion | text | |
| activo | boolean DEFAULT true | |
| created_at | timestamp | |

#### 13. registros_nomina
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| empleado_id | int FK → empleados | NULL para parafiscales globales |
| concepto_nomina_id | int FK → conceptos_nomina | NOT NULL |
| anio | int NOT NULL | |
| mes | int NOT NULL | |
| quincena | int NOT NULL | 1 o 2 |
| valor | numeric(14,2) NOT NULL | |
| fecha_pago | date | |
| medio_pago_id | int FK → medios_pago | |
| registrado_por | varchar(100) | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

**Constraint:** UNIQUE(empleado_id, concepto_nomina_id, anio, mes, quincena) — permite un registro por concepto por quincena por empleado.

#### 14. conceptos_compras (catálogo con CRUD)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| nombre | varchar(100) NOT NULL UNIQUE | Materiales, Equipos, Insumos, Papelería, etc. |
| descripcion | text | |
| activo | boolean DEFAULT true | |
| created_at | timestamp | |

#### 15. compras
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| fecha | date NOT NULL | |
| tercero_id | int FK → terceros | Proveedor (opcional) |
| concepto_compra_id | int FK → conceptos_compras | NOT NULL |
| descripcion | varchar(300) NOT NULL | |
| valor | numeric(14,2) NOT NULL | |
| medio_pago_id | int FK → medios_pago | |
| fecha_pago | date | |
| estado | varchar(20) DEFAULT 'pendiente' | pendiente, pagado |
| registrado_por | varchar(100) | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

#### 16. conceptos_gastos (catálogo con CRUD)
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| nombre | varchar(100) NOT NULL UNIQUE | Alimentación, Transporte, Representación, etc. |
| descripcion | text | |
| activo | boolean DEFAULT true | |
| created_at | timestamp | |

#### 17. gastos
| Campo | Tipo | Notas |
|-------|------|-------|
| id | serial PK | |
| fecha | date NOT NULL | |
| tercero_id | int FK → terceros | Opcional |
| concepto_gasto_id | int FK → conceptos_gastos | NOT NULL |
| descripcion | varchar(300) | |
| valor | numeric(14,2) NOT NULL | |
| medio_pago_id | int FK → medios_pago | |
| fecha_pago | date | |
| responsable | varchar(100) | Texto libre |
| registrado_por | varchar(100) | |
| observaciones | text | |
| created_at | timestamp | |
| updated_at | timestamp | |

---

## Flujos Principales (UI)

### Registrar pago de servicio (desde la matriz)
1. Usuario entra a Servicios → Ver pagos 2026
2. Ve la matriz (filas=servicios, columnas=meses)
3. Hace clic en una celda pendiente (amarilla)
4. Se abre modal con:
   - Servicio (prellenado, solo lectura)
   - Mes/Año (prellenado)
   - Valor pagado (prellenado con valor estimado)
   - Fecha de pago (hoy por defecto)
   - Medio de pago (desplegable)
   - Estado (pagado por defecto)
   - Observaciones
5. Guarda → celda se pone verde → mensaje de confirmación

### Registrar obligación nueva
1. Usuario entra a Obligaciones → Nueva
2. Selecciona Tercero (autocompletado, puede crear nuevo inline)
3. Selecciona Concepto (filtrado por categoría "Obligaciones Bancarias")
4. Selecciona Modalidad → según la selección se muestran/ocultan campos:
   - *Bancario cuota fija*: capital, tasa, plazo → sistema calcula cuota estimada
   - *Solo interés mensual*: capital, tasa, fecha vencimiento → sistema muestra interés mensual
   - *Cadena*: capital, valor cuota fija, día de pago
   - *Pago total pactado*: capital, tasa, fecha pactada → sistema muestra total proyectado
5. Completa titular, día límite, observaciones
6. Guarda → aparece en la lista con su saldo

### Registrar nómina quincenal
1. Usuario entra a Nómina → Registrar quincena
2. Selecciona Año, Mes, Quincena (1 o 2)
3. Sistema muestra todos los empleados activos
4. Por cada empleado puede agregar uno o más conceptos (salario, auxilio, etc.)
5. Los valores se prellenan con el salario base / 2 para Salario
6. Guarda todos los registros de la quincena de una vez

---

## Decisiones de Diseño

1. **Extensibilidad:** Campos como `estrato`, `tipo_medidor` están presentes en el modelo pero no son obligatorios. El formulario los muestra como opcionales y se pueden ignorar inicialmente.

2. **Parafiscales:** Se registran como `registros_nomina` con `empleado_id = NULL` (son globales del período). Así quedan en la misma tabla y se pueden consultar junto con la nómina, pero no se asignan a un empleado individual.

3. **Sin autenticación inicial:** El campo `registrado_por` es texto libre. Cuando se implemente login, se llenará automáticamente con el usuario autenticado.

4. **Modalidades de obligación como varchar:** No como tabla separada porque son pocas y fijas. Si se necesitan más, se agrega un valor al enum de la aplicación sin migración de BD.

5. **Medios de pago con CRUD:** Tabla propia con administración completa. Cada pago referencia un medio_pago_id (FK). Así se pueden agregar, renombrar o desactivar medios sin tocar código.

6. **Conceptos de nómina con CRUD:** Tabla `conceptos_nomina` administrable desde la UI, no hardcodeada. Permite agregar nuevos conceptos (ej: bonificación especial) sin modificar el sistema.

7. **Refinanciación como tabla propia:** Cada refinanciación registra fecha, valor refinanciado, nueva tasa, nuevo plazo, nueva cuota y observaciones. Una obligación puede tener múltiples refinanciaciones (historial).

8. **Conceptos de Compras y Gastos con CRUD propio:** Tablas `conceptos_compras` y `conceptos_gastos` con administración independiente. Los formularios de compras y gastos usan autocompletado dinámico desde estos catálogos.

9. **Una BD, una app:** Todo vive en `financiera_gastos`. No se crean schemas separados ni se referencia ninguna otra base.

---

## Datos Semilla (seeds.py)

Al ejecutar `seeds.py` se insertan:

**tipo_tercero:** Empleado, Proveedor, Entidad Financiera, Empresa Servicios, Prestamista Personal

**categorias:** Servicios Públicos, Obligaciones Bancarias, Nómina, Compras, Gastos

**conceptos (por categoría):**
- Servicios: Acueducto, Energía, Gas, Teléfono, Internet, Celular, Arriendo, Vigilancia, Plan exequial, Software/Plataforma, Otro Servicio
- Obligaciones: Cuota hipotecaria, Cuota consumo, Interés préstamo personal, Cadena, Abono capital, Otro bancario

**medios_pago:** Efectivo, Transferencia, Consignación, Cheque, Nequi, Daviplata

**conceptos_nomina:** Salario (devengado), Auxilio Transporte (devengado), Bonificación (devengado), Prima (devengado), Vacaciones (devengado), Seguridad Social (deduccion), Parafiscales (deduccion), Deducción (deduccion), Anticipo (deduccion), Novedad (devengado)

**conceptos_compras:** Materiales, Equipos, Insumos, Papelería, Mobiliario, Tecnología, Otro

**conceptos_gastos:** Alimentación, Transporte, Papelería, Representación, Mantenimiento, Aseo, Otro gasto

---

## Migraciones

Se usa Flask-Migrate (Alembic). Cada cambio futuro:
```
flask db migrate -m "descripcion del cambio"
flask db upgrade
```

Para agregar campos nuevos (ej: tasa_aplicada en obligaciones, novedades en nómina) solo se agrega la columna al modelo y se ejecuta la migración. No rompe nada existente.
