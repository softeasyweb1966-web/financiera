# Compras a crédito

Al crear una compra se elige contado o crédito. Contado registra el total como un pago realizado y exige su fecha. Crédito pregunta si existe abono inicial; si lo hay, exige valor y fecha real. Las próximas cuotas requieren valor y fecha acordada, y deben sumar exactamente el saldo restante. Las fechas pueden ser irregulares y no se limita el calendario a una cuota mensual.

El calendario se guarda en `cuotas_compras`; cada pago efectivo continúa en `abonos_compras`. La programación no registra dinero pagado por adelantado. Para conciliar cuotas y pagos se aplican los abonos cronológicamente a la cuota pendiente más antigua, permitiendo que una cuota tenga varios pagos y que un abono cubra varias cuotas. El detalle conserva las fechas pactadas y muestra las fechas e importes efectivamente aplicados. Los vencimientos del mes también aparecen en Compras aunque la compra sea de un mes anterior.

La migración `20260917_02` añade `compras.condicion_pago` (nullable para registros anteriores) y crea `cuotas_compras`. Es idempotente y está incorporada en la inicialización de esquema existente. Los registros anteriores mantienen sus saldos e historial; no se les inventan fechas de vencimiento. El calendario se define al crear nuevas compras; mientras exista, la edición general no puede modificar el valor total de la compra y desajustar sus cuotas.

Pruebas: `python -m unittest discover -s tests -v`. Usan SQLite en memoria y no cargan la conexión de producción. Esta implementación no crea compras reales ni despliega la aplicación.
