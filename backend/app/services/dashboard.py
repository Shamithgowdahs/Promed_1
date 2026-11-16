from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.models import InventoryLocation, MedicineBatch, Product, Sale, StockTransaction
from backend.app.services.inventory import classify_expiry, transaction_to_dict


def get_dashboard(db: Session) -> dict:
    product_count = db.scalar(select(func.count(Product.id)).where(Product.active.is_(True))) or 0
    stock_units = db.scalar(select(func.coalesce(func.sum(MedicineBatch.quantity), 0))) or 0
    available_stock_units = db.scalar(
        select(func.coalesce(func.sum(MedicineBatch.quantity), 0)).where(
            MedicineBatch.status == "active",
            MedicineBatch.expiry_date >= date.today(),
        )
    ) or 0
    expired_stock_units = db.scalar(
        select(func.coalesce(func.sum(MedicineBatch.quantity), 0)).where(
            MedicineBatch.expiry_date < date.today()
        )
    ) or 0
    locations = db.scalars(select(InventoryLocation).order_by(InventoryLocation.code)).all()
    location_data = []
    for location in locations:
        stock = db.scalar(
            select(func.coalesce(func.sum(MedicineBatch.quantity), 0)).where(
                MedicineBatch.location_id == location.id
            )
        ) or 0
        available_stock = db.scalar(
            select(func.coalesce(func.sum(MedicineBatch.quantity), 0)).where(
                MedicineBatch.location_id == location.id,
                MedicineBatch.status == "active",
                MedicineBatch.expiry_date >= date.today(),
            )
        ) or 0
        products_count = db.scalar(
            select(func.count(distinct(MedicineBatch.product_id))).where(
                MedicineBatch.location_id == location.id,
                MedicineBatch.quantity > 0,
            )
        ) or 0
        location_data.append(
            {
                "code": location.code,
                "name": location.name,
                "product_count": products_count,
                "stock_units": stock,
                "available_stock_units": available_stock,
            }
        )

    day_start = datetime.combine(date.today(), time.min).astimezone(timezone.utc).replace(tzinfo=None)
    day_end = day_start + timedelta(days=1)
    today_sales = db.scalar(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(
            Sale.created_at >= day_start,
            Sale.created_at < day_end,
        )
    ) or Decimal("0.00")

    stock_by_product = (
        select(MedicineBatch.product_id, func.sum(MedicineBatch.quantity).label("quantity"))
        .where(
            MedicineBatch.status == "active",
            MedicineBatch.expiry_date >= date.today(),
        )
        .group_by(MedicineBatch.product_id)
        .subquery()
    )
    low_stock_count = db.scalar(
        select(func.count(Product.id))
        .outerjoin(stock_by_product, Product.id == stock_by_product.c.product_id)
        .where(
            Product.active.is_(True),
            Product.min_threshold > 0,
            func.coalesce(stock_by_product.c.quantity, 0) <= Product.min_threshold,
        )
    ) or 0
    expiring_batch_count = db.scalar(
        select(func.count(MedicineBatch.id)).where(
            MedicineBatch.quantity > 0,
            MedicineBatch.expiry_date <= date.today() + timedelta(days=30),
        )
    ) or 0
    expiry_category_totals = {
        category: {"batch_count": 0, "quantity": 0}
        for category in ("expired", "within_30_days", "within_60_days", "within_90_days", "safe")
    }
    batch_expiries = db.execute(
        select(MedicineBatch.expiry_date, MedicineBatch.quantity).where(MedicineBatch.quantity > 0)
    ).all()
    for expiry_date, quantity in batch_expiries:
        category = classify_expiry(expiry_date)
        expiry_category_totals[category]["batch_count"] += 1
        expiry_category_totals[category]["quantity"] += quantity

    transactions = db.scalars(
        select(StockTransaction)
        .options(
            joinedload(StockTransaction.product),
            joinedload(StockTransaction.batch),
            joinedload(StockTransaction.location),
        )
        .order_by(StockTransaction.created_at.desc(), StockTransaction.id.desc())
        .limit(5)
    ).all()

    return {
        "product_count": product_count,
        "stock_units": stock_units,
        "available_stock_units": available_stock_units,
        "expired_stock_units": expired_stock_units,
        "today_sales_amount": today_sales,
        "low_stock_count": low_stock_count,
        "expiring_batch_count": expiring_batch_count,
        "expiry_categories": [
            {"category": category, **totals}
            for category, totals in expiry_category_totals.items()
        ],
        "locations": location_data,
        "recent_transactions": [transaction_to_dict(item) for item in transactions],
    }
