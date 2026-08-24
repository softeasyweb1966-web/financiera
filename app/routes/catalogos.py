from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import (
    MedioPago, Categoria, Concepto, ConceptoNomina,
    ConceptoCompra, ConceptoGasto, ProductoCompra, ItemGasto,
    GrupoServicio, GrupoServicioConcepto, HistorialEstado
)
from app.conceptos_estado import (
    ESTADOS_CONCEPTO, cargar_historial_conceptos, concepto_activo_en_periodo,
    estado_concepto_en_periodo, periodo_anterior, siguiente_cambio_concepto
)
from datetime import date, datetime

catalogos_bp = Blueprint('catalogos', __name__, url_prefix='/catalogos')


# ==================== MEDIOS DE PAGO ====================

@catalogos_bp.route('/medios-pago')
def medios_pago():
    medios = MedioPago.query.order_by(MedioPago.nombre).all()
    return render_template('catalogos/medios_pago.html', medios=medios)


@catalogos_bp.route('/medios-pago/guardar', methods=['POST'])
def medios_pago_guardar():
    id = request.form.get('id')
    nombre = request.form['nombre'].strip()
    descripcion = request.form.get('descripcion', '').strip()

    if id:
        medio = MedioPago.query.get_or_404(int(id))
        medio.nombre = nombre
        medio.descripcion = descripcion
        flash(f'Medio de pago "{nombre}" actualizado.', 'success')
    else:
        medio = MedioPago(nombre=nombre, descripcion=descripcion)
        db.session.add(medio)
        flash(f'Medio de pago "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('catalogos.medios_pago'))


@catalogos_bp.route('/medios-pago/<int:id>/toggle', methods=['POST'])
def medios_pago_toggle(id):
    medio = MedioPago.query.get_or_404(id)
    medio.activo = not medio.activo
    db.session.commit()
    estado = 'activado' if medio.activo else 'desactivado'
    flash(f'Medio de pago "{medio.nombre}" {estado}.', 'info')
    return redirect(url_for('catalogos.medios_pago'))


# ==================== CONCEPTOS (Servicios y Obligaciones) ====================

@catalogos_bp.route('/conceptos')
def conceptos():
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    conceptos = Concepto.query.order_by(Concepto.categoria_id, Concepto.nombre).all()
    hoy = date.today()
    historiales = cargar_historial_conceptos([c.id for c in conceptos])
    for concepto in conceptos:
        rows = historiales.get(concepto.id, [])
        estado_operativo, cambio_vigente = estado_concepto_en_periodo(concepto, hoy.year, hoy.month, rows)
        concepto.estado_operativo = estado_operativo
        concepto.cambio_vigente = cambio_vigente
        concepto.proximo_cambio = siguiente_cambio_concepto(concepto, hoy.year, hoy.month, rows)
    return render_template('catalogos/conceptos.html',
                           categorias=categorias, conceptos=conceptos,
                           mes_actual=hoy.strftime('%Y-%m'))


@catalogos_bp.route('/conceptos/guardar', methods=['POST'])
def conceptos_guardar():
    id = request.form.get('id')
    nombre = request.form['nombre'].strip()
    categoria_id = request.form['categoria_id']
    descripcion = request.form.get('descripcion', '').strip()

    if id:
        concepto = Concepto.query.get_or_404(int(id))
        concepto.nombre = nombre
        concepto.categoria_id = categoria_id
        concepto.descripcion = descripcion
        flash(f'Concepto "{nombre}" actualizado.', 'success')
    else:
        concepto = Concepto(nombre=nombre, categoria_id=categoria_id, descripcion=descripcion)
        db.session.add(concepto)
        flash(f'Concepto "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('catalogos.conceptos'))


@catalogos_bp.route('/conceptos/<int:id>/cambiar-estado', methods=['POST'])
def conceptos_cambiar_estado(id):
    concepto = Concepto.query.get_or_404(id)
    nuevo_estado = request.form.get('estado', '').strip().lower()
    motivo = request.form.get('motivo', '').strip()
    vigencia_str = request.form.get('vigencia_desde', '').strip()

    if nuevo_estado not in ESTADOS_CONCEPTO:
        flash('Seleccione un estado valido para el concepto.', 'danger')
        return redirect(url_for('catalogos.conceptos'))
    if not motivo:
        flash('Debe indicar el motivo del cambio de estado.', 'danger')
        return redirect(url_for('catalogos.conceptos'))
    if not vigencia_str:
        flash('Debe indicar desde que mes empieza a operar el nuevo estado.', 'danger')
        return redirect(url_for('catalogos.conceptos'))

    try:
        vigencia_desde = datetime.strptime(vigencia_str, '%Y-%m').date().replace(day=1)
    except ValueError:
        flash('El mes de vigencia no es valido.', 'danger')
        return redirect(url_for('catalogos.conceptos'))

    mes_actual = date.today().replace(day=1)
    if vigencia_desde < mes_actual:
        flash('El nuevo estado no puede operar hacia atras.', 'danger')
        return redirect(url_for('catalogos.conceptos'))

    historiales = cargar_historial_conceptos([concepto.id]).get(concepto.id, [])
    anio_prev, mes_prev = periodo_anterior(vigencia_desde.year, vigencia_desde.month)
    estado_anterior, _ = estado_concepto_en_periodo(concepto, anio_prev, mes_prev, historiales)
    estado_objetivo, _ = estado_concepto_en_periodo(concepto, vigencia_desde.year, vigencia_desde.month, historiales)

    if estado_objetivo == nuevo_estado:
        flash('Ese concepto ya queda en ese estado para el mes indicado.', 'warning')
        return redirect(url_for('catalogos.conceptos'))

    db.session.add(HistorialEstado(
        entidad='concepto',
        entidad_id=concepto.id,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado,
        fecha_cambio=datetime.utcnow(),
        vigencia_desde=vigencia_desde,
        motivo=motivo
    ))

    if vigencia_desde <= mes_actual:
        concepto.activo = (nuevo_estado == 'activo')
    db.session.commit()
    flash(
        f'Concepto "{concepto.nombre}" programado como {nuevo_estado} desde {vigencia_desde.strftime("%m/%Y")}.',
        'info'
    )
    return redirect(url_for('catalogos.conceptos'))


# ==================== CONCEPTOS DE NÓMINA ====================

@catalogos_bp.route('/conceptos-nomina')
def conceptos_nomina():
    conceptos = ConceptoNomina.query.order_by(ConceptoNomina.tipo, ConceptoNomina.nombre).all()
    return render_template('catalogos/conceptos_nomina.html', conceptos=conceptos)


@catalogos_bp.route('/conceptos-nomina/guardar', methods=['POST'])
def conceptos_nomina_guardar():
    id = request.form.get('id')
    nombre = request.form['nombre'].strip()
    tipo = request.form['tipo']
    descripcion = request.form.get('descripcion', '').strip()

    if id:
        concepto = ConceptoNomina.query.get_or_404(int(id))
        concepto.nombre = nombre
        concepto.tipo = tipo
        concepto.descripcion = descripcion
        flash(f'Concepto nómina "{nombre}" actualizado.', 'success')
    else:
        concepto = ConceptoNomina(nombre=nombre, tipo=tipo, descripcion=descripcion)
        db.session.add(concepto)
        flash(f'Concepto nómina "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('catalogos.conceptos_nomina'))


@catalogos_bp.route('/conceptos-nomina/<int:id>/toggle', methods=['POST'])
def conceptos_nomina_toggle(id):
    concepto = ConceptoNomina.query.get_or_404(id)
    concepto.activo = not concepto.activo
    db.session.commit()
    return redirect(url_for('catalogos.conceptos_nomina'))


# ==================== CONCEPTOS DE COMPRAS ====================

@catalogos_bp.route('/conceptos-compras')
def conceptos_compras():
    conceptos = ConceptoCompra.query.order_by(ConceptoCompra.nombre).all()
    productos = ProductoCompra.query.join(ConceptoCompra).order_by(
        ConceptoCompra.nombre, ProductoCompra.nombre
    ).all()
    return render_template('catalogos/conceptos_compras.html',
                           conceptos=conceptos, productos=productos)


@catalogos_bp.route('/conceptos-compras/guardar', methods=['POST'])
def conceptos_compras_guardar():
    id = request.form.get('id')
    nombre = request.form['nombre'].strip()
    descripcion = request.form.get('descripcion', '').strip()

    if id:
        concepto = ConceptoCompra.query.get_or_404(int(id))
        concepto.nombre = nombre
        concepto.descripcion = descripcion
        flash(f'Concepto compra "{nombre}" actualizado.', 'success')
    else:
        concepto = ConceptoCompra(nombre=nombre, descripcion=descripcion)
        db.session.add(concepto)
        flash(f'Concepto compra "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('catalogos.conceptos_compras'))


@catalogos_bp.route('/conceptos-compras/<int:id>/toggle', methods=['POST'])
def conceptos_compras_toggle(id):
    concepto = ConceptoCompra.query.get_or_404(id)
    concepto.activo = not concepto.activo
    db.session.commit()
    return redirect(url_for('catalogos.conceptos_compras'))


# ==================== CONCEPTOS DE GASTOS ====================

@catalogos_bp.route('/conceptos-gastos')
def conceptos_gastos():
    flash('Los catalogos de Gastos ya no se administran por separado.', 'info')
    return redirect(url_for('catalogos.conceptos_compras'))


@catalogos_bp.route('/conceptos-gastos/guardar', methods=['POST'])
def conceptos_gastos_guardar():
    id = request.form.get('id')
    nombre = request.form['nombre'].strip()
    descripcion = request.form.get('descripcion', '').strip()

    if id:
        concepto = ConceptoGasto.query.get_or_404(int(id))
        concepto.nombre = nombre
        concepto.descripcion = descripcion
        flash(f'Concepto gasto "{nombre}" actualizado.', 'success')
    else:
        concepto = ConceptoGasto(nombre=nombre, descripcion=descripcion)
        db.session.add(concepto)
        flash(f'Concepto gasto "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('catalogos.conceptos_gastos'))


@catalogos_bp.route('/conceptos-gastos/<int:id>/toggle', methods=['POST'])
def conceptos_gastos_toggle(id):
    concepto = ConceptoGasto.query.get_or_404(id)
    concepto.activo = not concepto.activo
    db.session.commit()
    return redirect(url_for('catalogos.conceptos_gastos'))


# ==================== PRODUCTOS DE COMPRAS ====================

@catalogos_bp.route('/productos-compras')
def productos_compras():
    flash('Los items de compras ahora se administran junto con los conceptos.', 'info')
    return redirect(url_for('catalogos.conceptos_compras'))


@catalogos_bp.route('/productos-compras/guardar', methods=['POST'])
def productos_compras_guardar():
    id = request.form.get('id')
    concepto_compra_id = request.form['concepto_compra_id']
    nombre = request.form['nombre'].strip()
    descripcion = request.form.get('descripcion', '').strip()

    if id:
        producto = ProductoCompra.query.get_or_404(int(id))
        producto.concepto_compra_id = concepto_compra_id
        producto.nombre = nombre
        producto.descripcion = descripcion
        flash(f'Item de compra "{nombre}" actualizado.', 'success')
    else:
        producto = ProductoCompra(
            concepto_compra_id=concepto_compra_id,
            nombre=nombre,
            descripcion=descripcion
        )
        db.session.add(producto)
        flash(f'Item de compra "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('catalogos.conceptos_compras'))


@catalogos_bp.route('/productos-compras/<int:id>/toggle', methods=['POST'])
def productos_compras_toggle(id):
    producto = ProductoCompra.query.get_or_404(id)
    producto.activo = not producto.activo
    db.session.commit()
    return redirect(url_for('catalogos.conceptos_compras'))


# ==================== ITEMS DE GASTOS ====================

@catalogos_bp.route('/items-gastos')
def items_gastos():
    flash('Los catalogos de Gastos ya no se administran por separado.', 'info')
    return redirect(url_for('catalogos.conceptos_compras'))


@catalogos_bp.route('/items-gastos/guardar', methods=['POST'])
def items_gastos_guardar():
    id = request.form.get('id')
    concepto_gasto_id = request.form['concepto_gasto_id']
    nombre = request.form['nombre'].strip()
    descripcion = request.form.get('descripcion', '').strip()

    if id:
        item = ItemGasto.query.get_or_404(int(id))
        item.concepto_gasto_id = concepto_gasto_id
        item.nombre = nombre
        item.descripcion = descripcion
        flash(f'Item de gasto "{nombre}" actualizado.', 'success')
    else:
        item = ItemGasto(
            concepto_gasto_id=concepto_gasto_id,
            nombre=nombre,
            descripcion=descripcion
        )
        db.session.add(item)
        flash(f'Item de gasto "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('catalogos.items_gastos'))


@catalogos_bp.route('/items-gastos/<int:id>/toggle', methods=['POST'])
def items_gastos_toggle(id):
    item = ItemGasto.query.get_or_404(id)
    item.activo = not item.activo
    db.session.commit()
    return redirect(url_for('catalogos.items_gastos'))


# ==================== APIs para autocompletado ====================

@catalogos_bp.route('/api/medios-pago')
def api_medios_pago():
    medios = MedioPago.query.filter_by(activo=True).order_by(MedioPago.nombre).all()
    return jsonify([{'id': m.id, 'nombre': m.nombre} for m in medios])


@catalogos_bp.route('/api/conceptos')
def api_conceptos():
    categoria_id = request.args.get('categoria_id', type=int)
    anio = request.args.get('anio', date.today().year, type=int)
    mes = request.args.get('mes', date.today().month, type=int)
    query = Concepto.query
    if categoria_id:
        query = query.filter_by(categoria_id=categoria_id)
    conceptos = query.order_by(Concepto.nombre).all()
    historiales = cargar_historial_conceptos([c.id for c in conceptos])
    conceptos = [
        c for c in conceptos
        if concepto_activo_en_periodo(c, anio, mes, historiales.get(c.id, []))
    ]
    return jsonify([{'id': c.id, 'nombre': c.nombre} for c in conceptos])


@catalogos_bp.route('/api/conceptos-nomina')
def api_conceptos_nomina():
    conceptos = ConceptoNomina.query.filter_by(activo=True).order_by(ConceptoNomina.nombre).all()
    return jsonify([{'id': c.id, 'nombre': c.nombre, 'tipo': c.tipo} for c in conceptos])


@catalogos_bp.route('/api/conceptos-compras')
def api_conceptos_compras():
    conceptos = ConceptoCompra.query.filter_by(activo=True).order_by(ConceptoCompra.nombre).all()
    return jsonify([{'id': c.id, 'nombre': c.nombre} for c in conceptos])


@catalogos_bp.route('/api/conceptos-gastos')
def api_conceptos_gastos():
    conceptos = ConceptoGasto.query.filter_by(activo=True).order_by(ConceptoGasto.nombre).all()
    return jsonify([{'id': c.id, 'nombre': c.nombre} for c in conceptos])


@catalogos_bp.route('/api/productos-compras')
def api_productos_compras():
    concepto_id = request.args.get('concepto_compra_id', type=int)
    query = ProductoCompra.query.filter_by(activo=True)
    if concepto_id:
        query = query.filter_by(concepto_compra_id=concepto_id)
    productos = query.order_by(ProductoCompra.nombre).all()
    return jsonify([
        {
            'id': p.id,
            'nombre': p.nombre,
            'concepto_compra_id': p.concepto_compra_id
        } for p in productos
    ])


@catalogos_bp.route('/api/items-gastos')
def api_items_gastos():
    concepto_id = request.args.get('concepto_gasto_id', type=int)
    query = ItemGasto.query.filter_by(activo=True)
    if concepto_id:
        query = query.filter_by(concepto_gasto_id=concepto_id)
    items = query.order_by(ItemGasto.nombre).all()
    return jsonify([
        {
            'id': i.id,
            'nombre': i.nombre,
            'concepto_gasto_id': i.concepto_gasto_id
        } for i in items
    ])


# ==================== GRUPOS DE SERVICIOS ====================

@catalogos_bp.route('/grupos-servicios')
def grupos_servicios():
    grupos = GrupoServicio.query.order_by(GrupoServicio.orden, GrupoServicio.nombre).all()
    cat = Categoria.query.filter_by(nombre='Servicios Públicos').first()
    conceptos = Concepto.query.filter_by(categoria_id=cat.id).order_by(Concepto.nombre).all() if cat else []
    hoy = date.today()
    historiales = cargar_historial_conceptos([c.id for c in conceptos])
    conceptos = [
        c for c in conceptos
        if concepto_activo_en_periodo(c, hoy.year, hoy.month, historiales.get(c.id, []))
    ]
    return render_template('catalogos/grupos_servicios.html', grupos=grupos, conceptos=conceptos)


@catalogos_bp.route('/grupos-servicios/guardar', methods=['POST'])
def grupos_servicios_guardar():
    id = request.form.get('id')
    nombre = request.form['nombre'].strip()
    color = request.form.get('color', '#6366f1').strip()
    orden = request.form.get('orden', 0)
    conceptos_ids = request.form.getlist('conceptos_ids')

    if id and id.strip():
        grupo = GrupoServicio.query.get_or_404(int(id))
        grupo.nombre = nombre
        grupo.color = color
        grupo.orden = orden
        # Reemplazar conceptos
        GrupoServicioConcepto.query.filter_by(grupo_id=grupo.id).delete()
        for cid in conceptos_ids:
            db.session.add(GrupoServicioConcepto(grupo_id=grupo.id, concepto_id=int(cid)))
        flash(f'Grupo "{nombre}" actualizado.', 'success')
    else:
        # Verificar si ya existe uno con ese nombre
        existente = GrupoServicio.query.filter_by(nombre=nombre).first()
        if existente:
            flash(f'Ya existe un grupo con el nombre "{nombre}". Use otro nombre o edítelo.', 'danger')
            return redirect(url_for('catalogos.grupos_servicios'))
        grupo = GrupoServicio(nombre=nombre, color=color, orden=orden)
        db.session.add(grupo)
        db.session.flush()
        for cid in conceptos_ids:
            db.session.add(GrupoServicioConcepto(grupo_id=grupo.id, concepto_id=int(cid)))
        flash(f'Grupo "{nombre}" creado.', 'success')

    db.session.commit()
    return redirect(url_for('catalogos.grupos_servicios'))


@catalogos_bp.route('/grupos-servicios/<int:id>/eliminar', methods=['POST'])
def grupos_servicios_eliminar(id):
    grupo = GrupoServicio.query.get_or_404(id)
    GrupoServicioConcepto.query.filter_by(grupo_id=id).delete()
    db.session.delete(grupo)
    db.session.commit()
    flash(f'Grupo "{grupo.nombre}" eliminado.', 'warning')
    return redirect(url_for('catalogos.grupos_servicios'))
