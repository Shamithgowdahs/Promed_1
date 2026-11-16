import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from io import BytesIO, StringIO
from xml.sax.saxutils import escape as escape_xml

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from backend.app.auth import require_owner
from backend.app.db import get_db
from backend.app.models import (
    MedicineBatch,
    Order,
    OrderItem,
    Product,
    ProductCategory,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    StockTransaction,
    StoreConfiguration,
    Supplier,
    InventoryLocation,
)

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(require_owner)])
MAX_REPORT_ROWS = 5000

REPORT_COLUMNS = {
    "sales": ["invoice_number", "date", "item_count", "subtotal", "discount", "tax", "total", "refunds", "net_revenue"],
    "revenue": ["invoice_number", "date", "item_count", "subtotal", "discount", "tax", "total", "refunds", "net_revenue"],
    "profit": ["product_id", "product_name", "category", "units_sold", "net_sales_ex_tax", "estimated_cost", "estimated_gross_profit", "missing_cost_units", "profit_calculable"],
    "product-performance": ["product_id", "product_name", "category", "units_sold", "net_sales_ex_tax", "estimated_cost", "estimated_gross_profit", "missing_cost_units", "profit_calculable"],
    "inventory": ["product_id", "product_name", "category", "active", "stock_units", "eligible_stock_units", "recorded_inventory_cost", "missing_cost_units", "min_threshold", "low_stock"],
    "low-stock": ["product_id", "product_name", "category", "active", "stock_units", "eligible_stock_units", "recorded_inventory_cost", "missing_cost_units", "min_threshold", "low_stock"],
    "inventory-by-location": ["product_id", "product_name", "category", "location_code", "location_name", "on_hand_units", "eligible_stock_units", "recorded_inventory_cost", "missing_cost_units"],
    "expiry": ["product_name", "category", "batch_number", "expiry_date", "days_remaining", "quantity", "status", "location_code"],
    "supplier-purchases": ["supplier_name", "purchase_date", "product_name", "batch_number", "location_code", "received_quantity", "purchase_price", "unit_cost", "recorded_purchase_value", "value_source"],
    "customer-orders": ["order_number", "date", "status", "workflow_status", "fulfillment_method", "item_count", "total_amount"],
    "stock-movement": ["date", "product_name", "batch_number", "location_code", "kind", "quantity_delta", "previous_quantity", "updated_quantity", "reason"],
}

REPORT_WARNINGS = {
    "profit": "Gross profit is estimated from the batch's currently recorded unit cost; cost is not snapshotted at sale time. Profit is unavailable where costs are missing.",
    "product-performance": "Gross profit is estimated from the batch's currently recorded unit cost; cost is not snapshotted at sale time. Profit is unavailable where costs are missing.",
    "supplier-purchases": "Receipts may be combined on a batch/location record. Transaction-level purchase prices are not retained separately; unavailable values are not inferred.",
}


def _number(value) -> float:
    return float(value or 0)


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _date_range(date_from: date | None, date_to: date | None):
    end = date_to or date.today()
    start = date_from or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    if (end - start).days > 1095:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 3 years")

    def boundary(day: date) -> datetime:
        return datetime.combine(day, time.min).astimezone(timezone.utc).replace(tzinfo=None)

    return start, end, boundary(start), boundary(end + timedelta(days=1))


def _as_datetime(value: datetime | None):
    return value.isoformat() if value else None


def _sales_rows(db: Session, start: datetime, end: datetime):
    sales = db.scalars(
        select(Sale)
        .where(Sale.created_at >= start, Sale.created_at < end)
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(MAX_REPORT_ROWS + 1)
    ).all()
    if not sales:
        return []
    sale_ids = [sale.id for sale in sales]
    item_counts = dict(
        db.execute(
            select(SaleItem.sale_id, func.count(SaleItem.id))
            .where(SaleItem.sale_id.in_(sale_ids))
            .group_by(SaleItem.sale_id)
        ).all()
    )
    refunds = dict(
        db.execute(
            select(SaleReturn.sale_id, func.sum(SaleReturn.refund_amount))
            .where(SaleReturn.sale_id.in_(sale_ids))
            .group_by(SaleReturn.sale_id)
        ).all()
    )
    return [
        {
            "invoice_number": sale.invoice_number,
            "date": _as_datetime(sale.created_at),
            "item_count": int(item_counts.get(sale.id, 0)),
            "subtotal": _number(sale.subtotal_amount),
            "discount": _number(sale.discount_amount),
            "tax": _number(sale.tax_amount),
            "total": _number(sale.total_amount),
            "refunds": _number(refunds.get(sale.id, 0)),
            "net_revenue": _number(sale.total_amount) - _number(refunds.get(sale.id, 0)),
        }
        for sale in sales
    ]


def _performance_rows(db: Session, start: datetime, end: datetime):
    restocked = (
        select(
            SaleReturnItem.sale_item_id.label("sale_item_id"),
            func.sum(SaleReturnItem.quantity).label("quantity"),
        )
        .where(SaleReturnItem.disposition == "restocked")
        .group_by(SaleReturnItem.sale_item_id)
        .subquery()
    )
    net_units = SaleItem.quantity - SaleItem.returned_quantity
    cost_units = SaleItem.quantity - func.coalesce(restocked.c.quantity, 0)
    net_sales = (
        SaleItem.unit_price * net_units
        - SaleItem.discount_amount * net_units / SaleItem.quantity
    )
    records = db.execute(
        select(
            Product.id,
            Product.name,
            ProductCategory.name,
            func.sum(net_units),
            func.sum(net_sales),
            func.sum(case((MedicineBatch.unit_cost.is_not(None), MedicineBatch.unit_cost * cost_units), else_=0)),
            func.sum(case((MedicineBatch.unit_cost.is_(None), cost_units), else_=0)),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .join(ProductCategory, ProductCategory.id == Product.category_id)
        .join(MedicineBatch, MedicineBatch.id == SaleItem.batch_id)
        .outerjoin(restocked, restocked.c.sale_item_id == SaleItem.id)
        .where(Sale.created_at >= start, Sale.created_at < end)
        .group_by(Product.id, Product.name, ProductCategory.name)
        .order_by(Product.name)
    ).all()
    results = []
    for product_id, name, category, units_sold, net_sales_ex_tax, estimated_cost, missing_cost_units in records:
        calculable = int(missing_cost_units or 0) == 0
        net_sales_value = _decimal(net_sales_ex_tax)
        cost_value = _decimal(estimated_cost)
        results.append(
            {
                "product_id": product_id,
                "product_name": name,
                "category": category,
                "units_sold": int(units_sold or 0),
                "net_sales_ex_tax": _number(net_sales_value),
                "estimated_cost": _number(cost_value) if calculable else None,
                "estimated_gross_profit": _number(net_sales_value - cost_value) if calculable else None,
                "missing_cost_units": int(missing_cost_units or 0),
                "profit_calculable": calculable,
            }
        )
    return sorted(results, key=lambda row: (-row["units_sold"], row["product_name"].casefold()))


def _inventory_rows(db: Session):
    products = db.execute(
        select(Product, ProductCategory.name)
        .join(ProductCategory, ProductCategory.id == Product.category_id)
        .order_by(Product.name)
    ).all()
    batches = db.execute(
        select(MedicineBatch.product_id, MedicineBatch.quantity, MedicineBatch.unit_cost, MedicineBatch.status, MedicineBatch.expiry_date)
        .where(MedicineBatch.quantity > 0)
    ).all()
    by_product = {}
    today = date.today()
    for product_id, quantity, unit_cost, status, expiry_date in batches:
        item = by_product.setdefault(product_id, {"stock": 0, "eligible": 0, "value": Decimal("0"), "missing": 0})
        item["stock"] += quantity
        if status == "active" and expiry_date >= today:
            item["eligible"] += quantity
        if unit_cost is None:
            item["missing"] += quantity
        else:
            item["value"] += _decimal(unit_cost) * quantity
    rows = []
    for product, category in products:
        stock = by_product.get(product.id, {"stock": 0, "eligible": 0, "value": Decimal("0"), "missing": 0})
        rows.append(
            {
                "product_id": product.id,
                "product_name": product.name,
                "category": category,
                "active": product.active,
                "stock_units": stock["stock"],
                "eligible_stock_units": stock["eligible"] if product.active else 0,
                "recorded_inventory_cost": _number(stock["value"]) if stock["missing"] == 0 else None,
                "missing_cost_units": stock["missing"],
                "min_threshold": product.min_threshold,
                "low_stock": bool(product.active and product.min_threshold > 0 and stock["eligible"] <= product.min_threshold),
            }
        )
    return rows


def _location_inventory_rows(db: Session):
    eligible_quantity = case(
        (and_(Product.active.is_(True), MedicineBatch.status == "active", MedicineBatch.expiry_date >= date.today()), MedicineBatch.quantity),
        else_=0,
    )
    missing_cost = func.sum(case((MedicineBatch.unit_cost.is_(None), MedicineBatch.quantity), else_=0))
    records = db.execute(
        select(
            Product.id,
            Product.name,
            ProductCategory.name,
            InventoryLocation.code,
            InventoryLocation.name,
            func.sum(MedicineBatch.quantity),
            func.sum(eligible_quantity),
            func.sum(case((MedicineBatch.unit_cost.is_not(None), MedicineBatch.unit_cost * MedicineBatch.quantity), else_=0)),
            missing_cost,
        )
        .join(MedicineBatch, MedicineBatch.product_id == Product.id)
        .join(ProductCategory, ProductCategory.id == Product.category_id)
        .join(InventoryLocation, InventoryLocation.id == MedicineBatch.location_id)
        .group_by(Product.id, Product.name, ProductCategory.name, InventoryLocation.id, InventoryLocation.code, InventoryLocation.name)
        .order_by(Product.name, InventoryLocation.code)
    ).all()
    return [
        {
            "product_id": product_id,
            "product_name": product_name,
            "category": category,
            "location_code": location_code,
            "location_name": location_name,
            "on_hand_units": int(on_hand or 0),
            "eligible_stock_units": int(eligible or 0),
            "recorded_inventory_cost": _number(recorded_cost) if not missing_cost else None,
            "missing_cost_units": int(missing_cost or 0),
        }
        for product_id, product_name, category, location_code, location_name, on_hand, eligible, recorded_cost, missing_cost in records
    ]


def _expiry_rows(db: Session, start_day: date, end_day: date):
    records = db.execute(
        select(MedicineBatch, Product.name, ProductCategory.name, InventoryLocation.code)
        .join(Product, Product.id == MedicineBatch.product_id)
        .join(ProductCategory, ProductCategory.id == Product.category_id)
        .join(InventoryLocation, InventoryLocation.id == MedicineBatch.location_id)
        .where(
            MedicineBatch.expiry_date >= start_day,
            MedicineBatch.expiry_date <= end_day,
            MedicineBatch.quantity > 0,
        )
        .order_by(MedicineBatch.expiry_date, Product.name)
        .limit(MAX_REPORT_ROWS + 1)
    ).all()
    today = date.today()
    return [
        {
            "product_name": name,
            "category": category,
            "batch_number": batch.batch_number,
            "expiry_date": batch.expiry_date.isoformat(),
            "days_remaining": (batch.expiry_date - today).days,
            "quantity": batch.quantity,
            "status": batch.status,
            "location_code": location,
        }
        for batch, name, category, location in records
    ]


def _purchase_rows(db: Session, start_day: date, end_day: date):
    records = db.execute(
        select(MedicineBatch, Product.name, Supplier.name, InventoryLocation.code)
        .join(Product, Product.id == MedicineBatch.product_id)
        .outerjoin(Supplier, Supplier.id == MedicineBatch.supplier_id)
        .join(InventoryLocation, InventoryLocation.id == MedicineBatch.location_id)
        .where(MedicineBatch.purchase_date >= start_day, MedicineBatch.purchase_date <= end_day)
        .order_by(MedicineBatch.purchase_date.desc(), Product.name)
    ).all()
    return [
        {
            "supplier_name": supplier or "Not recorded",
            "purchase_date": batch.purchase_date.isoformat(),
            "product_name": product_name,
            "batch_number": batch.batch_number,
            "location_code": location,
            "received_quantity": batch.received_quantity,
            "purchase_price": _number(batch.purchase_price) if batch.purchase_price is not None else None,
            "unit_cost": _number(batch.unit_cost) if batch.unit_cost is not None else None,
            "recorded_purchase_value": (
                _number(batch.purchase_price) if batch.purchase_price is not None else None
            ),
            "value_source": "recorded batch purchase price" if batch.purchase_price is not None else "not recorded",
        }
        for batch, product_name, supplier, location in records
    ]


def _order_rows(db: Session, start: datetime, end: datetime):
    item_counts = (
        select(OrderItem.order_id.label("order_id"), func.count(OrderItem.id).label("item_count"))
        .group_by(OrderItem.order_id)
        .subquery()
    )
    records = db.execute(
        select(Order, func.coalesce(item_counts.c.item_count, 0))
        .outerjoin(item_counts, item_counts.c.order_id == Order.id)
        .where(Order.created_at >= start, Order.created_at < end)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(MAX_REPORT_ROWS + 1)
    ).all()
    return [
        {
            "order_number": order.order_number,
            "date": _as_datetime(order.created_at),
            "status": order.status,
            "workflow_status": order.workflow_status,
            "fulfillment_method": order.fulfillment_method,
            "item_count": int(item_count),
            "total_amount": _number(order.total_amount),
        }
        for order, item_count in records
    ]


def _movement_rows(db: Session, start: datetime, end: datetime):
    records = db.execute(
        select(StockTransaction, Product.name, MedicineBatch.batch_number, InventoryLocation.code)
        .join(Product, Product.id == StockTransaction.product_id)
        .join(MedicineBatch, MedicineBatch.id == StockTransaction.batch_id)
        .join(InventoryLocation, InventoryLocation.id == StockTransaction.location_id)
        .where(StockTransaction.created_at >= start, StockTransaction.created_at < end)
        .order_by(StockTransaction.created_at.desc(), StockTransaction.id.desc())
        .limit(MAX_REPORT_ROWS + 1)
    ).all()
    return [
        {
            "date": _as_datetime(transaction.created_at),
            "product_name": product_name,
            "batch_number": batch_number,
            "location_code": location,
            "kind": transaction.kind,
            "quantity_delta": transaction.quantity_delta,
            "previous_quantity": transaction.previous_quantity,
            "updated_quantity": transaction.updated_quantity,
            "reason": transaction.reason or "",
        }
        for transaction, product_name, batch_number, location in records
    ]


def _report_rows(db: Session, report_type: str, start: datetime, end: datetime, start_day: date, end_day: date):
    if report_type in {"sales", "revenue"}:
        return _sales_rows(db, start, end)
    if report_type in {"profit", "product-performance"}:
        return _performance_rows(db, start, end)
    if report_type == "inventory":
        return _inventory_rows(db)
    if report_type == "inventory-by-location":
        return _location_inventory_rows(db)
    if report_type == "low-stock":
        return [row for row in _inventory_rows(db) if row["low_stock"]]
    if report_type == "expiry":
        return _expiry_rows(db, start_day, end_day)
    if report_type == "supplier-purchases":
        return _purchase_rows(db, start_day, end_day)
    if report_type == "customer-orders":
        return _order_rows(db, start, end)
    if report_type == "stock-movement":
        return _movement_rows(db, start, end)
    raise HTTPException(status_code=404, detail="Unknown analytics report")


def _filter_rows(rows, search: str | None, category: str | None, sort_by: str | None, direction: str):
    if search and search.strip():
        term = search.strip().casefold()
        rows = [row for row in rows if any(term in str(value).casefold() for value in row.values() if value is not None)]
    if category and category.strip():
        rows = [row for row in rows if row.get("category") == category.strip()]
    if sort_by:
        if not rows or sort_by not in rows[0]:
            raise HTTPException(status_code=422, detail="sort_by is not a column in this report")
        rows = sorted(rows, key=lambda row: (row.get(sort_by) is None, row.get(sort_by)), reverse=direction == "desc")
    truncated = len(rows) > MAX_REPORT_ROWS
    return rows[:MAX_REPORT_ROWS], truncated


def _dashboard_trend(db: Session, start_day: date, end_day: date):
    span = (end_day - start_day).days
    use_months = span > 62
    sales = db.execute(
        select(Sale.created_at, Sale.total_amount, Sale.id)
        .where(Sale.created_at >= _date_range(start_day, end_day)[2], Sale.created_at < _date_range(start_day, end_day)[3])
        .order_by(Sale.created_at)
    ).all()
    values = {}
    for created_at, total, _sale_id in sales:
        key = created_at.strftime("%Y-%m") if use_months else created_at.date().isoformat()
        values[key] = values.get(key, Decimal("0")) + _decimal(total)
    labels = []
    cursor = start_day.replace(day=1) if use_months else start_day
    last = end_day.replace(day=1) if use_months else end_day
    while cursor <= last:
        labels.append(cursor.strftime("%Y-%m") if use_months else cursor.isoformat())
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1) if use_months else cursor + timedelta(days=1)
    return {"period": "month" if use_months else "day", "points": [{"period": key, "sales": _number(values.get(key, 0))} for key in labels]}


@router.get("/dashboard")
def get_analytics_dashboard(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    start_day, end_day, start, end = _date_range(date_from, date_to)
    sales = db.execute(
        select(
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.subtotal_amount), 0),
            func.coalesce(func.sum(Sale.discount_amount), 0),
            func.coalesce(func.sum(Sale.tax_amount), 0),
            func.coalesce(func.sum(Sale.total_amount), 0),
        ).where(Sale.created_at >= start, Sale.created_at < end)
    ).one()
    refunds = db.scalar(
        select(func.coalesce(func.sum(SaleReturn.refund_amount), 0))
        .join(Sale, Sale.id == SaleReturn.sale_id)
        .where(Sale.created_at >= start, Sale.created_at < end)
    ) or 0
    sale_count, subtotal, discounts, tax, total = sales
    inventory = _inventory_rows(db)
    performance = _performance_rows(db, start, end)
    missing_cost_units = sum(row["missing_cost_units"] for row in performance)
    estimated_profit = (
        sum(row["estimated_gross_profit"] or 0 for row in performance)
        if missing_cost_units == 0
        else None
    )
    batch_rows = db.execute(
        select(MedicineBatch.quantity, MedicineBatch.status, MedicineBatch.expiry_date, MedicineBatch.unit_cost, Product.active)
        .join(Product, Product.id == MedicineBatch.product_id)
        .where(MedicineBatch.quantity > 0)
    ).all()
    today = date.today()
    expiry = {"expired": 0, "within_7_days": 0, "within_30_days": 0, "within_60_days": 0, "within_90_days": 0}
    inventory_value = Decimal("0")
    inventory_cost_missing_units = 0
    on_hand = eligible = 0
    for quantity, batch_status, expiry_date, unit_cost, product_active in batch_rows:
        on_hand += quantity
        if product_active and batch_status == "active" and expiry_date >= today:
            eligible += quantity
        if unit_cost is None:
            inventory_cost_missing_units += quantity
        else:
            inventory_value += _decimal(unit_cost) * quantity
        if batch_status == "active":
            days = (expiry_date - today).days
            if days < 0:
                expiry["expired"] += quantity
            elif days <= 7:
                expiry["within_7_days"] += quantity
            elif days <= 30:
                expiry["within_30_days"] += quantity
            elif days <= 60:
                expiry["within_60_days"] += quantity
            elif days <= 90:
                expiry["within_90_days"] += quantity
    low_stock_count = sum(1 for row in inventory if row["low_stock"])
    currency = db.get(StoreConfiguration, 1)
    order_counts = dict(
        db.execute(
            select(Order.workflow_status, func.count(Order.id))
            .where(Order.created_at >= start, Order.created_at < end)
            .group_by(Order.workflow_status)
        ).all()
    )
    purchases = _purchase_rows(db, start_day, end_day)
    movement = _movement_rows(db, start, end)
    return {
        "date_from": start_day.isoformat(),
        "date_to": end_day.isoformat(),
        "currency_code": currency.currency_code if currency else None,
        "categories": list(db.scalars(select(ProductCategory.name).order_by(ProductCategory.name)).all()),
        "sales": {
            "transaction_count": int(sale_count),
            "subtotal": _number(subtotal),
            "discounts": _number(discounts),
            "tax": _number(tax),
            "gross_sales": _number(total),
            "refunds": _number(refunds),
            "net_revenue": _number(_decimal(total) - _decimal(refunds)),
            "average_transaction": _number((_decimal(total) - _decimal(refunds)) / sale_count) if sale_count else 0,
            "units_sold": sum(row["units_sold"] for row in performance),
        },
        "profit": {
            "estimated_gross_profit": estimated_profit,
            "calculable": missing_cost_units == 0,
            "missing_cost_units": missing_cost_units,
            "basis": REPORT_WARNINGS["profit"],
        },
        "inventory": {
            "active_products": sum(1 for row in inventory if row["active"]),
            "on_hand_units": on_hand,
            "eligible_units": eligible,
            "low_stock_products": low_stock_count,
            "recorded_cost_value": _number(inventory_value) if inventory_cost_missing_units == 0 else None,
            "missing_cost_units": inventory_cost_missing_units,
        },
        "expiry": expiry,
        "order_workflow": dict(order_counts),
        "purchase_summary": {
            "record_count": len(purchases),
            "recorded_purchase_value": sum(row["recorded_purchase_value"] or 0 for row in purchases),
            "unpriced_batch_count": sum(1 for row in purchases if row["recorded_purchase_value"] is None),
        },
        "sales_trend": _dashboard_trend(db, start_day, end_day),
        "best_sellers": performance[:10],
        "category_performance": _category_performance(performance),
        "low_stock": [row for row in inventory if row["low_stock"]][:10],
        "recent_stock_movements": movement[:20],
        "recent_receipts": [row for row in movement if row["kind"] == "receipt"][:10],
        "recent_sales": _sales_rows(db, start, end)[:10],
        "purchase_records": purchases[:10],
        "recent_orders": _order_rows(db, start, end)[:10],
        "notes": [
            "All figures are derived from saved database records. Empty results mean no matching records exist.",
            "Net revenue and average transaction use saved invoice totals (including configured tax) less recorded returns for those invoices.",
            REPORT_WARNINGS["profit"],
            REPORT_WARNINGS["supplier-purchases"],
            "No purchase-order model exists, so pending purchase orders cannot be reported.",
            *(["The store currency is not configured; monetary values are shown without a currency code."] if currency is None else []),
        ],
    }


def _category_performance(performance):
    grouped = {}
    for row in performance:
        category = grouped.setdefault(row["category"], {"category": row["category"], "units_sold": 0, "net_sales_ex_tax": 0.0})
        category["units_sold"] += row["units_sold"]
        category["net_sales_ex_tax"] += row["net_sales_ex_tax"]
    return sorted(grouped.values(), key=lambda row: (-row["net_sales_ex_tax"], row["category"].casefold()))


@router.get("/reports/{report_type}")
def get_report(
    report_type: str,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=80),
    sort_by: str | None = Query(default=None, max_length=40),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    start_day, end_day, start, end = _date_range(date_from, date_to)
    rows = _report_rows(db, report_type, start, end, start_day, end_day)
    rows, truncated = _filter_rows(rows, search, category, sort_by, direction)
    if report_type not in REPORT_COLUMNS:
        raise HTTPException(status_code=404, detail="Unknown analytics report")
    return {
        "report_type": report_type,
        "date_from": start_day.isoformat(),
        "date_to": end_day.isoformat(),
        "columns": REPORT_COLUMNS[report_type],
        "categories": list(db.scalars(select(ProductCategory.name).order_by(ProductCategory.name)).all()),
        "rows": rows,
        "truncated": truncated,
        "row_limit": MAX_REPORT_ROWS,
        "warning": REPORT_WARNINGS.get(report_type),
    }


def _csv_value(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


@router.get("/reports/{report_type}/export")
def export_report(
    report_type: str,
    format: str = Query(default="csv", pattern="^(csv|pdf)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=80),
    sort_by: str | None = Query(default=None, max_length=40),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    start_day, end_day, start, end = _date_range(date_from, date_to)
    rows = _report_rows(db, report_type, start, end, start_day, end_day)
    rows, truncated = _filter_rows(rows, search, category, sort_by, direction)
    columns = REPORT_COLUMNS.get(report_type)
    if columns is None:
        raise HTTPException(status_code=404, detail="Unknown analytics report")
    title = report_type.replace("-", " ").title()
    if format == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_csv_value(row.get(column)) for column in columns])
        if truncated:
            writer.writerow([])
            writer.writerow(["Export capped at", MAX_REPORT_ROWS, "most recent/available rows"])
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="promed-{report_type}-{start_day}-{end_day}.csv"'},
        )

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(letter), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    content = [Paragraph(f"PROMED — {title}", styles["Title"]), Paragraph(f"{start_day} through {end_day}", styles["Normal"]), Spacer(1, 10)]
    table_data = [[Paragraph(escape_xml(column.replace("_", " ").title()), styles["BodyText"]) for column in columns]]
    table_data.extend(
        [[Paragraph(escape_xml(str(row.get(column) if row.get(column) is not None else "Not available")), styles["BodyText"]) for column in columns] for row in rows]
    )
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15324b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
    ]))
    content.append(table)
    if truncated:
        content.append(Spacer(1, 8))
        content.append(Paragraph(f"Report capped at {MAX_REPORT_ROWS} rows.", styles["Italic"]))
    if report_type in REPORT_WARNINGS:
        content.append(Spacer(1, 8))
        content.append(Paragraph(REPORT_WARNINGS[report_type], styles["Italic"]))
    document.build(content)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="promed-{report_type}-{start_day}-{end_day}.pdf"'},
    )
