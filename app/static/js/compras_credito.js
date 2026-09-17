document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('form-compra');
    const condicion = document.getElementById('condicion_pago');
    if (!form || !condicion) return;

    const paga = document.getElementById('paga_inicial');
    const cuotas = document.getElementById('cuotas-credito');
    const abonadoPrevio = Math.round((Number(form.dataset.creditoAbonadoPrevio || '0') || 0) * 100);
    const importe = input => Math.round(window.FinancieraMoney.parse(input.value, 2) * 100);
    const moneda = n => new Intl.NumberFormat('es-CO', {style: 'currency', currency: 'COP'}).format(n / 100);

    function actualizar() {
        const credito = condicion.value === 'credito';
        const inicial = !credito || paga.value === 'si';
        document.getElementById('pregunta-inicial').hidden = !credito;
        paga.disabled = !credito;
        document.getElementById('pago-inicial').hidden = !inicial;
        document.querySelectorAll('#pago-inicial input, #pago-inicial select').forEach(i => i.disabled = !inicial);
        document.getElementById('valor-inicial-grupo').hidden = !credito;

        const valorInicial = document.getElementById('valor_abono_inicial');
        valorInicial.disabled = !credito || !inicial;
        valorInicial.required = credito && inicial;
        document.getElementById('fecha_pago_inicial').required = inicial;
        document.getElementById('plan-credito').hidden = !credito;
        document.getElementById('texto-contado').hidden = credito;
        cuotas.querySelectorAll('input').forEach(i => { i.disabled = !credito; i.required = credito; });

        const saldo = importe(form.elements.valor) - abonadoPrevio - (credito && inicial ? importe(valorInicial) : 0);
        const suma = [...cuotas.querySelectorAll('[name="cuota_valor"]')].reduce((n, i) => n + importe(i), 0);
        document.getElementById('resumen-credito').textContent = 'Saldo a credito: ' + moneda(saldo) + ' - Total programado: ' + moneda(suma) + ' - Diferencia: ' + moneda(saldo - suma);
        return {credito, saldo, suma};
    }

    document.getElementById('agregar-cuota-credito').addEventListener('click', () => {
        const fila = document.createElement('div');
        fila.className = 'row g-2 mb-2 cuota-credito';
        fila.innerHTML = '<div class="col-5"><input aria-label="Fecha de cuota" name="cuota_fecha" type="date" class="form-control"></div><div class="col-5"><input aria-label="Valor de cuota" name="cuota_valor" class="form-control js-money" data-money-scale="2"></div><div class="col-2"><button type="button" class="btn btn-outline-danger quitar-cuota" aria-label="Quitar cuota">x</button></div>';
        cuotas.appendChild(fila);
        window.FinancieraMoney.init(fila);
        actualizar();
    });

    cuotas.addEventListener('click', e => {
        if (e.target.classList.contains('quitar-cuota')) {
            e.target.closest('.cuota-credito').remove();
            actualizar();
        }
    });
    form.addEventListener('input', actualizar);
    form.addEventListener('change', actualizar);
    form.addEventListener('submit', e => {
        const {credito, saldo, suma} = actualizar();
        if (credito && (saldo <= 0 || saldo !== suma || !cuotas.children.length)) {
            e.preventDefault();
            alert('Revise las cuotas: deben sumar exactamente el saldo pendiente de la compra.');
        }
    });
    actualizar();
});
