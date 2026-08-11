"""
Modelos del Sistema Financiero de Gastos Fijos
17 tablas: catálogos + maestros + operativas
BD: financiera_gastos (independiente)
"""
from app import db
from datetime import datetime, date


# ============================================================
# CATÁLOGOS (tablas de referencia con CRUD)
# ============================================================

class TipoTercero(db.Model):
    """Clasificación de terceros: Empleado, Proveedor, Entidad Financiera, etc."""
    __tablename__ = 'tipo_tercero'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    descripcion = db.Column(db.Text)

    terceros = db.relationship('Tercero', backref='tipo_tercero_rel', lazy='dynamic')

    def __repr__(self):
        return f'<TipoTercero {self.nombre}>'


class Categoria(db.Model):
    """Agrupador contable: Servicios Públicos, Obligaciones, Nómina, Compras, Gastos"""
    __tablename__ = 'categorias'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    descripcion = db.Column(db.Text)

    conceptos = db.relationship('Concepto', backref='categoria_rel', lazy='dynamic')

    def __repr__(self):
        return f'<Categoria {self.nombre}>'


class Concepto(db.Model):
    """Concepto de pago vinculado a una categoría (Arriendo, Energía, Hipoteca, etc.)"""
    __tablename__ = 'conceptos'

    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('categoria_id', 'nombre', name='uq_concepto_categoria'),
    )

    def __repr__(self):
        return f'<Concepto {self.nombre}>'


class MedioPago(db.Model):
    """Formas de pago: Efectivo, Transferencia, Nequi, etc."""
    __tablename__ = 'medios_pago'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<MedioPago {self.nombre}>'


class ConceptoNomina(db.Model):
    """Conceptos específicos de nómina: Salario, Seg.Social, Anticipo, etc."""
    __tablename__ = 'conceptos_nomina'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    tipo = db.Column(db.String(20), nullable=False)  # devengado, deduccion
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ConceptoNomina {self.nombre} ({self.tipo})>'


class ConceptoCompra(db.Model):
    """Conceptos de compras: Materiales, Equipos, Insumos, etc."""
    __tablename__ = 'conceptos_compras'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ConceptoCompra {self.nombre}>'


class ConceptoGasto(db.Model):
    """Conceptos de gastos: Alimentación, Transporte, Papelería, etc."""
    __tablename__ = 'conceptos_gastos'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ConceptoGasto {self.nombre}>'


class ProductoCompra(db.Model):
    """Productos o items normalizados para compras"""
    __tablename__ = 'productos_compras'

    id = db.Column(db.Integer, primary_key=True)
    concepto_compra_id = db.Column(db.Integer, db.ForeignKey('conceptos_compras.id'), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    concepto_compra = db.relationship('ConceptoCompra', backref='productos')

    __table_args__ = (
        db.UniqueConstraint('concepto_compra_id', 'nombre', name='uq_producto_compra_concepto_nombre'),
    )

    def __repr__(self):
        return f'<ProductoCompra {self.nombre}>'


class ItemGasto(db.Model):
    """Items normalizados para gastos"""
    __tablename__ = 'items_gastos'

    id = db.Column(db.Integer, primary_key=True)
    concepto_gasto_id = db.Column(db.Integer, db.ForeignKey('conceptos_gastos.id'), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    concepto_gasto = db.relationship('ConceptoGasto', backref='items')

    __table_args__ = (
        db.UniqueConstraint('concepto_gasto_id', 'nombre', name='uq_item_gasto_concepto_nombre'),
    )

    def __repr__(self):
        return f'<ItemGasto {self.nombre}>'


class GrupoServicio(db.Model):
    """Agrupación personalizada de conceptos de servicio para el resumen visual"""
    __tablename__ = 'grupos_servicios'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    color = db.Column(db.String(7), default='#6366f1')  # Color hex para la UI
    orden = db.Column(db.Integer, default=0)  # Para ordenar en pantalla
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    conceptos = db.relationship('GrupoServicioConcepto', backref='grupo', lazy='dynamic')

    def __repr__(self):
        return f'<GrupoServicio {self.nombre}>'


class GrupoServicioConcepto(db.Model):
    """Relación entre grupo de servicio y conceptos que agrupa"""
    __tablename__ = 'grupos_servicios_conceptos'

    id = db.Column(db.Integer, primary_key=True)
    grupo_id = db.Column(db.Integer, db.ForeignKey('grupos_servicios.id'), nullable=False)
    concepto_id = db.Column(db.Integer, db.ForeignKey('conceptos.id'), nullable=False)

    concepto = db.relationship('Concepto')

    __table_args__ = (
        db.UniqueConstraint('grupo_id', 'concepto_id', name='uq_grupo_concepto'),
    )


# ============================================================
# MAESTROS (terceros, servicios, obligaciones, empleados)
# ============================================================

class HistorialEstado(db.Model):
    """Registro histórico de cambios de estado en cualquier entidad"""
    __tablename__ = 'historial_estados'

    id = db.Column(db.Integer, primary_key=True)
    entidad = db.Column(db.String(50), nullable=False)  # 'tercero', 'servicio', 'obligacion', 'empleado', etc.
    entidad_id = db.Column(db.Integer, nullable=False)
    estado_anterior = db.Column(db.String(20))
    estado_nuevo = db.Column(db.String(20), nullable=False)
    fecha_cambio = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    vigencia_desde = db.Column(db.Date)
    motivo = db.Column(db.Text)
    registrado_por = db.Column(db.String(100))

    def __repr__(self):
        return f'<HistorialEstado {self.entidad}#{self.entidad_id}: {self.estado_anterior}→{self.estado_nuevo}>'


class Tercero(db.Model):
    """Persona natural o jurídica: empleado, proveedor, banco, empresa servicios"""
    __tablename__ = 'terceros'

    id = db.Column(db.Integer, primary_key=True)
    tipo_tercero_id = db.Column(db.Integer, db.ForeignKey('tipo_tercero.id'), nullable=False)
    nombre = db.Column(db.String(150), nullable=False)
    identificacion = db.Column(db.String(20))  # NIT o cédula
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(100))
    direccion = db.Column(db.String(200))
    activo = db.Column(db.Boolean, default=True)
    estado = db.Column(db.String(20), default='activo')  # activo, inactivo, retirado, anulado
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Tercero {self.nombre}>'


class Servicio(db.Model):
    """Servicio público o fijo recurrente"""
    __tablename__ = 'servicios'

    id = db.Column(db.Integer, primary_key=True)
    tercero_id = db.Column(db.Integer, db.ForeignKey('terceros.id'), nullable=False)
    concepto_id = db.Column(db.Integer, db.ForeignKey('conceptos.id'), nullable=False)
    referencia = db.Column(db.String(50))  # No. cuenta o referencia de pago
    periodicidad = db.Column(db.String(20), default='mensual')  # mensual, bimestral, anual
    dia_limite_pago = db.Column(db.Integer)
    dia_causacion = db.Column(db.Integer)  # Día del mes en que llega la factura
    valor_estimado = db.Column(db.Numeric(14, 2))
    provision_mensual = db.Column(db.Numeric(14, 2))  # Para servicios anuales: provisión mensual
    fecha_pago_anual = db.Column(db.Date)  # Fecha exacta de pago para servicios anuales
    mes_inicio_bimestral = db.Column(db.Integer, default=1)  # 1=meses impares, 2=meses pares
    direccion_inmueble = db.Column(db.String(200))
    estrato = db.Column(db.Integer)
    activo = db.Column(db.Boolean, default=True)
    estado = db.Column(db.String(20), default='activo')  # activo, inactivo, retirado, anulado
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tercero = db.relationship('Tercero', backref='servicios')
    concepto = db.relationship('Concepto', backref='servicios')
    pagos = db.relationship('PagoServicio', backref='servicio', lazy='dynamic')

    def __repr__(self):
        return f'<Servicio {self.tercero.nombre if self.tercero else "?"} - {self.concepto.nombre if self.concepto else "?"}>'


class Obligacion(db.Model):
    """Obligación financiera: crédito bancario, préstamo personal, cadena"""
    __tablename__ = 'obligaciones'

    id = db.Column(db.Integer, primary_key=True)
    tercero_id = db.Column(db.Integer, db.ForeignKey('terceros.id'), nullable=False)
    concepto_id = db.Column(db.Integer, db.ForeignKey('conceptos.id'), nullable=False)
    modalidad = db.Column(db.String(30), nullable=False)
    # Modalidades: solo_interes, cadena, pago_total_pactado, bancario_cuota_fija
    capital_inicial = db.Column(db.Numeric(14, 2))
    saldo_actual = db.Column(db.Numeric(14, 2))
    tasa_interes_mensual = db.Column(db.Numeric(6, 4))  # Ej: 1.5% = 1.5000
    plazo_meses = db.Column(db.Integer)
    plazo_dias = db.Column(db.Integer)  # Para préstamos a días (corto plazo)
    cuotas_totales = db.Column(db.Integer)
    cuotas_pagadas = db.Column(db.Integer, default=0)
    valor_cuota_fija = db.Column(db.Numeric(14, 2))  # Para cadenas o cuota pactada
    fecha_inicio = db.Column(db.Date)
    fecha_vencimiento = db.Column(db.Date)
    fecha_recibe = db.Column(db.Date)
    titular = db.Column(db.String(150))
    referencia = db.Column(db.String(50))
    frecuencia_pago = db.Column(db.String(20), default='mensual')  # mensual, quincenal
    dia_limite_pago = db.Column(db.Integer)
    activo = db.Column(db.Boolean, default=True)
    estado = db.Column(db.String(20), default='activo')  # activo, inactivo, retirado, anulado
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tercero = db.relationship('Tercero', backref='obligaciones')
    concepto = db.relationship('Concepto', backref='obligaciones')
    pagos = db.relationship('PagoObligacion', backref='obligacion', lazy='dynamic')
    refinanciaciones = db.relationship('Refinanciacion', backref='obligacion', lazy='dynamic',
                                       order_by='Refinanciacion.fecha_refinanciacion.desc()')

    @property
    def cuotas_pendientes(self):
        if self.cuotas_totales and self.cuotas_pagadas is not None:
            return self.cuotas_totales - self.cuotas_pagadas
        return None

    @property
    def interes_mensual_calculado(self):
        """Calcula interés mensual: capital * tasa / 100"""
        if self.saldo_actual and self.tasa_interes_mensual:
            return float(self.saldo_actual) * float(self.tasa_interes_mensual) / 100
        return None

    @property
    def cuota_francesa_calculada(self):
        """Calcula cuota fija con amortización francesa: C = K * i / (1 - (1+i)^-n)"""
        if self.saldo_actual and self.tasa_interes_mensual and self.cuotas_pendientes:
            k = float(self.saldo_actual)
            i = float(self.tasa_interes_mensual) / 100
            n = self.cuotas_pendientes
            if i > 0 and n > 0:
                return k * i / (1 - (1 + i) ** (-n))
        return None

    def __repr__(self):
        return f'<Obligacion {self.tercero.nombre if self.tercero else "?"} - {self.modalidad}>'


class Refinanciacion(db.Model):
    """Historial de refinanciaciones de una obligación"""
    __tablename__ = 'refinanciaciones'

    id = db.Column(db.Integer, primary_key=True)
    obligacion_id = db.Column(db.Integer, db.ForeignKey('obligaciones.id'), nullable=False)
    fecha_refinanciacion = db.Column(db.Date, nullable=False)
    valor_refinanciado = db.Column(db.Numeric(14, 2), nullable=False)
    nueva_tasa_mensual = db.Column(db.Numeric(6, 4))
    nuevo_plazo_meses = db.Column(db.Integer)
    nuevo_valor_cuota = db.Column(db.Numeric(14, 2))
    nueva_fecha_vencimiento = db.Column(db.Date)
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Refinanciacion {self.fecha_refinanciacion} - ${self.valor_refinanciado}>'


class AbonoCapitalObligacion(db.Model):
    """Historial de abonos extraordinarios a capital"""
    __tablename__ = 'abonos_capital_obligaciones'

    id = db.Column(db.Integer, primary_key=True)
    obligacion_id = db.Column(db.Integer, db.ForeignKey('obligaciones.id'), nullable=False)
    fecha_abono = db.Column(db.Date, nullable=False)
    valor_abono = db.Column(db.Numeric(14, 2), nullable=False)
    saldo_anterior = db.Column(db.Numeric(14, 2))
    saldo_nuevo = db.Column(db.Numeric(14, 2))
    opcion_recalculo = db.Column(db.String(20), nullable=False)  # reducir_cuota, reducir_plazo
    cuotas_pendientes_antes = db.Column(db.Integer)
    cuotas_pendientes_despues = db.Column(db.Integer)
    cuota_anterior = db.Column(db.Numeric(14, 2))
    cuota_nueva = db.Column(db.Numeric(14, 2))
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    obligacion = db.relationship('Obligacion', backref=db.backref(
        'abonos_capital', lazy='dynamic', order_by='AbonoCapitalObligacion.fecha_abono.desc()'
    ))

    def __repr__(self):
        return f'<AbonoCapitalObligacion {self.fecha_abono} - ${self.valor_abono}>'


class Empleado(db.Model):
    """Empleado vinculado a un tercero"""
    __tablename__ = 'empleados'

    id = db.Column(db.Integer, primary_key=True)
    tercero_id = db.Column(db.Integer, db.ForeignKey('terceros.id'), nullable=False)
    cargo = db.Column(db.String(100))
    salario_base = db.Column(db.Numeric(14, 2))
    tipo_contrato = db.Column(db.String(30))  # laboral, prestacion_servicios
    forma_pago = db.Column(db.String(20), default='quincenal')  # diaria, semanal, quincenal, mensual
    whatsapp = db.Column(db.String(20))
    autoriza_whatsapp = db.Column(db.Boolean, default=False)
    fecha_ingreso = db.Column(db.Date)
    fecha_retiro = db.Column(db.Date)
    activo = db.Column(db.Boolean, default=True)
    estado = db.Column(db.String(20), default='activo')  # activo, inactivo, retirado, anulado
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tercero = db.relationship('Tercero', backref='empleado_info')
    registros_nomina = db.relationship('RegistroNomina', backref='empleado', lazy='dynamic')

    @property
    def nombre(self):
        return self.tercero.nombre if self.tercero else ''

    def __repr__(self):
        return f'<Empleado {self.nombre} - {self.cargo}>'


# ============================================================
# TABLAS OPERATIVAS (pagos y movimientos)
# ============================================================

class PagoServicio(db.Model):
    """Registro de pago mensual de un servicio"""
    __tablename__ = 'pagos_servicios'

    id = db.Column(db.Integer, primary_key=True)
    servicio_id = db.Column(db.Integer, db.ForeignKey('servicios.id'), nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)
    valor_causado = db.Column(db.Numeric(14, 2))    # Valor que se espera pagar (causación)
    fecha_causacion = db.Column(db.Date)             # Fecha en que se causó (llegó la factura)
    valor_pagado = db.Column(db.Numeric(14, 2))     # Valor efectivamente pagado
    fecha_pago = db.Column(db.Date)
    medio_pago_id = db.Column(db.Integer, db.ForeignKey('medios_pago.id'))
    # Estados: sin_causar, causado, pagado, vencido, parcial, n/a
    estado = db.Column(db.String(20), default='sin_causar')
    registrado_por = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    medio_pago = db.relationship('MedioPago')

    __table_args__ = (
        db.UniqueConstraint('servicio_id', 'anio', 'mes', name='uq_pago_servicio_mes'),
    )


class PagoObligacion(db.Model):
    """Registro de pago mensual de una obligación financiera"""
    __tablename__ = 'pagos_obligaciones'

    id = db.Column(db.Integer, primary_key=True)
    obligacion_id = db.Column(db.Integer, db.ForeignKey('obligaciones.id'), nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)
    valor_causado = db.Column(db.Numeric(14, 2))    # Valor esperado de la cuota (causación)
    fecha_causacion = db.Column(db.Date)             # Fecha en que se causó
    valor_pagado = db.Column(db.Numeric(14, 2))     # Valor efectivamente pagado
    componente_capital = db.Column(db.Numeric(14, 2))
    componente_interes = db.Column(db.Numeric(14, 2))
    numero_cuota = db.Column(db.Integer)
    fecha_pago = db.Column(db.Date)
    medio_pago_id = db.Column(db.Integer, db.ForeignKey('medios_pago.id'))
    # Estados: sin_causar, causado, pagado, vencido, parcial
    estado = db.Column(db.String(20), default='sin_causar')
    registrado_por = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    medio_pago = db.relationship('MedioPago')

    __table_args__ = (
        db.UniqueConstraint('obligacion_id', 'anio', 'mes', name='uq_pago_obligacion_mes'),
    )


class RegistroNomina(db.Model):
    """Registro de pago de un concepto de nómina a un empleado por quincena"""
    __tablename__ = 'registros_nomina'

    id = db.Column(db.Integer, primary_key=True)
    empleado_id = db.Column(db.Integer, db.ForeignKey('empleados.id'))  # NULL para parafiscales globales
    concepto_nomina_id = db.Column(db.Integer, db.ForeignKey('conceptos_nomina.id'), nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    mes = db.Column(db.Integer, nullable=False)
    quincena = db.Column(db.Integer, nullable=False)  # 1 o 2
    valor = db.Column(db.Numeric(14, 2), nullable=False)
    fecha_pago = db.Column(db.Date)
    medio_pago_id = db.Column(db.Integer, db.ForeignKey('medios_pago.id'))
    registrado_por = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    concepto_nomina = db.relationship('ConceptoNomina')
    medio_pago = db.relationship('MedioPago')

    __table_args__ = (
        db.UniqueConstraint('empleado_id', 'concepto_nomina_id', 'anio', 'mes', 'quincena',
                            name='uq_registro_nomina_concepto_quinc'),
    )


class Compra(db.Model):
    """Registro de compra puntual"""
    __tablename__ = 'compras'

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False)
    tercero_id = db.Column(db.Integer, db.ForeignKey('terceros.id'))  # Proveedor (opcional)
    concepto_compra_id = db.Column(db.Integer, db.ForeignKey('conceptos_compras.id'), nullable=False)
    producto_compra_id = db.Column(db.Integer, db.ForeignKey('productos_compras.id'))
    descripcion = db.Column(db.String(300), nullable=False)
    valor = db.Column(db.Numeric(14, 2), nullable=False)
    medio_pago_id = db.Column(db.Integer, db.ForeignKey('medios_pago.id'))
    fecha_pago = db.Column(db.Date)
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, pagado
    registrado_por = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tercero = db.relationship('Tercero', backref='compras')
    concepto_compra = db.relationship('ConceptoCompra', backref='compras')
    producto_compra = db.relationship('ProductoCompra', backref='compras')
    medio_pago = db.relationship('MedioPago')

    def __repr__(self):
        return f'<Compra {self.descripcion}>'


class PagoTC(db.Model):
    """Registro de pagos realizados con tarjeta de crédito"""
    __tablename__ = 'pagos_tc'

    id = db.Column(db.Integer, primary_key=True)
    pago_tipo = db.Column(db.String(30), nullable=False)  # 'servicio', 'obligacion', 'compra', 'gasto'
    pago_id = db.Column(db.Integer, nullable=False)  # ID del registro de pago
    titular_tc = db.Column(db.String(100), nullable=False)
    numero_cuotas = db.Column(db.Integer, default=1)
    fecha_pago_tc = db.Column(db.Date)
    valor_cuota = db.Column(db.Numeric(14, 2))
    cuotas_pagadas = db.Column(db.Integer, default=0)
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<PagoTC {self.pago_tipo}#{self.pago_id} - {self.titular_tc}>'


class Gasto(db.Model):
    """Registro de gasto puntual"""
    __tablename__ = 'gastos'

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False)
    tercero_id = db.Column(db.Integer, db.ForeignKey('terceros.id'))  # Opcional
    concepto_gasto_id = db.Column(db.Integer, db.ForeignKey('conceptos_gastos.id'), nullable=False)
    item_gasto_id = db.Column(db.Integer, db.ForeignKey('items_gastos.id'))
    descripcion = db.Column(db.String(300))
    valor = db.Column(db.Numeric(14, 2), nullable=False)
    medio_pago_id = db.Column(db.Integer, db.ForeignKey('medios_pago.id'))
    fecha_pago = db.Column(db.Date)
    responsable = db.Column(db.String(100))
    registrado_por = db.Column(db.String(100))
    observaciones = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tercero = db.relationship('Tercero', backref='gastos')
    concepto_gasto = db.relationship('ConceptoGasto', backref='gastos')
    item_gasto = db.relationship('ItemGasto', backref='gastos')
    medio_pago = db.relationship('MedioPago')

    def __repr__(self):
        return f'<Gasto {self.descripcion}>'
