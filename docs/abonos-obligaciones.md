# Abonos de obligaciones

El botón **Abonar** abre un formulario y luego una vista previa. Sólo **Confirmar y registrar abono** escribe el movimiento. La confirmación vence a los 30 minutos, no admite reutilización y verifica que la obligación no haya cambiado. Las escrituras de pagos y abonos toman un bloqueo sobre la obligación.

## Opciones

- **Reducir cuota:** amortización mensual con la tasa registrada, conservando la cantidad de cuotas pendientes.
- **Reducir plazo:** conserva la cuota; calcula los vencimientos necesarios y ajusta la última cuota al saldo exacto.
- **Acuerdo de saldo y cuotas:** saldo anterior menos dinero pagado menos intereses descontados. Las cuotas pactadas deben sumar exactamente el saldo resultante. El descuento queda separado del efectivo y exige una observación. Se registra una cuota por mes, desde el mes siguiente al abono.

Los cálculos automáticos requieren saldo de capital confirmado, tasa conocida (puede ser cero), plazo y calendario válidos, y ausencia de atrasos. Para modalidades sin amortización bancaria, tablas importadas, seguros o cargos pactados, se utiliza el acuerdo con las cifras confirmadas por el acreedor. No se reconstruye una tabla del banco suponiendo condiciones financieras.

El acuerdo reemplaza todas las obligaciones de pago pendientes del calendario anterior, incluidos atrasos. Conserva los importes efectivamente pagados y el historial de las causaciones que modifica. El saldo de un acuerdo representa el total pendiente pactado: al pagar sus cuotas se descuenta también el interés incluido en ellas, sin descontar mora ni anticipos adicionales. El desglose capital/intereses continúa siendo obligatorio si la obligación lo exige.

### Caso de aceptación

Saldo $9.600.000; pago $6.400.000; descuento de intereses $800.000; una cuota de $2.400.000 el 10/10/2026. Tras confirmar, septiembre no tiene deuda vencida y noviembre/diciembre no tienen cuotas. Al pagar octubre el saldo y las cuotas pendientes quedan en cero.

## Historial y reversión

El historial muestra pago, descuento, saldo anterior y nuevo, calendario y observación. Permite revertir el último movimiento vigente cuando no existen cambios posteriores en la obligación, sus pagos, refinanciaciones o tabla. Se exige motivo y se conservan tanto el abono como su reversión. Los abonos antiguos sin snapshot se mantienen visibles, pero no se ofrece reversión automática.

La edición directa y refinanciación de condiciones se bloquean mientras exista un plan de abonos vigente, para evitar dejar un calendario incompatible. Los cambios posteriores se registran como otro acuerdo. Las cuotas anteriores cubiertas por el acuerdo no pueden pagarse ni modificarse por las rutas antiguas.

## Esquema y verificación

La migración `20260917_01`, posterior a `20260824_02`, añade una columna nullable `datos_movimiento` a `abonos_capital_obligaciones`. Contiene calendario, descuento, huellas de estado y snapshot de reversión. No transforma abonos anteriores. La inicialización de esquema también comprueba y agrega la columna, siguiendo el mecanismo existente de la aplicación.

Ejecutar `python -m unittest discover -s tests -v`. Las pruebas usan una base SQLite en memoria y no cargan la configuración ni la conexión real de la aplicación.

Esta implementación no registra automáticamente el pago real de MAMÁ YELI. El usuario debe revisar la fecha efectiva y confirmar su movimiento en la aplicación después del despliegue.
