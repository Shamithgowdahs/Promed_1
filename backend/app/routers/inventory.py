from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models import (
    BatchStatusEvent,
    InventoryLocation,
    MedicineBatch,
    Product,
    ProductCategory,
    StockTransaction,
)
from backend.app.schemas import (
    BatchHistoryRead,
    BatchRead,
    BatchReceive,
    BatchStatusEventRead,
    BatchStatusUpdate,
    ExpiringBatchRead,
    ExpiryCategory,
    InventoryBatchRead,
    LowStockProductRead,
    StockAdjustment,
    StockTransactionRead,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)
from backend.app.services.inventory import (
    batch_to_dict,
    classify_expiry,
    inventory_batch_to_dict,
    product_to_dict,
    InventoryOperationError,
    record_stock_receipt,
    resolve_location,
    transaction_to_dict,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("/receipts", response_model=BatchRead, status_code=status.HTTP_201_CREATED)
def receive_stock(payload: BatchReceive, db: Session = Depends(get_db)):
    product = db.get(Product, payload.product_id)
    if product is None or not product.active:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        batch = record_stock_receipt(db, product, payload)
    except InventoryOperationError as error:
        db.rollback()
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    try:
        db.commit()
        db.refresh(batch)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to record this receipt") from error
    return batch_to_dict(batch)


@router.post("/adjustments", response_model=StockTransactionRead, status_code=status.HTTP_201_CREATED)
def adjust_stock(payload: StockAdjustment, db: Session = Depends(get_db)):
    batch = db.scalar(
        select(MedicineBatch)
        .options(joinedload(MedicineBatch.product), joinedload(MedicineBatch.location))
        .where(MedicineBatch.id == payload.batch_id)
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    result = db.execute(
        update(MedicineBatch)
        .where(
            MedicineBatch.id == batch.id,
            MedicineBatch.quantity + payload.quantity_delta >= 0,
        )
        .values(quantity=MedicineBatch.quantity + payload.quantity_delta)
        .returning(MedicineBatch.quantity)
    ).scalar_one_or_none()
    if result is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Adjustment would result in negative stock")
    updated_quantity = result
    transaction = StockTransaction(
        product_id=batch.product_id,
        batch_id=batch.id,
        location_id=batch.location_id,
        kind="adjustment",
        quantity_delta=payload.quantity_delta,
        previous_quantity=updated_quantity - payload.quantity_delta,
        updated_quantity=updated_quantity,
        reason=payload.reason,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction_to_dict(transaction)


@router.get("/transactions", response_model=list[StockTransactionRead])
def list_transactions(
    product_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = select(StockTransaction).options(
        joinedload(StockTransaction.product),
        joinedload(StockTransaction.batch),
        joinedload(StockTransaction.location),
    )
    if product_id is not None:
        statement = statement.where(StockTransaction.product_id == product_id)
    transactions = db.scalars(
        statement.order_by(StockTransaction.created_at.desc(), StockTransaction.id.desc()).limit(limit)
    ).unique().all()
    return [transaction_to_dict(item) for item in transactions]


@router.get("/low-stock", response_model=list[LowStockProductRead])
def list_low_stock_products(db: Session = Depends(get_db)):
    stock_by_product = (
        select(MedicineBatch.product_id, func.sum(MedicineBatch.quantity).label("quantity"))
        .where(
            MedicineBatch.status == "active",
            MedicineBatch.expiry_date >= date.today(),
        )
        .group_by(MedicineBatch.product_id)
        .subquery()
    )
    products = db.execute(
        select(Product, func.coalesce(stock_by_product.c.quantity, 0).label("quantity"))
        .outerjoin(stock_by_product, Product.id == stock_by_product.c.product_id)
        .where(
            Product.active.is_(True),
            Product.min_threshold > 0,
            func.coalesce(stock_by_product.c.quantity, 0) <= Product.min_threshold,
        )
        .order_by(Product.name)
    ).all()
    results = []
    for product, stock_quantity in products:
        product_data = product_to_dict(db, product)
        results.append(
            {
                "product_id": product.id,
                "product_name": product.name,
                "barcode": product.barcode,
                "stock_quantity": stock_quantity,
                "min_threshold": product.min_threshold,
                "suggested_reorder_quantity": max(product.min_threshold * 2 - stock_quantity, 0),
                "location_quantities": product_data["location_quantities"],
            }
        )
    return results


def _batch_filters(
    db: Session,
    statement,
    product_name: str | None,
    batch_number: str | None,
    expiry_from: date | None,
    expiry_to: date | None,
    category_id: int | None,
    location_code: str | None,
    expiry_category: ExpiryCategory | None,
    batch_status: Literal["active", "quarantined", "damaged"] | None,
):
    if expiry_from and expiry_to and expiry_from > expiry_to:
        raise HTTPException(status_code=422, detail="expiry_from must not be after expiry_to")
    if product_name and product_name.strip():
        statement = statement.where(Product.name.ilike(f"%{product_name.strip()}%"))
    if batch_number and batch_number.strip():
        statement = statement.where(MedicineBatch.batch_number.ilike(f"%{batch_number.strip()}%"))
    if expiry_from:
        statement = statement.where(MedicineBatch.expiry_date >= expiry_from)
    if expiry_to:
        statement = statement.where(MedicineBatch.expiry_date <= expiry_to)
    if category_id is not None:
        statement = statement.where(Product.category_id == category_id)
    if location_code:
        location = db.scalar(
            select(InventoryLocation).where(InventoryLocation.code == location_code.strip().upper())
        )
        if location is None:
            raise HTTPException(status_code=404, detail="Inventory location not found")
        statement = statement.where(MedicineBatch.location_id == location.id)
    if expiry_category:
        today = date.today()
        if expiry_category == "expired":
            statement = statement.where(MedicineBatch.expiry_date < today)
        elif expiry_category == "within_30_days":
            statement = statement.where(
                MedicineBatch.expiry_date >= today,
                MedicineBatch.expiry_date <= today + timedelta(days=30),
            )
        elif expiry_category == "within_60_days":
            statement = statement.where(
                MedicineBatch.expiry_date > today + timedelta(days=30),
                MedicineBatch.expiry_date <= today + timedelta(days=60),
            )
        elif expiry_category == "within_90_days":
            statement = statement.where(
                MedicineBatch.expiry_date > today + timedelta(days=60),
                MedicineBatch.expiry_date <= today + timedelta(days=90),
            )
        else:
            statement = statement.where(MedicineBatch.expiry_date > today + timedelta(days=90))
    if batch_status:
        statement = statement.where(MedicineBatch.status == batch_status)
    return statement


def _batch_list_statement(
    db: Session,
    product_name: str | None,
    batch_number: str | None,
    expiry_from: date | None,
    expiry_to: date | None,
    category_id: int | None,
    location_code: str | None,
    expiry_category: ExpiryCategory | None,
    batch_status: Literal["active", "quarantined", "damaged"] | None,
):
    statement = (
        select(MedicineBatch)
        .join(MedicineBatch.product)
        .options(
            joinedload(MedicineBatch.location),
            joinedload(MedicineBatch.supplier),
            joinedload(MedicineBatch.product).joinedload(Product.category),
        )
    )
    return _batch_filters(
        db,
        statement,
        product_name,
        batch_number,
        expiry_from,
        expiry_to,
        category_id,
        location_code,
        expiry_category,
        batch_status,
    )


@router.get("/batches", response_model=list[InventoryBatchRead])
def list_batches(
    product_name: str | None = Query(default=None, max_length=160),
    batch_number: str | None = Query(default=None, max_length=80),
    expiry_from: date | None = None,
    expiry_to: date | None = None,
    category_id: int | None = Query(default=None, gt=0),
    location_code: str | None = Query(default=None, max_length=16),
    expiry_category: ExpiryCategory | None = None,
    batch_status: Literal["active", "quarantined", "damaged"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = _batch_list_statement(
        db, product_name, batch_number, expiry_from, expiry_to, category_id,
        location_code, expiry_category, batch_status,
    )
    batches = db.scalars(
        statement.order_by(MedicineBatch.expiry_date, Product.name, MedicineBatch.batch_number).limit(limit)
    ).unique().all()
    return [inventory_batch_to_dict(batch) for batch in batches]


@router.get("/batches/{batch_id}", response_model=InventoryBatchRead)
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    batch = db.scalar(
        select(MedicineBatch)
        .options(
            joinedload(MedicineBatch.location),
            joinedload(MedicineBatch.supplier),
            joinedload(MedicineBatch.product).joinedload(Product.category),
        )
        .where(MedicineBatch.id == batch_id)
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return inventory_batch_to_dict(batch)


@router.patch("/batches/{batch_id}/status", response_model=BatchStatusEventRead)
def update_batch_status(batch_id: int, payload: BatchStatusUpdate, db: Session = Depends(get_db)):
    batch = db.get(MedicineBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    previous_status = batch.status
    if previous_status == payload.status:
        raise HTTPException(status_code=409, detail="Batch already has this status")

    updated = db.execute(
        update(MedicineBatch)
        .where(MedicineBatch.id == batch_id, MedicineBatch.status == previous_status)
        .values(status=payload.status)
        .returning(MedicineBatch.id)
    ).scalar_one_or_none()
    if updated is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Batch status changed concurrently; retry")

    event = BatchStatusEvent(
        batch_id=batch_id,
        previous_status=previous_status,
        updated_status=payload.status,
        reason=payload.reason,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/batches/{batch_id}/history", response_model=BatchHistoryRead)
def get_batch_history(batch_id: int, db: Session = Depends(get_db)):
    batch = db.scalar(
        select(MedicineBatch)
        .options(
            joinedload(MedicineBatch.location),
            joinedload(MedicineBatch.supplier),
            joinedload(MedicineBatch.product).joinedload(Product.category),
        )
        .where(MedicineBatch.id == batch_id)
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    transactions = db.scalars(
        select(StockTransaction)
        .options(
            joinedload(StockTransaction.product),
            joinedload(StockTransaction.batch),
            joinedload(StockTransaction.location),
        )
        .where(StockTransaction.batch_id == batch_id)
        .order_by(StockTransaction.created_at.desc(), StockTransaction.id.desc())
    ).unique().all()
    status_events = db.scalars(
        select(BatchStatusEvent)
        .where(BatchStatusEvent.batch_id == batch_id)
        .order_by(BatchStatusEvent.created_at.desc(), BatchStatusEvent.id.desc())
    ).all()
    return {
        "batch": inventory_batch_to_dict(batch),
        "transactions": [transaction_to_dict(item) for item in transactions],
        "status_events": status_events,
    }


@router.get("/expiry", response_model=list[InventoryBatchRead])
def list_expiring_batches(
    within_days: int | None = Query(default=None, ge=0, le=3650),
    product_name: str | None = Query(default=None, max_length=160),
    batch_number: str | None = Query(default=None, max_length=80),
    expiry_from: date | None = None,
    expiry_to: date | None = None,
    category_id: int | None = Query(default=None, gt=0),
    location_code: str | None = Query(default=None, max_length=16),
    expiry_category: ExpiryCategory | None = None,
    batch_status: Literal["active", "quarantined", "damaged"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    today = date.today()
    statement = _batch_list_statement(
        db, product_name, batch_number, expiry_from, expiry_to, category_id,
        location_code, expiry_category, batch_status,
    ).where(MedicineBatch.quantity > 0)
    if within_days is not None:
        statement = statement.where(MedicineBatch.expiry_date <= today + timedelta(days=within_days))
    elif expiry_category is None and expiry_from is None and expiry_to is None:
        statement = statement.where(MedicineBatch.expiry_date <= today + timedelta(days=30))
    batches = db.scalars(
        statement.order_by(MedicineBatch.expiry_date, Product.name, MedicineBatch.batch_number).limit(limit)
    ).unique().all()
    return [inventory_batch_to_dict(batch, today) for batch in batches]
