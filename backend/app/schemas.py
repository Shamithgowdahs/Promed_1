from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

ShortName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
BatchNumber = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"),
]
LocationCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=16, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]
ExpiryCategory = Literal["expired", "within_30_days", "within_60_days", "within_90_days", "safe"]
BatchStatus = Literal["active", "quarantined", "damaged"]
PaymentMethod = Literal["cash", "upi", "card"]
OrderWorkflowStatus = Literal[
    "RECEIVED",
    "PHARMACIST_REVIEW",
    "ACCEPTED",
    "PREPARING",
    "READY_FOR_PICKUP",
    "OUT_FOR_DELIVERY",
    "COMPLETED",
    "REJECTED",
    "CANCELLED",
]
AccountEmail = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=6,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
AccountPhone = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=7, max_length=32, pattern=r"^\+?[0-9][0-9 ()-]*$"),
]
AccountPassword = Annotated[str, StringConstraints(min_length=12, max_length=128)]


class CustomerRegister(BaseModel):
    email: AccountEmail
    display_name: ShortName
    phone: AccountPhone
    password: AccountPassword

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class AccountLogin(BaseModel):
    email: AccountEmail
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class AccountRead(BaseModel):
    id: int
    email: str
    display_name: str
    phone: str | None
    role: str


class CustomerProfileUpdate(BaseModel):
    display_name: ShortName | None = None
    phone: AccountPhone | None = None

    @model_validator(mode="after")
    def require_update(self):
        if self.display_name is None and self.phone is None:
            raise ValueError("Provide a profile field to update")
        return self


class StaffAccountCreate(BaseModel):
    email: AccountEmail
    display_name: ShortName
    phone: AccountPhone | None = None
    password: AccountPassword
    role: Literal["pharmacist", "operator"]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class CategoryCreate(BaseModel):
    name: CategoryName
    description: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=1000)] = None
    image_url: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    active: bool = True

    @field_validator("image_url")
    @classmethod
    def local_category_image_only(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("/assets/")
            or ".." in value
            or "\\" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError("Category images must use a local /assets/ path")
        return value


class CategoryUpdate(BaseModel):
    name: CategoryName | None = None
    description: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=1000)] = None
    image_url: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    active: bool | None = None

    @field_validator("image_url")
    @classmethod
    def local_category_image_only(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("/assets/")
            or ".." in value
            or "\\" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError("Category images must use a local /assets/ path")
        return value

    @model_validator(mode="after")
    def require_update(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one category field to update")
        if any(
            getattr(self, field) is None
            for field in ("name", "active")
            if field in self.model_fields_set
        ):
            raise ValueError("Category name and active status cannot be null")
        return self


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str | None
    image_url: str | None
    active: bool


class InitialStockCreate(BaseModel):
    batch_number: BatchNumber
    manufacturing_date: date | None = None
    expiry_date: date
    purchase_date: date = Field(default_factory=date.today)
    supplier_id: int | None = Field(default=None, gt=0)
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    quantity: int = Field(gt=0, le=1_000_000)
    location_code: LocationCode
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)

    @model_validator(mode="after")
    def validate_batch_dates(self):
        if self.manufacturing_date and self.manufacturing_date >= self.expiry_date:
            raise ValueError("manufacturing_date must be earlier than expiry_date")
        if self.manufacturing_date and self.manufacturing_date > self.purchase_date:
            raise ValueError("manufacturing_date cannot be after purchase_date")
        if self.purchase_date > self.expiry_date:
            raise ValueError("purchase_date cannot be after expiry_date")
        if self.purchase_date > date.today():
            raise ValueError("purchase_date cannot be in the future")
        return self


class ProductCreate(BaseModel):
    name: ShortName
    generic_name: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=160)] = None
    barcode: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")] = None
    category_id: int | None = Field(default=None, gt=0)
    category_name: CategoryName | None = None
    min_threshold: int = Field(default=0, ge=0, le=1_000_000)
    unit_price: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    unit_of_measure: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] = "unit"
    requires_prescription: bool = False
    active: bool = True
    manufacturer: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=160)] = None
    image_url: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    description: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    ingredients_strengths: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    common_uses: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    directions: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    warnings: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    product_information_verified: bool = False
    initial_stock: InitialStockCreate | None = None

    @field_validator("image_url")
    @classmethod
    def local_product_image_only(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("/assets/")
            or ".." in value
            or "\\" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError("Product images must use a local /assets/ path")
        return value

    @model_validator(mode="after")
    def require_category(self):
        if (self.category_id is None) == (self.category_name is None):
            raise ValueError("Provide exactly one of category_id or category_name")
        return self


class CustomerProductRead(BaseModel):
    id: int
    name: str
    category_id: int
    category_name: str
    manufacturer: str | None
    image_url: str | None
    unit_price: Decimal
    available_quantity: int
    availability_status: Literal["available", "unavailable"]
    requires_prescription: bool
    description: str | None
    ingredients_strengths: str | None
    common_uses: str | None
    directions: str | None
    warnings: str | None
    product_information_verified: bool


class ProductInventoryUpdate(BaseModel):
    min_threshold: int | None = Field(default=None, ge=0, le=1_000_000)
    requires_prescription: bool | None = None
    manufacturer: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=160)] = None
    image_url: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    description: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    ingredients_strengths: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    common_uses: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    directions: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    warnings: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    product_information_verified: bool | None = None

    @field_validator("image_url")
    @classmethod
    def local_product_image_only(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("/assets/")
            or ".." in value
            or "\\" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError("Product images must use a local /assets/ path")
        return value

    @model_validator(mode="after")
    def require_update(self):
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("Provide at least one product field to update")
        return self


class ProductUpdate(BaseModel):
    name: ShortName | None = None
    generic_name: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=160)] = None
    barcode: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")] = None
    category_id: int | None = Field(default=None, gt=0)
    min_threshold: int | None = Field(default=None, ge=0, le=1_000_000)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    unit_of_measure: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] = None
    requires_prescription: bool | None = None
    active: bool | None = None
    manufacturer: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=160)] = None
    image_url: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    description: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    ingredients_strengths: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    common_uses: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    directions: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    warnings: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None
    product_information_verified: bool | None = None

    @field_validator("image_url")
    @classmethod
    def local_product_image_only(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("/assets/")
            or ".." in value
            or "\\" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError("Product images must use a local /assets/ path")
        return value

    @model_validator(mode="after")
    def require_update(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one product field to update")
        required_fields = {
            "name",
            "category_id",
            "min_threshold",
            "unit_price",
            "unit_of_measure",
            "requires_prescription",
            "active",
            "product_information_verified",
        }
        if any(
            getattr(self, field) is None
            for field in required_fields.intersection(self.model_fields_set)
        ):
            raise ValueError("Non-optional product fields cannot be null")
        return self


class BatchReceive(InitialStockCreate):
    product_id: int = Field(gt=0)


class SupplierCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    contact_details: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=160)] = None
    address: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=320)] = None
    reference_code: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=80)] = None


class SupplierUpdate(SupplierCreate):
    pass


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    contact_details: str | None
    address: str | None
    reference_code: str | None


class BatchStatusUpdate(BaseModel):
    status: BatchStatus
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]


class StockAdjustment(BaseModel):
    batch_id: int = Field(gt=0)
    quantity_delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]

    @field_validator("quantity_delta")
    @classmethod
    def nonzero_delta(cls, value: int) -> int:
        if value == 0:
            raise ValueError("quantity_delta must not be zero")
        return value


class InventoryLocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class InventoryLocationCreate(BaseModel):
    code: LocationCode
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.upper()


class InventoryLocationUpdate(InventoryLocationCreate):
    pass


class LocationQuantityRead(BaseModel):
    location_code: str
    quantity: int


class BatchRead(BaseModel):
    id: int
    batch_number: str
    manufacturing_date: date | None
    expiry_date: date
    expiry_category: ExpiryCategory
    days_remaining: int
    purchase_date: date
    purchase_price: Decimal | None
    supplier_id: int | None
    supplier_name: str | None
    supplier_reference: str | None
    supplier_contact: str | None
    supplier_address: str | None
    quantity: int
    available_quantity: int
    received_quantity: int
    status: BatchStatus
    location_code: str
    unit_cost: Decimal | None


class InventoryBatchRead(BatchRead):
    product_id: int
    product_name: str
    barcode: str | None
    category_id: int
    category_name: str


class ProductRead(BaseModel):
    id: int
    name: str
    generic_name: str | None
    barcode: str | None
    category_id: int
    category_name: str
    min_threshold: int
    unit_price: Decimal
    requires_prescription: bool
    stock_quantity: int
    available_stock_quantity: int
    expired_stock_quantity: int
    locations: list[str]
    location_quantities: list[LocationQuantityRead]
    batches: list[BatchRead]


class ProductManagementRead(ProductRead):
    unit_of_measure: str
    active: bool
    manufacturer: str | None
    image_url: str | None
    description: str | None
    ingredients_strengths: str | None
    common_uses: str | None
    directions: str | None
    warnings: str | None
    product_information_verified: bool


class StockTransactionRead(BaseModel):
    id: int
    product_id: int
    product_name: str
    batch_id: int
    batch_number: str
    location_code: str
    kind: str
    quantity_delta: int
    previous_quantity: int
    updated_quantity: int
    reason: str | None
    created_at: datetime


class BatchStatusEventRead(BaseModel):
    id: int
    previous_status: BatchStatus
    updated_status: BatchStatus
    reason: str
    created_at: datetime


class BatchHistoryRead(BaseModel):
    batch: InventoryBatchRead
    transactions: list[StockTransactionRead]
    status_events: list[BatchStatusEventRead]


class LowStockProductRead(BaseModel):
    product_id: int
    product_name: str
    barcode: str | None
    stock_quantity: int
    min_threshold: int
    suggested_reorder_quantity: int
    location_quantities: list[LocationQuantityRead]


class ExpiringBatchRead(BaseModel):
    id: int
    product_id: int
    product_name: str
    barcode: str | None
    batch_number: str
    expiry_date: date
    days_remaining: int
    quantity: int
    location_code: str
    expiry_category: ExpiryCategory
    status: BatchStatus
    available_quantity: int


class ExpiryCategorySummary(BaseModel):
    category: ExpiryCategory
    batch_count: int
    quantity: int


class DashboardRead(BaseModel):
    product_count: int
    stock_units: int
    available_stock_units: int
    expired_stock_units: int
    today_sales_amount: Decimal
    low_stock_count: int
    expiring_batch_count: int
    expiry_categories: list[ExpiryCategorySummary]
    locations: list[dict[str, int | str]]
    recent_transactions: list[StockTransactionRead]


class SaleItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1_000_000)


class SaleCreate(BaseModel):
    items: list[SaleItemCreate] = Field(min_length=1, max_length=100)


class SaleItemRead(BaseModel):
    product_id: int
    product_name: str
    batch_id: int
    batch_number: str
    quantity: int
    unit_price: Decimal


class SaleRead(BaseModel):
    id: int
    invoice_number: str
    total_amount: Decimal
    created_at: datetime
    items: list[SaleItemRead]


class SalesConfigUpdate(BaseModel):
    store_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    store_phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    store_address: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=320)] = None
    tax_rate_percent: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    currency_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")]

    @field_validator("currency_code")
    @classmethod
    def normalize_currency_code(cls, value: str) -> str:
        return value.upper()


class SalesConfigRead(BaseModel):
    configured: bool
    store_name: str | None
    store_phone: str | None
    store_address: str | None
    tax_rate_percent: Decimal | None
    currency_code: str | None


class SaleCheckoutItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1_000_000)


class SaleCheckout(BaseModel):
    items: list[SaleCheckoutItem] = Field(min_length=1, max_length=100)
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    discount_authorized_by: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] = None
    discount_reason: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)] = None
    prescription_reference: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] = None
    pharmacist_reference: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] = None
    customer_name: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] = None
    customer_phone: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] = None
    operator_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    payment_method: PaymentMethod
    payment_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_reference: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] = None
    idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=80)]

    @model_validator(mode="after")
    def validate_checkout(self):
        if self.discount_amount > 0 and (not self.discount_authorized_by or not self.discount_reason):
            raise ValueError("A discount requires an authorizer reference and reason")
        if self.payment_method in ("upi", "card") and not self.payment_reference:
            raise ValueError("A payment reference is required for UPI and card payments")
        if len({item.product_id for item in self.items}) != len(self.items):
            raise ValueError("Each product may appear only once in the checkout")
        return self


class PaymentRecordRead(BaseModel):
    id: int
    kind: str
    method: PaymentMethod
    amount: Decimal
    cash_received: Decimal | None
    change_given: Decimal | None
    reference: str | None
    created_at: datetime


class InvoiceLineRead(BaseModel):
    sale_item_id: int
    product_name: str
    batch_number: str
    quantity: int
    returned_quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal


class InvoiceRead(BaseModel):
    sale_id: int
    invoice_number: str
    created_at: datetime
    store_name: str | None
    store_phone: str | None
    store_address: str | None
    currency_code: str | None
    customer_name: str | None
    customer_phone: str | None
    operator_reference: str | None
    subtotal_amount: Decimal
    discount_amount: Decimal
    discount_authorized_by: str | None
    discount_reason: str | None
    prescription_reference: str | None
    pharmacist_reference: str | None
    tax_rate_percent: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    payment: PaymentRecordRead | None
    items: list[InvoiceLineRead]


class SaleHistoryRead(BaseModel):
    sale_id: int
    invoice_number: str
    created_at: datetime
    customer_name: str | None
    customer_phone: str | None
    currency_code: str | None
    subtotal_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    payment_method: PaymentMethod | None
    item_count: int


class SaleReturnItemCreate(BaseModel):
    sale_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1_000_000)
    restock: bool = False
    restock_verified_by: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] = None

    @model_validator(mode="after")
    def require_restock_verification(self):
        if self.restock and not self.restock_verified_by:
            raise ValueError("Verified inspection reference is required before restocking a return")
        return self


class SaleReturnCreate(BaseModel):
    items: list[SaleReturnItemCreate] = Field(min_length=1, max_length=100)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    refund_method: PaymentMethod
    refund_reference: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] = None
    operator_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=80)]

    @model_validator(mode="after")
    def validate_return(self):
        if self.refund_method in ("upi", "card") and not self.refund_reference:
            raise ValueError("A refund reference is required for UPI and card refunds")
        if len({item.sale_item_id for item in self.items}) != len(self.items):
            raise ValueError("Each sold batch allocation may appear only once")
        return self


class SaleReturnItemRead(BaseModel):
    sale_item_id: int
    product_name: str
    batch_number: str
    quantity: int
    disposition: str
    restock_verified_by: str | None
    refund_amount: Decimal


class SaleReturnRead(BaseModel):
    id: int
    return_number: str
    sale_id: int
    invoice_number: str
    reason: str
    refund_method: PaymentMethod
    refund_amount: Decimal
    operator_reference: str
    created_at: datetime
    items: list[SaleReturnItemRead]


class SalesRevenuePoint(BaseModel):
    day: date
    revenue: Decimal


class BestSellerRead(BaseModel):
    product_id: int
    product_name: str
    units_sold: int


class SalesSummaryRead(BaseModel):
    today_revenue: Decimal
    today_transactions: int
    week_revenue: Decimal
    month_revenue: Decimal
    daily_revenue: list[SalesRevenuePoint]
    best_sellers: list[BestSellerRead]
    recent_invoices: list[SaleHistoryRead]


class OrderItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=1_000_000)


class CustomerOrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1, max_length=100)
    fulfillment_method: Literal["pickup", "delivery"] = "pickup"
    delivery_address: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=320)] = None
    idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=80)]

    @model_validator(mode="after")
    def validate_order(self):
        if self.fulfillment_method == "delivery" and not self.delivery_address:
            raise ValueError("A delivery address is required for home delivery")
        if self.fulfillment_method == "pickup" and self.delivery_address:
            raise ValueError("A delivery address is only accepted for home delivery")
        product_ids = [item.product_id for item in self.items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Each product may only appear once in an order")
        return self


class CustomerOrderItemRead(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    requires_prescription: bool


class CustomerOrderStatusEventRead(BaseModel):
    status: OrderWorkflowStatus
    created_at: datetime


class CustomerOrderRead(BaseModel):
    id: int
    order_number: str
    status: OrderWorkflowStatus
    created_at: datetime
    fulfillment_method: Literal["pickup", "delivery"]
    delivery_address: str | None
    total_amount: Decimal
    requires_pharmacist_review: bool
    items: list[CustomerOrderItemRead]
    status_timeline: list[CustomerOrderStatusEventRead]


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1, max_length=100)
    customer_name: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] = None
    customer_phone: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] = None
    fulfillment_method: Literal["pickup", "delivery"] = "pickup"
    delivery_address: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=320)] = None
    notes: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None
    operator_reference: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] = None
    prescription_reference: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] = None

    @model_validator(mode="after")
    def validate_delivery(self):
        if self.fulfillment_method == "delivery" and not self.delivery_address:
            raise ValueError("A delivery address is required for home delivery")
        return self


class OrderItemRead(BaseModel):
    product_id: int
    product_name: str
    quantity: int


class OrderRead(BaseModel):
    id: int
    order_number: str
    status: str
    created_at: datetime
    items: list[OrderItemRead]


class OrderStatusUpdate(BaseModel):
    status: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^(pending|fulfilled|cancelled)$")]


class OrderWorkflowStatusUpdate(BaseModel):
    status: OrderWorkflowStatus
    operator_reference: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] = None
    note: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)] = None


class PrescriptionVerificationCreate(BaseModel):
    status: Literal["verified", "rejected"]
    pharmacist_reference: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    prescription_reference: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] = None
    note: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)] = None


class PrescriptionVerificationRead(BaseModel):
    id: int
    status: str
    prescription_reference: str | None
    pharmacist_reference: str | None
    note: str | None
    created_at: datetime


class OrderStatusEventRead(BaseModel):
    id: int
    previous_status: str | None
    updated_status: str
    operator_reference: str | None
    note: str | None
    created_at: datetime


class OrderWorkflowItemRead(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    requires_prescription: bool


class OrderWorkflowRead(BaseModel):
    id: int
    order_number: str
    status: str
    customer_name: str | None
    customer_phone: str | None
    fulfillment_method: str
    delivery_address: str | None
    notes: str | None
    operator_reference: str | None
    prescription_status: str
    prescription_reference: str | None
    created_at: datetime
    total_amount: Decimal
    items: list[OrderWorkflowItemRead]


class OrderWorkflowHistoryRead(BaseModel):
    order: OrderWorkflowRead
    status_events: list[OrderStatusEventRead]
    prescription_events: list[PrescriptionVerificationRead]


class SettingUpdate(BaseModel):
    value: Annotated[str, StringConstraints(max_length=1000)]


class SettingRead(BaseModel):
    key: str
    value: str
    updated_at: datetime
