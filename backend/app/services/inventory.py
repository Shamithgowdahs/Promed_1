from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, joinedload

from backend.app.models import (
    InventoryLocation,
    MedicineBatch,
    Product,
    ProductCategory,
    StockTransaction,
    Supplier,
)
from backend.app.schemas import BatchReceive
from backend.app.services.store_categories import category_name_key, category_slug


def classify_expiry(expiry_date: date, today: date | None = None) -> str:
    today = today or date.today()
    days_remaining = (expiry_date - today).days
    if days_remaining < 0:
        return "expired"
    if days_remaining <= 30:
        return "within_30_days"
    if days_remaining <= 60:
        return "within_60_days"
    if days_remaining <= 90:
        return "within_90_days"
    return "safe"


def eligible_stock_quantity(db: Session, product_id: int, today: date | None = None) -> int:
    stock_date = today or date.today()
    quantity = db.scalar(
        select(func.coalesce(func.sum(MedicineBatch.quantity), 0)).where(
            MedicineBatch.product_id == product_id,
            MedicineBatch.status == "active",
            MedicineBatch.expiry_date >= stock_date,
        )
    )
    return int(quantity or 0)


def batch_to_dict(batch: MedicineBatch, today: date | None = None) -> dict:
    today = today or date.today()
    available_quantity = (
        batch.quantity
        if batch.status == "active" and batch.expiry_date >= today
        else 0
    )
    return {
        "id": batch.id,
        "batch_number": batch.batch_number,
        "manufacturing_date": batch.manufacturing_date,
        "expiry_date": batch.expiry_date,
        "expiry_category": classify_expiry(batch.expiry_date, today),
        "days_remaining": (batch.expiry_date - today).days,
        "purchase_date": batch.purchase_date,
        "purchase_price": batch.purchase_price,
        "supplier_id": batch.supplier_id,
        "supplier_name": batch.supplier.name if batch.supplier else None,
        "supplier_reference": batch.supplier.reference_code if batch.supplier else None,
        "supplier_contact": batch.supplier.contact_details if batch.supplier else None,
        "supplier_address": batch.supplier.address if batch.supplier else None,
        "quantity": batch.quantity,
        "available_quantity": available_quantity,
        "received_quantity": batch.received_quantity,
        "status": batch.status,
        "location_code": batch.location.code,
        "unit_cost": batch.unit_cost,
    }


def inventory_batch_to_dict(batch: MedicineBatch, today: date | None = None) -> dict:
    return {
        **batch_to_dict(batch, today),
        "product_id": batch.product_id,
        "product_name": batch.product.name,
        "barcode": batch.product.barcode,
        "category_id": batch.product.category_id,
        "category_name": batch.product.category.name,
    }


def product_stock(db: Session, product_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(MedicineBatch.quantity), 0)).where(MedicineBatch.product_id == product_id)
    ) or 0


def product_to_dict(db: Session, product: Product) -> dict:
    batches = db.scalars(
        select(MedicineBatch)
        .options(joinedload(MedicineBatch.location), joinedload(MedicineBatch.supplier))
        .where(MedicineBatch.product_id == product.id)
        .order_by(MedicineBatch.expiry_date, MedicineBatch.id)
    ).all()
    quantities_by_location: dict[str, int] = {}
    for batch in batches:
        quantities_by_location[batch.location.code] = (
            quantities_by_location.get(batch.location.code, 0) + batch.quantity
        )

    return {
        "id": product.id,
        "name": product.name,
        "generic_name": product.generic_name,
        "barcode": product.barcode,
        "category_id": product.category_id,
        "category_name": product.category.name,
        "min_threshold": product.min_threshold,
        "unit_price": product.unit_price,
        "requires_prescription": product.requires_prescription,
        "stock_quantity": sum(batch.quantity for batch in batches),
        "available_stock_quantity": sum(
            batch.quantity
            for batch in batches
            if batch.status == "active" and batch.expiry_date >= date.today()
        ),
        "expired_stock_quantity": sum(
            batch.quantity for batch in batches if batch.expiry_date < date.today()
        ),
        "locations": sorted({batch.location.code for batch in batches if batch.quantity > 0}),
        "location_quantities": [
            {"location_code": code, "quantity": quantity}
            for code, quantity in sorted(quantities_by_location.items())
            if quantity > 0
        ],
        "batches": [batch_to_dict(batch) for batch in batches],
    }


class InventoryOperationError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def record_stock_receipt(db: Session, product: Product, payload: BatchReceive) -> MedicineBatch:
    if not product.active:
        raise InventoryOperationError(404, "Product not found")
    if payload.expiry_date < date.today():
        raise InventoryOperationError(422, "Cannot receive an already expired batch")
    try:
        location = resolve_location(db, payload.location_code)
    except ValueError as error:
        raise InventoryOperationError(404, str(error)) from error
    supplier = db.get(Supplier, payload.supplier_id) if payload.supplier_id else None
    if payload.supplier_id and supplier is None:
        raise InventoryOperationError(404, "Supplier not found")

    purchase_price = payload.purchase_price
    unit_cost = payload.unit_cost
    if purchase_price is None and unit_cost is not None:
        purchase_price = unit_cost * payload.quantity
    if unit_cost is None and purchase_price is not None:
        unit_cost = (purchase_price / payload.quantity).quantize(Decimal("0.01"))

    insert_statement = sqlite_insert(MedicineBatch).values(
        product_id=product.id,
        batch_number=payload.batch_number,
        manufacturing_date=payload.manufacturing_date,
        expiry_date=payload.expiry_date,
        purchase_date=payload.purchase_date,
        supplier_id=supplier.id if supplier else None,
        purchase_price=purchase_price,
        location_id=location.id,
        quantity=payload.quantity,
        received_quantity=payload.quantity,
        unit_cost=unit_cost,
        status="active",
    )
    excluded = insert_statement.excluded
    accumulated_purchase_price = func.coalesce(MedicineBatch.purchase_price, 0) + excluded.purchase_price
    accumulated_unit_cost = case(
        (
            excluded.purchase_price.is_not(None),
            accumulated_purchase_price
            / (MedicineBatch.received_quantity + excluded.received_quantity),
        ),
        else_=func.coalesce(excluded.unit_cost, MedicineBatch.unit_cost),
    )
    result = db.execute(
        insert_statement.on_conflict_do_update(
            index_elements=[
                MedicineBatch.product_id,
                MedicineBatch.batch_number,
                MedicineBatch.location_id,
            ],
            set_={
                "quantity": MedicineBatch.quantity + excluded.quantity,
                "received_quantity": MedicineBatch.received_quantity + excluded.received_quantity,
                "manufacturing_date": func.coalesce(
                    MedicineBatch.manufacturing_date,
                    excluded.manufacturing_date,
                ),
                "purchase_date": func.min(MedicineBatch.purchase_date, excluded.purchase_date),
                "supplier_id": func.coalesce(MedicineBatch.supplier_id, excluded.supplier_id),
                "purchase_price": case(
                    (excluded.purchase_price.is_not(None), accumulated_purchase_price),
                    else_=MedicineBatch.purchase_price,
                ),
                "unit_cost": accumulated_unit_cost,
            },
            where=(
                (MedicineBatch.expiry_date == excluded.expiry_date)
                & (
                    MedicineBatch.manufacturing_date.is_(None)
                    | excluded.manufacturing_date.is_(None)
                    | (MedicineBatch.manufacturing_date == excluded.manufacturing_date)
                )
                & (
                    MedicineBatch.supplier_id.is_(None)
                    | excluded.supplier_id.is_(None)
                    | (MedicineBatch.supplier_id == excluded.supplier_id)
                )
            ),
        ).returning(MedicineBatch.id, MedicineBatch.quantity)
    ).one_or_none()
    if result is None:
        raise InventoryOperationError(
            409,
            "Batch identity, expiry, manufacturing date, or supplier conflicts",
        )

    batch_id, updated_quantity = result
    batch = db.get(MedicineBatch, batch_id)
    if batch is None:
        raise InventoryOperationError(500, "Unable to load the recorded stock batch")
    db.add(
        StockTransaction(
            product_id=product.id,
            batch_id=batch.id,
            location_id=location.id,
            kind="receipt",
            quantity_delta=payload.quantity,
            previous_quantity=updated_quantity - payload.quantity,
            updated_quantity=updated_quantity,
            reason=f"Stock received from {supplier.name}" if supplier else "Stock received",
        )
    )
    return batch


def transaction_to_dict(transaction: StockTransaction) -> dict:
    return {
        "id": transaction.id,
        "product_id": transaction.product_id,
        "product_name": transaction.product.name,
        "batch_id": transaction.batch_id,
        "batch_number": transaction.batch.batch_number,
        "location_code": transaction.location.code,
        "kind": transaction.kind,
        "quantity_delta": transaction.quantity_delta,
        "previous_quantity": transaction.previous_quantity,
        "updated_quantity": transaction.updated_quantity,
        "reason": transaction.reason,
        "created_at": transaction.created_at,
    }


def resolve_category(db: Session, category_id: int | None, category_name: str | None) -> ProductCategory:
    if category_id is not None:
        category = db.get(ProductCategory, category_id)
        if category is None or not category.active:
            raise ValueError("Active category not found")
        return category

    normalized_name = category_name.strip()
    key = category_name_key(normalized_name)
    category = db.scalar(select(ProductCategory).where(ProductCategory.name_key == key))
    if category is not None and not category.active:
        raise ValueError("Category is inactive")
    if category is None:
        category = ProductCategory(
            name=normalized_name,
            name_key=key,
            slug=category_slug(normalized_name),
            active=True,
        )
        db.add(category)
        db.flush()
    return category


def resolve_location(db: Session, code: str) -> InventoryLocation:
    location = db.scalar(select(InventoryLocation).where(InventoryLocation.code == code.strip().upper()))
    if location is None:
        raise ValueError("Unknown inventory location")
    return location
