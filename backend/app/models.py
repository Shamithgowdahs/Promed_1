from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AccountUser(Base):
    __tablename__ = "account_users"
    __table_args__ = (
        CheckConstraint("role IN ('customer', 'owner', 'pharmacist', 'operator')", name="ck_account_users_role"),
        Index("ix_account_users_role", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="customer", nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("session_type IN ('customer', 'staff')", name="ck_user_sessions_type"),
        Index("ix_user_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("account_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    session_type: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[AccountUser] = relationship(back_populates="sessions")


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_suppliers_name_nonempty"),
        Index("ix_suppliers_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    contact_details: Mapped[str | None] = mapped_column(String(160))
    address: Mapped[str | None] = mapped_column(String(320))
    reference_code: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)

    batches: Mapped[list["MedicineBatch"]] = relationship(back_populates="supplier")


class ProductCategory(Base):
    __tablename__ = "product_categories"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_product_categories_name_nonempty"),
        CheckConstraint("length(trim(name_key)) > 0", name="ck_product_categories_name_key_nonempty"),
        Index("ix_product_categories_name_key", "name_key", unique=True),
        Index("ix_product_categories_slug", "slug", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(default=True, nullable=False, server_default=text("1"))
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class InventoryLocation(Base):
    __tablename__ = "inventory_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    batches: Mapped[list["MedicineBatch"]] = relationship(back_populates="location")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("min_threshold >= 0", name="ck_products_min_threshold_nonnegative"),
        CheckConstraint("unit_price >= 0", name="ck_products_unit_price_nonnegative"),
        Index("ix_products_name_generic", "name", "generic_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    generic_name: Mapped[str | None] = mapped_column(String(160))
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("product_categories.id", ondelete="RESTRICT"), index=True)
    min_threshold: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    unit_of_measure: Mapped[str] = mapped_column(String(40), default="unit", nullable=False, server_default="unit")
    requires_prescription: Mapped[bool] = mapped_column(default=False, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(160))
    image_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    ingredients_strengths: Mapped[str | None] = mapped_column(Text)
    common_uses: Mapped[str | None] = mapped_column(Text)
    directions: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[str | None] = mapped_column(Text)
    product_information_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    category: Mapped[ProductCategory] = relationship(back_populates="products")
    batches: Mapped[list["MedicineBatch"]] = relationship(back_populates="product")
    stock_transactions: Mapped[list["StockTransaction"]] = relationship(back_populates="product")


class MedicineBatch(Base):
    __tablename__ = "medicine_batches"
    __table_args__ = (
        UniqueConstraint("product_id", "batch_number", "location_id", name="uq_batch_product_number_location"),
        CheckConstraint("quantity >= 0", name="ck_batches_quantity_nonnegative"),
        CheckConstraint("received_quantity >= 0", name="ck_batches_received_quantity_nonnegative"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_batches_cost_nonnegative"),
        CheckConstraint("purchase_price IS NULL OR purchase_price >= 0", name="ck_batches_purchase_price_nonnegative"),
        CheckConstraint(
            "manufacturing_date IS NULL OR manufacturing_date < expiry_date",
            name="ck_batches_manufacturing_before_expiry",
        ),
        CheckConstraint("purchase_date <= expiry_date", name="ck_batches_purchase_before_expiry"),
        CheckConstraint("status IN ('active', 'quarantined', 'damaged')", name="ck_batches_status"),
        Index("ix_batches_expiry_date", "expiry_date"),
        Index("ix_batches_product_expiry", "product_id", "expiry_date"),
        Index("ix_batches_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("inventory_locations.id", ondelete="RESTRICT"), index=True)
    batch_number: Mapped[str] = mapped_column(String(80))
    manufacturing_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date)
    purchase_date: Mapped[date] = mapped_column(Date, default=date.today)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"), index=True)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    received_quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    product: Mapped[Product] = relationship(back_populates="batches")
    location: Mapped[InventoryLocation] = relationship(back_populates="batches")
    supplier: Mapped[Supplier | None] = relationship(back_populates="batches")
    stock_transactions: Mapped[list["StockTransaction"]] = relationship(back_populates="batch")
    status_events: Mapped[list["BatchStatusEvent"]] = relationship(back_populates="batch")


class StockTransaction(Base):
    __tablename__ = "stock_transactions"
    __table_args__ = (
        CheckConstraint("quantity_delta != 0", name="ck_stock_transactions_nonzero_delta"),
        CheckConstraint("kind IN ('receipt', 'adjustment', 'sale')", name="ck_stock_transactions_kind"),
        Index("ix_stock_transactions_created_at", "created_at"),
        Index("ix_stock_transactions_product_created", "product_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("medicine_batches.id", ondelete="RESTRICT"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("inventory_locations.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    quantity_delta: Mapped[int] = mapped_column(Integer)
    previous_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    product: Mapped[Product] = relationship(back_populates="stock_transactions")
    batch: Mapped[MedicineBatch] = relationship(back_populates="stock_transactions")
    location: Mapped[InventoryLocation] = relationship()


class BatchStatusEvent(Base):
    __tablename__ = "batch_status_events"
    __table_args__ = (
        CheckConstraint(
            "previous_status IN ('active', 'quarantined', 'damaged')",
            name="ck_batch_status_events_previous",
        ),
        CheckConstraint(
            "updated_status IN ('active', 'quarantined', 'damaged')",
            name="ck_batch_status_events_updated",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="ck_batch_status_events_reason"),
        Index("ix_batch_status_events_batch_created", "batch_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("medicine_batches.id", ondelete="RESTRICT"), index=True)
    previous_status: Mapped[str] = mapped_column(String(16))
    updated_status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    batch: Mapped[MedicineBatch] = relationship(back_populates="status_events")


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_sales_total_nonnegative"),
        Index("ix_sales_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    tax_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    customer_name: Mapped[str | None] = mapped_column(String(160))
    customer_phone: Mapped[str | None] = mapped_column(String(32), index=True)
    operator_reference: Mapped[str | None] = mapped_column(String(80))
    store_name: Mapped[str | None] = mapped_column(String(160))
    store_phone: Mapped[str | None] = mapped_column(String(32))
    store_address: Mapped[str | None] = mapped_column(String(320))
    currency_code: Mapped[str | None] = mapped_column(String(3))
    discount_authorized_by: Mapped[str | None] = mapped_column(String(80))
    discount_reason: Mapped[str | None] = mapped_column(String(240))
    prescription_reference: Mapped[str | None] = mapped_column(String(160))
    pharmacist_reference: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    payment: Mapped["PaymentRecord | None"] = relationship(back_populates="sale", uselist=False)
    returns: Mapped[list["SaleReturn"]] = relationship(back_populates="sale")


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sale_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_sale_items_price_nonnegative"),
        UniqueConstraint("sale_id", "batch_id", name="uq_sale_batch"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("medicine_batches.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    returned_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sale: Mapped[Sale] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    batch: Mapped[MedicineBatch] = relationship()
    returns: Mapped[list["SaleReturnItem"]] = relationship(back_populates="sale_item")


class SaleReturn(Base):
    __tablename__ = "sale_returns"
    __table_args__ = (
        CheckConstraint("refund_amount >= 0", name="ck_sale_returns_refund_nonnegative"),
        Index("ix_sale_returns_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    return_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"), index=True)
    reason: Mapped[str] = mapped_column(String(240))
    refund_method: Mapped[str] = mapped_column(String(16))
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    operator_reference: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    sale: Mapped[Sale] = relationship(back_populates="returns")
    items: Mapped[list["SaleReturnItem"]] = relationship(back_populates="sale_return", cascade="all, delete-orphan")
    payment: Mapped["PaymentRecord | None"] = relationship(back_populates="sale_return", uselist=False)


class SaleReturnItem(Base):
    __tablename__ = "sale_return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sale_return_items_quantity_positive"),
        CheckConstraint("disposition IN ('restocked', 'quarantined')", name="ck_sale_return_items_disposition"),
        CheckConstraint("refund_amount >= 0", name="ck_sale_return_items_refund_nonnegative"),
        UniqueConstraint("sale_return_id", "sale_item_id", name="uq_sale_return_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_return_id: Mapped[int] = mapped_column(ForeignKey("sale_returns.id", ondelete="CASCADE"), index=True)
    sale_item_id: Mapped[int] = mapped_column(ForeignKey("sale_items.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    disposition: Mapped[str] = mapped_column(String(16))
    restock_verified_by: Mapped[str | None] = mapped_column(String(80))
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    sale_return: Mapped[SaleReturn] = relationship(back_populates="items")
    sale_item: Mapped[SaleItem] = relationship(back_populates="returns")


class PaymentRecord(Base):
    __tablename__ = "payment_records"
    __table_args__ = (
        CheckConstraint("kind IN ('payment', 'refund')", name="ck_payment_records_kind"),
        CheckConstraint("method IN ('cash', 'upi', 'card')", name="ck_payment_records_method"),
        CheckConstraint(
            "(kind = 'payment' AND amount > 0) OR (kind = 'refund' AND amount >= 0)",
            name="ck_payment_records_amount",
        ),
        CheckConstraint(
            "(kind = 'payment' AND sale_id IS NOT NULL AND return_id IS NULL) OR "
            "(kind = 'refund' AND sale_id IS NULL AND return_id IS NOT NULL)",
            name="ck_payment_records_owner",
        ),
        UniqueConstraint("sale_id", name="uq_payment_records_sale"),
        UniqueConstraint("return_id", name="uq_payment_records_return"),
        UniqueConstraint("idempotency_key", name="uq_payment_records_idempotency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"))
    return_id: Mapped[int | None] = mapped_column(ForeignKey("sale_returns.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    cash_received: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    change_given: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    reference: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    sale: Mapped[Sale | None] = relationship(back_populates="payment")
    sale_return: Mapped[SaleReturn | None] = relationship(back_populates="payment")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'fulfilled', 'cancelled')", name="ck_orders_status"),
        Index("ix_orders_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    workflow_status: Mapped[str] = mapped_column(String(24), default="RECEIVED", nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(160))
    customer_phone: Mapped[str | None] = mapped_column(String(32), index=True)
    delivery_address: Mapped[str | None] = mapped_column(String(320))
    fulfillment_method: Mapped[str] = mapped_column(String(16), default="pickup", nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    operator_reference: Mapped[str | None] = mapped_column(String(80))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("account_users.id", ondelete="SET NULL"), index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
    customer: Mapped[AccountUser | None] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    status_events: Mapped[list["OrderStatusEvent"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    prescription_verifications: Mapped[list["PrescriptionVerification"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class OrderStatusEvent(Base):
    __tablename__ = "order_status_events"
    __table_args__ = (
        CheckConstraint(
            "updated_status IN ('RECEIVED', 'PHARMACIST_REVIEW', 'ACCEPTED', 'PREPARING', "
            "'READY_FOR_PICKUP', 'OUT_FOR_DELIVERY', 'COMPLETED', 'REJECTED', 'CANCELLED')",
            name="ck_order_status_events_status",
        ),
        Index("ix_order_status_events_order_created", "order_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(24))
    updated_status: Mapped[str] = mapped_column(String(24))
    operator_reference: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    order: Mapped[Order] = relationship(back_populates="status_events")


class PrescriptionVerification(Base):
    __tablename__ = "prescription_verifications"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'verified', 'rejected')", name="ck_prescription_verifications_status"),
        Index("ix_prescription_verifications_order_created", "order_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    prescription_reference: Mapped[str | None] = mapped_column(String(160))
    pharmacist_reference: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())

    order: Mapped[Order] = relationship(back_populates="prescription_verifications")


class ApplicationSetting(Base):
    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())


class StoreConfiguration(Base):
    __tablename__ = "store_configuration"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_store_configuration_singleton"),
        CheckConstraint("tax_rate_percent >= 0 AND tax_rate_percent <= 100", name="ck_store_configuration_tax_rate"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    store_name: Mapped[str] = mapped_column(String(160))
    store_phone: Mapped[str] = mapped_column(String(32))
    store_address: Mapped[str | None] = mapped_column(String(320))
    tax_rate_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    currency_code: Mapped[str] = mapped_column(String(3))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp())
