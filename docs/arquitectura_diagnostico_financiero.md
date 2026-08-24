# Arquitectura Base Para Diagnostico Financiero

## Objetivo

Este aplicativo no solo registra pagos. Su objetivo es permitir diagnosticar el estado financiero de una empresa, consolidando:

- compromisos
- gastos
- nomina
- servicios
- obligaciones
- ingresos

La meta final es poder responder con trazabilidad:

- que estaba programado o causado
- que se pago realmente
- que saldo quedo pendiente
- como evoluciono cada item en el tiempo
- como impacta el flujo de caja y el punto de equilibrio
- como bajar desde el tablero general hasta el detalle mas pequeno


## Regla de modelado

Todo modulo financiero del sistema debe poder representar estas 4 capas:

1. `Base maestra`
   Ejemplo: empleado, obligacion, servicio, proveedor, item de gasto.

2. `Causacion o programacion`
   Lo que la empresa deberia pagar o reconocer para un periodo.

3. `Movimiento real`
   Pago, abono, ajuste, anulacion, refinanciacion u otro evento real.

4. `Saldo y estado visible`
   Resultado de comparar lo causado con lo pagado o abonado.

Sin esas 4 capas no hay analitica confiable.


## Estados minimos esperados

Cada modulo debe poder mapear sus datos a este lenguaje comun:

- `sin_causar`
- `causado`
- `parcial`
- `pagado`
- `vencido`
- `no_aplica`
- `anulado`

No todos los modulos tienen que persistir todos los estados, pero la vista de negocio si debe poder derivarlos.


## Trazabilidad obligatoria

Todo movimiento monetario debe conservar, como minimo:

- periodo afectado
- valor
- fecha
- medio de pago
- descripcion u observacion
- usuario o proceso que lo registro
- fecha de creacion
- fecha de actualizacion

Si un valor cambia, el sistema debe conservar el historial o la bitacora del ajuste.


## Drill-down esperado

El aplicativo debe permitir navegar:

1. Resumen empresa
2. Categoria
3. Modulo
4. Maestro
5. Periodo
6. Movimiento puntual

Ejemplos:

- de flujo mensual a nomina de agosto 2026 Q1
- de nomina Q1 a empleado
- de empleado a quincena
- de quincena a abono o pago puntual


## Estado actual por modulo

### Obligaciones

Fortalezas:

- ya separa `valor_causado` y `valor_pagado`
- maneja `parcial`
- conserva historial de pagos y ajustes
- tiene buen nivel de detalle para analitica

Brechas:

- conviene mantener la disciplina de registrar todo ajuste como movimiento y no solo como sobrescritura del pago actual


### Servicios

Fortalezas:

- ya usa `PagoServicio` con `valor_causado`, `valor_pagado` y `estado`
- reconoce parciales y vencidos
- soporta historiales de valores y activacion por periodo

Brechas:

- la trazabilidad de multiples abonos sobre un mismo periodo todavia puede crecer hacia un esquema mas granular, similar al de abonos de nomina


### Nomina

Fortalezas actuales:

- separa causacion por quincena
- soporta aplicabilidad por fecha de ingreso y forma de pago
- ya cuenta con `SaldoAnteriorNomina`
- desde agosto 24, 2026 se agrego `AbonoNomina` para registrar pagos parciales o totales con trazabilidad

Brechas:

- el modelo viejo `RegistroNomina.fecha_pago` sigue existiendo por compatibilidad
- a futuro, la lectura debe depender cada vez menos del campo agregado en el registro y mas de la bitacora de abonos


### Compras

Fortalezas:

- ya tiene maestro y detalle por registro

Brechas importantes:

- hoy se maneja casi como binario `pendiente/pagado`
- no tiene capa clara de causacion separada del movimiento real
- no tiene bitacora de abonos parciales
- limita el analisis de pasivos y flujo real


### Gastos

Fortalezas:

- ya registra egresos puntuales con detalle

Brechas importantes:

- funciona mas como registro de salida que como compromiso financiero trazable
- si un gasto requiere quedar causado y pagarse despues, el modelo actual se queda corto


### Ingresos

Pendiente de implementar.

Debe nacer con la misma estructura:

- fuente o maestro
- causacion o expectativa
- recaudo real
- saldo
- historial


## Decisiones de arquitectura

### 1. No mezclar causacion con movimiento

Un campo como `fecha_pago` dentro del registro principal puede servir como compatibilidad o resumen, pero no debe ser la unica fuente de verdad cuando el negocio soporta abonos, ajustes o pagos multiples.


### 2. Los saldos deben derivarse de movimientos

Siempre que sea posible:

- `saldo = causado - abonado`

Si existe una tabla de saldos manuales, debe entenderse como mecanismo transitorio o de compatibilidad, no como sustituto de la bitacora real.


### 3. Todo modulo nuevo debe nacer con bitacora de movimientos

Si un modulo puede tener:

- pago parcial
- ajuste
- anulacion
- refinanciacion
- reliquidacion

entonces debe tener una tabla de movimientos o historial desde el inicio.


### 4. La analitica debe leer un lenguaje comun

Para construir tablero empresarial, flujo, punto de equilibrio y diagnostico, el backend deberia exponer una capa comun por item y periodo con:

- `valor_programado`
- `valor_causado`
- `valor_pagado`
- `saldo`
- `estado`
- `fecha_ultimo_movimiento`
- `detalle_url`


## Prioridad sugerida de evolucion

1. Consolidar nomina con la bitacora de abonos ya creada.
2. Revisar servicios para soportar multiples movimientos por periodo si negocio lo necesita.
3. Llevar compras a modelo `causacion + movimiento + saldo`.
4. Llevar gastos a modelo `compromiso + ejecucion`, al menos para los recurrentes o financiados.
5. Diseñar ingresos con la misma base comun.
6. Construir capa de diagnostico empresarial y punto de equilibrio sobre ese lenguaje unificado.


## Criterio para aceptar futuras mejoras

Una mejora financiera se considera completa solo si:

- resuelve la operacion
- conserva trazabilidad
- permite auditar el saldo
- sirve para el tablero general
- permite bajar al detalle minimo sin perder consistencia
