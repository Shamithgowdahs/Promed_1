import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from io import BytesIO
from uuid import uuid4
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.models import (
    MedicineBatch,
    PaymentRecord,
    Product,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    StockTransaction,
    StoreConfiguration,
)
from backend.app.schemas import (
    InvoiceRead,
    PaymentMethod,
    SaleCheckout,
    SaleHistoryRead,
    SaleRead,
    SaleCreate,
    SaleReturnCreate,
    SaleReturnRead,
    SalesConfigRead,
    SalesConfigUpdate,
    SalesSummaryRead,
)

router = APIRouter(prefix="/sales", tags=["sales"])
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def request_fingerprint(payload: BaseModel) -> str:
    serialized = payload.model_dump(mode="json")
    canonical = json.dumps(serialized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def allocate_amount(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    if not weights:
        return []
    cents = int(money(total) * 100)
    weight_cents = [int(money(weight) * 100) for weight in weights]
    denominator = sum(weight_cents)
    if denominator <= 0:
        result = [Decimal("0.00")] * len(weights)
        result[-1] = money(total)
        return result
    amounts = [
        (Decimal(cents * weight) / Decimal(denominator)).to_integral_value(rounding=ROUND_FLOOR)
        for weight in weight_cents
    ]
    amounts[-1] += cents - sum(int(amount) for amount in amounts)
    return [money(amount / 100) for amount in amounts]


def sale_to_dict(sale: Sale) -> dict:
    return {
        "id": sale.id,
        "invoice_number": sale.invoice_number,
        "total_amount": sale.total_amount,
        "created_at": sale.created_at,
        "items": [
            {
                "product_id": item.product_id,
                "product_name": item.product.name,
                "batch_id": item.batch_id,
                "batch_number": item.batch.batch_number,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
            }
            for item in sale.items
        ],
    }


def sale_history_to_dict(sale: Sale) -> dict:
    return {
        "sale_id": sale.id,
        "invoice_number": sale.invoice_number,
        "created_at": sale.created_at,
        "customer_name": sale.customer_name,
        "customer_phone": sale.customer_phone,
        "currency_code": sale.currency_code,
        "subtotal_amount": sale.subtotal_amount,
        "discount_amount": sale.discount_amount,
        "tax_amount": sale.tax_amount,
        "total_amount": sale.total_amount,
        "payment_method": sale.payment.method if sale.payment else None,
        "item_count": sum(item.quantity for item in sale.items),
    }


def invoice_to_dict(sale: Sale) -> dict:
    payment = sale.payment
    return {
        "sale_id": sale.id,
        "invoice_number": sale.invoice_number,
        "created_at": sale.created_at,
        "store_name": sale.store_name,
        "store_phone": sale.store_phone,
        "store_address": sale.store_address,
        "currency_code": sale.currency_code,
        "customer_name": sale.customer_name,
        "customer_phone": sale.customer_phone,
        "operator_reference": sale.operator_reference,
        "subtotal_amount": sale.subtotal_amount,
        "discount_amount": sale.discount_amount,
        "discount_authorized_by": sale.discount_authorized_by,
        "discount_reason": sale.discount_reason,
        "prescription_reference": sale.prescription_reference,
        "pharmacist_reference": sale.pharmacist_reference,
        "tax_rate_percent": sale.tax_rate_percent,
        "tax_amount": sale.tax_amount,
        "total_amount": sale.total_amount,
        "payment": (
            {
                "id": payment.id,
                "kind": payment.kind,
                "method": payment.method,
                "amount": payment.amount,
                "cash_received": payment.cash_received,
                "change_given": payment.change_given,
                "reference": payment.reference,
                "created_at": payment.created_at,
            }
            if payment
            else None
        ),
        "items": [
            {
                "sale_item_id": item.id,
                "product_name": item.product.name,
                "batch_number": item.batch.batch_number,
                "quantity": item.quantity,
                "returned_quantity": item.returned_quantity,
                "unit_price": item.unit_price,
                "discount_amount": item.discount_amount,
                "tax_amount": item.tax_amount,
                "line_total": item.line_total,
            }
            for item in sale.items
        ],
    }


def sale_statement():
    return select(Sale).options(
        joinedload(Sale.payment),
        joinedload(Sale.items).joinedload(SaleItem.product),
        joinedload(Sale.items).joinedload(SaleItem.batch),
    )


def load_sale(db: Session, sale_id: int) -> Sale:
    sale = db.execute(sale_statement().where(Sale.id == sale_id)).unique().scalar_one_or_none()
    if sale is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return sale


def sale_return_to_dict(sale_return: SaleReturn) -> dict:
    return {
        "id": sale_return.id,
        "return_number": sale_return.return_number,
        "sale_id": sale_return.sale_id,
        "invoice_number": sale_return.sale.invoice_number,
        "reason": sale_return.reason,
        "refund_method": sale_return.refund_method,
        "refund_amount": sale_return.refund_amount,
        "operator_reference": sale_return.operator_reference,
        "created_at": sale_return.created_at,
        "items": [
            {
                "sale_item_id": item.sale_item_id,
                "product_name": item.sale_item.product.name,
                "batch_number": item.sale_item.batch.batch_number,
                "quantity": item.quantity,
                "disposition": item.disposition,
                "restock_verified_by": item.restock_verified_by,
                "refund_amount": item.refund_amount,
            }
            for item in sale_return.items
        ],
    }


def load_sale_return(db: Session, return_id: int) -> SaleReturn | None:
    return db.execute(
        select(SaleReturn)
        .options(
            joinedload(SaleReturn.sale),
            joinedload(SaleReturn.payment),
            joinedload(SaleReturn.items).joinedload(SaleReturnItem.sale_item).joinedload(SaleItem.product),
            joinedload(SaleReturn.items).joinedload(SaleReturnItem.sale_item).joinedload(SaleItem.batch),
        )
        .where(SaleReturn.id == return_id)
    ).unique().scalar_one_or_none()


def invoice_pdf(invoice: dict) -> BytesIO:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=f"Invoice {invoice['invoice_number']}",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(escape(invoice["store_name"] or "Store name not configured"), styles["Title"]),
        Paragraph(escape(invoice["store_phone"] or ""), styles["Normal"]),
        Paragraph(escape(invoice["store_address"] or ""), styles["Normal"]),
        Spacer(1, 12),
        Paragraph("INVOICE", styles["Heading1"]),
        Paragraph(f"Invoice: {escape(invoice['invoice_number'])}", styles["Normal"]),
        Paragraph(f"Date: {escape(str(invoice['created_at']))}", styles["Normal"]),
    ]
    if invoice["customer_name"]:
        story.append(Paragraph(f"Customer: {escape(invoice['customer_name'])}", styles["Normal"]))
    if invoice["customer_phone"]:
        story.append(Paragraph(f"Customer phone: {escape(invoice['customer_phone'])}", styles["Normal"]))
    if invoice["operator_reference"]:
        story.append(Paragraph(f"Operator: {escape(invoice['operator_reference'])}", styles["Normal"]))
    if invoice["prescription_reference"]:
        story.append(Paragraph(f"Prescription reference: {escape(invoice['prescription_reference'])}", styles["Normal"]))
    if invoice["pharmacist_reference"]:
        story.append(Paragraph(f"Pharmacist: {escape(invoice['pharmacist_reference'])}", styles["Normal"]))

    currency = escape(invoice["currency_code"] or "")
    rows = [["Medicine / batch", "Qty", "Unit price", "Discount", "Tax", "Amount"]]
    for item in invoice["items"]:
        rows.append(
            [
                Paragraph(
                    f"{escape(item['product_name'])}<br/><font size='8'>Batch {escape(item['batch_number'])}</font>",
                    styles["Normal"],
                ),
                str(item["quantity"]),
                f"{currency} {item['unit_price']:.2f}",
                f"{currency} {item['discount_amount']:.2f}",
                f"{currency} {item['tax_amount']:.2f}",
                f"{currency} {item['line_total']:.2f}",
            ]
        )
    table = Table(rows, colWidths=[2.5 * inch, 0.45 * inch, 0.8 * inch, 0.75 * inch, 0.65 * inch, 0.8 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#152238")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c6d0dc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend(
        [
            Spacer(1, 14),
            table,
            Spacer(1, 12),
            Paragraph(f"Subtotal: {currency} {invoice['subtotal_amount']:.2f}", styles["Normal"]),
            Paragraph(f"Discount: {currency} {invoice['discount_amount']:.2f}", styles["Normal"]),
            Paragraph(
                f"Configured tax ({invoice['tax_rate_percent']:.2f}%): "
                f"{currency} {invoice['tax_amount']:.2f}",
                styles["Normal"],
            ),
            Paragraph(f"<b>Total: {currency} {invoice['total_amount']:.2f}</b>", styles["Heading2"]),
        ]
    )
    if invoice["payment"]:
        payment = invoice["payment"]
        story.append(
            Paragraph(
                f"Payment: {escape(payment['method'].upper())} · {currency} {payment['amount']:.2f}",
                styles["Normal"],
            )
        )
        if payment["reference"]:
            story.append(Paragraph(f"Payment reference: {escape(payment['reference'])}", styles["Normal"]))
    if invoice["discount_authorized_by"]:
        story.append(
            Paragraph(
                f"Discount authorized by: {escape(invoice['discount_authorized_by'])}"
                + (f" — {escape(invoice['discount_reason'])}" if invoice["discount_reason"] else ""),
                styles["Normal"],
            )
        )
    document.build(story)
    buffer.seek(0)
    return buffer


def _configured_store(db: Session) -> StoreConfiguration:
    config = db.get(StoreConfiguration, 1)
    if config is None:
        raise HTTPException(
            status_code=409,
            detail="Configure the store identity, currency, and tax rate before checkout",
        )
    return config


@router.get("/config", response_model=SalesConfigRead)
def get_sales_config(db: Session = Depends(get_db)):
    config = db.get(StoreConfiguration, 1)
    if config is None:
        return {
            "configured": False,
            "store_name": None,
            "store_phone": None,
            "store_address": None,
            "tax_rate_percent": None,
            "currency_code": None,
        }
    return {
        "configured": True,
        "store_name": config.store_name,
        "store_phone": config.store_phone,
        "store_address": config.store_address,
        "tax_rate_percent": config.tax_rate_percent,
        "currency_code": config.currency_code,
    }


@router.put("/config", response_model=SalesConfigRead)
def save_sales_config(payload: SalesConfigUpdate, db: Session = Depends(get_db)):
    config = db.get(StoreConfiguration, 1)
    if config is None:
        config = StoreConfiguration(id=1, **payload.model_dump())
        db.add(config)
    else:
        for field, value in payload.model_dump().items():
            setattr(config, field, value)
    db.commit()
    return get_sales_config(db)


@router.get("/summary", response_model=SalesSummaryRead)
def get_sales_summary(db: Session = Depends(get_db)):
    today = date.today()

    def day_start(day: date) -> datetime:
        return datetime.combine(day, time.min).astimezone(timezone.utc).replace(tzinfo=None)

    def revenue_between(start: date, end: date) -> Decimal:
        start_time = day_start(start)
        end_time = day_start(end)
        sales_total = db.scalar(
            select(func.coalesce(func.sum(Sale.total_amount), 0)).where(
                Sale.created_at >= start_time,
                Sale.created_at < end_time,
            )
        ) or Decimal("0.00")
        returns_total = db.scalar(
            select(func.coalesce(func.sum(SaleReturn.refund_amount), 0)).where(
                SaleReturn.created_at >= start_time,
                SaleReturn.created_at < end_time,
            )
        ) or Decimal("0.00")
        return money(Decimal(sales_total) - Decimal(returns_total))

    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    today_start = day_start(today)
    tomorrow_start = day_start(today + timedelta(days=1))
    today_transactions = db.scalar(
        select(func.count(Sale.id)).where(
            Sale.created_at >= today_start,
            Sale.created_at < tomorrow_start,
        )
    ) or 0

    revenue_points = [
        {"day": today - timedelta(days=offset), "revenue": revenue_between(today - timedelta(days=offset), today - timedelta(days=offset - 1))}
        for offset in range(6, -1, -1)
    ]
    best_seller_rows = db.execute(
        select(
            SaleItem.product_id,
            Product.name,
            func.sum(SaleItem.quantity - SaleItem.returned_quantity).label("units_sold"),
        )
        .join(Product, Product.id == SaleItem.product_id)
        .group_by(SaleItem.product_id, Product.name)
        .order_by(func.sum(SaleItem.quantity - SaleItem.returned_quantity).desc(), Product.name)
        .limit(5)
    ).all()
    recent_sales = db.scalars(
        sale_statement().order_by(Sale.created_at.desc(), Sale.id.desc()).limit(10)
    ).unique().all()
    return {
        "today_revenue": revenue_between(today, today + timedelta(days=1)),
        "today_transactions": today_transactions,
        "week_revenue": revenue_between(week_start, today + timedelta(days=1)),
        "month_revenue": revenue_between(month_start, today + timedelta(days=1)),
        "daily_revenue": revenue_points,
        "best_sellers": [
            {"product_id": product_id, "product_name": name, "units_sold": units_sold}
            for product_id, name, units_sold in best_seller_rows
        ],
        "recent_invoices": [sale_history_to_dict(sale) for sale in recent_sales],
    }


@router.get("/history", response_model=list[SaleHistoryRead])
def search_sales_history(
    invoice_number: str | None = Query(default=None, max_length=40),
    customer_phone: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = sale_statement()
    if invoice_number and invoice_number.strip():
        statement = statement.where(Sale.invoice_number.ilike(f"%{invoice_number.strip()}%"))
    if customer_phone and customer_phone.strip():
        statement = statement.where(Sale.customer_phone == customer_phone.strip())
    sales = db.scalars(
        statement.order_by(Sale.created_at.desc(), Sale.id.desc()).limit(limit)
    ).unique().all()
    return [sale_history_to_dict(sale) for sale in sales]


@router.get("/returns", response_model=list[SaleReturnRead])
def search_returns(
    invoice_number: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = select(SaleReturn).options(
        joinedload(SaleReturn.sale),
        joinedload(SaleReturn.items).joinedload(SaleReturnItem.sale_item).joinedload(SaleItem.product),
        joinedload(SaleReturn.items).joinedload(SaleReturnItem.sale_item).joinedload(SaleItem.batch),
    )
    if invoice_number and invoice_number.strip():
        statement = statement.join(SaleReturn.sale).where(
            Sale.invoice_number.ilike(f"%{invoice_number.strip()}%")
        )
    returns = db.scalars(
        statement.order_by(SaleReturn.created_at.desc(), SaleReturn.id.desc()).limit(limit)
    ).unique().all()
    return [sale_return_to_dict(item) for item in returns]


@router.get("/returns/{return_id}", response_model=SaleReturnRead)
def get_sale_return(return_id: int, db: Session = Depends(get_db)):
    sale_return = load_sale_return(db, return_id)
    if sale_return is None:
        raise HTTPException(status_code=404, detail="Return not found")
    return sale_return_to_dict(sale_return)


@router.get("/{sale_id}/invoice.pdf")
def download_invoice_pdf(sale_id: int, db: Session = Depends(get_db)):
    invoice = invoice_to_dict(load_sale(db, sale_id))
    pdf = invoice_pdf(invoice)
    filename = f"{invoice['invoice_number']}.pdf"
    return StreamingResponse(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{sale_id}/invoice", response_model=InvoiceRead)
def get_invoice(sale_id: int, db: Session = Depends(get_db)):
    return invoice_to_dict(load_sale(db, sale_id))


@router.get("", response_model=list[SaleRead])
def list_sales(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    sales = db.scalars(
        sale_statement().order_by(Sale.created_at.desc(), Sale.id.desc()).limit(limit)
    ).unique().all()
    return [sale_to_dict(sale) for sale in sales]


@router.post("", response_model=SaleRead, status_code=status.HTTP_201_CREATED)
def create_legacy_sale(payload: SaleCreate, db: Session = Depends(get_db)):
    requested = {item.product_id: item.quantity for item in payload.items}
    plans: list[dict] = []
    subtotal = Decimal("0.00")
    for product_id, quantity in requested.items():
        product = db.get(Product, product_id)
        if product is None or not product.active:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        batches = db.scalars(
            select(MedicineBatch)
            .where(
                MedicineBatch.product_id == product_id,
                MedicineBatch.quantity > 0,
                MedicineBatch.status == "active",
                MedicineBatch.expiry_date >= date.today(),
            )
            .order_by(MedicineBatch.expiry_date, MedicineBatch.id)
        ).all()
        if sum(batch.quantity for batch in batches) < quantity:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient eligible stock for product {product.name}",
            )
        remaining = quantity
        for batch in batches:
            allocated = min(batch.quantity, remaining)
            if allocated:
                plans.append(
                    {
                        "product": product,
                        "batch": batch,
                        "quantity": allocated,
                        "line_total": money(product.unit_price * allocated),
                    }
                )
                subtotal += money(product.unit_price * allocated)
                remaining -= allocated
            if remaining == 0:
                break

    sale = Sale(
        invoice_number=f"INV-{date.today():%Y%m%d}-{uuid4().hex[:12].upper()}",
        total_amount=money(subtotal),
        subtotal_amount=money(subtotal),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        tax_rate_percent=Decimal("0.00"),
    )
    db.add(sale)
    db.flush()
    try:
        for allocation in plans:
            batch = allocation["batch"]
            quantity = allocation["quantity"]
            updated_quantity = db.execute(
                update(MedicineBatch)
                .where(
                    MedicineBatch.id == batch.id,
                    MedicineBatch.quantity >= quantity,
                    MedicineBatch.status == "active",
                    MedicineBatch.expiry_date >= date.today(),
                )
                .values(quantity=MedicineBatch.quantity - quantity)
                .returning(MedicineBatch.quantity)
            ).scalar_one_or_none()
            if updated_quantity is None:
                db.rollback()
                raise HTTPException(status_code=409, detail="Stock changed during sale; retry")
            db.add(
                SaleItem(
                    sale_id=sale.id,
                    product_id=allocation["product"].id,
                    batch_id=batch.id,
                    quantity=quantity,
                    unit_price=allocation["product"].unit_price,
                    line_total=allocation["line_total"],
                )
            )
            db.add(
                StockTransaction(
                    product_id=allocation["product"].id,
                    batch_id=batch.id,
                    location_id=batch.location_id,
                    kind="sale",
                    quantity_delta=-quantity,
                    previous_quantity=updated_quantity + quantity,
                    updated_quantity=updated_quantity,
                    reason=f"Sale {sale.invoice_number}",
                )
            )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Sale conflicts with an existing transaction") from error
    return sale_to_dict(load_sale(db, sale.id))


@router.post("/checkout", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
def create_sale(
    payload: SaleCheckout,
    response: Response,
    db: Session = Depends(get_db),
):
    fingerprint = request_fingerprint(payload)
    existing = db.scalar(select(Sale).where(Sale.idempotency_key == payload.idempotency_key))
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different checkout")
        response.status_code = status.HTTP_200_OK
        return invoice_to_dict(load_sale(db, existing.id))

    config = _configured_store(db)
    requested = {item.product_id: item.quantity for item in payload.items}
    products: dict[int, Product] = {}
    plans: list[dict] = []
    subtotal = Decimal("0.00")
    for product_id, quantity in requested.items():
        product = db.get(Product, product_id)
        if product is None or not product.active:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        products[product_id] = product
        batches = db.scalars(
            select(MedicineBatch)
            .where(
                MedicineBatch.product_id == product_id,
                MedicineBatch.quantity > 0,
                MedicineBatch.status == "active",
                MedicineBatch.expiry_date >= date.today(),
            )
            .order_by(MedicineBatch.expiry_date, MedicineBatch.id)
        ).all()
        if sum(batch.quantity for batch in batches) < quantity:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient eligible stock for product {product.name}",
            )
        remaining = quantity
        for batch in batches:
            allocated = min(batch.quantity, remaining)
            if allocated:
                gross = money(product.unit_price * allocated)
                plans.append(
                    {
                        "product": product,
                        "batch": batch,
                        "quantity": allocated,
                        "gross": gross,
                    }
                )
                subtotal += gross
                remaining -= allocated
            if remaining == 0:
                break

    if any(product.requires_prescription for product in products.values()) and (
        not payload.prescription_reference or not payload.pharmacist_reference
    ):
        raise HTTPException(
            status_code=422,
            detail="Prescription-required products need a prescription reference and pharmacist reference",
        )

    subtotal = money(subtotal)
    discount = money(payload.discount_amount)
    if discount > subtotal:
        raise HTTPException(status_code=422, detail="Discount cannot exceed the subtotal")
    taxable_amount = subtotal - discount
    tax = money(taxable_amount * config.tax_rate_percent / Decimal("100"))
    total = money(taxable_amount + tax)
    if total <= 0:
        raise HTTPException(status_code=422, detail="Checkout total must be greater than zero")
    payment_amount = money(payload.payment_amount)
    if payload.payment_method == "cash":
        if payment_amount < total:
            raise HTTPException(status_code=422, detail="Cash received is less than the amount due")
    elif payment_amount != total:
        raise HTTPException(status_code=422, detail="UPI and card payments must match the amount due")

    discount_allocations = allocate_amount(discount, [item["gross"] for item in plans])
    taxable_allocations = [
        item["gross"] - discount_allocations[index]
        for index, item in enumerate(plans)
    ]
    tax_allocations = allocate_amount(tax, taxable_allocations)
    sale = Sale(
        invoice_number=f"INV-{date.today():%Y%m%d}-{uuid4().hex[:12].upper()}",
        total_amount=total,
        subtotal_amount=subtotal,
        discount_amount=discount,
        tax_amount=tax,
        tax_rate_percent=config.tax_rate_percent,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        operator_reference=payload.operator_reference,
        store_name=config.store_name,
        store_phone=config.store_phone,
        store_address=config.store_address,
        currency_code=config.currency_code,
        discount_authorized_by=payload.discount_authorized_by,
        discount_reason=payload.discount_reason,
        prescription_reference=payload.prescription_reference,
        pharmacist_reference=payload.pharmacist_reference,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=fingerprint,
    )
    db.add(sale)
    db.flush()
    try:
        for index, allocation in enumerate(plans):
            batch = allocation["batch"]
            quantity = allocation["quantity"]
            updated_quantity = db.execute(
                update(MedicineBatch)
                .where(
                    MedicineBatch.id == batch.id,
                    MedicineBatch.quantity >= quantity,
                    MedicineBatch.status == "active",
                    MedicineBatch.expiry_date >= date.today(),
                )
                .values(quantity=MedicineBatch.quantity - quantity)
                .returning(MedicineBatch.quantity)
            ).scalar_one_or_none()
            if updated_quantity is None:
                db.rollback()
                raise HTTPException(status_code=409, detail="Stock changed during checkout; retry")

            line_total = money(
                allocation["gross"] - discount_allocations[index] + tax_allocations[index]
            )
            db.add(
                SaleItem(
                    sale_id=sale.id,
                    product_id=allocation["product"].id,
                    batch_id=batch.id,
                    quantity=quantity,
                    unit_price=allocation["product"].unit_price,
                    discount_amount=discount_allocations[index],
                    tax_amount=tax_allocations[index],
                    line_total=line_total,
                )
            )
            db.add(
                StockTransaction(
                    product_id=allocation["product"].id,
                    batch_id=batch.id,
                    location_id=batch.location_id,
                    kind="sale",
                    quantity_delta=-quantity,
                    previous_quantity=updated_quantity + quantity,
                    updated_quantity=updated_quantity,
                    reason=f"Sale {sale.invoice_number}",
                )
            )
        db.add(
            PaymentRecord(
                sale_id=sale.id,
                kind="payment",
                method=payload.payment_method,
                amount=total,
                cash_received=payment_amount if payload.payment_method == "cash" else None,
                change_given=money(payment_amount - total) if payload.payment_method == "cash" else None,
                reference=payload.payment_reference,
                idempotency_key=payload.idempotency_key,
            )
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Checkout conflicts with an existing transaction") from error
    return invoice_to_dict(load_sale(db, sale.id))


def returned_value(sale_item: SaleItem, returned_quantity: int) -> Decimal:
    full_value = money(
        sale_item.unit_price * sale_item.quantity
        - sale_item.discount_amount
        + sale_item.tax_amount
    )
    return money(full_value * returned_quantity / sale_item.quantity)


@router.post("/{sale_id}/returns", response_model=SaleReturnRead, status_code=status.HTTP_201_CREATED)
def create_sale_return(
    sale_id: int,
    payload: SaleReturnCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    fingerprint = request_fingerprint(payload)
    existing = db.scalar(select(SaleReturn).where(SaleReturn.idempotency_key == payload.idempotency_key))
    if existing is not None:
        if existing.request_fingerprint != fingerprint or existing.sale_id != sale_id:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for a different return")
        response.status_code = status.HTTP_200_OK
        return sale_return_to_dict(load_sale_return(db, existing.id))

    sale = db.get(Sale, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    requested_items = []
    for requested in payload.items:
        sale_item = db.execute(
            select(SaleItem)
            .options(joinedload(SaleItem.product), joinedload(SaleItem.batch))
            .where(SaleItem.id == requested.sale_item_id, SaleItem.sale_id == sale_id)
        ).scalar_one_or_none()
        if sale_item is None:
            raise HTTPException(status_code=404, detail="Invoice line not found")
        if requested.restock and (
            sale_item.batch.status != "active" or sale_item.batch.expiry_date < date.today()
        ):
            raise HTTPException(
                status_code=409,
                detail="Expired, damaged, or quarantined stock cannot be restored as saleable",
            )
        requested_items.append((requested, sale_item))

    sale_return = SaleReturn(
        return_number=f"RET-{date.today():%Y%m%d}-{uuid4().hex[:12].upper()}",
        sale_id=sale_id,
        reason=payload.reason,
        refund_method=payload.refund_method,
        refund_amount=Decimal("0.00"),
        operator_reference=payload.operator_reference,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=fingerprint,
    )
    db.add(sale_return)
    db.flush()
    refund_total = Decimal("0.00")
    try:
        for requested, sale_item in requested_items:
            updated_returned_quantity = db.execute(
                update(SaleItem)
                .where(
                    SaleItem.id == sale_item.id,
                    SaleItem.sale_id == sale_id,
                    SaleItem.returned_quantity + requested.quantity <= SaleItem.quantity,
                )
                .values(returned_quantity=SaleItem.returned_quantity + requested.quantity)
                .returning(SaleItem.returned_quantity)
            ).scalar_one_or_none()
            if updated_returned_quantity is None:
                db.rollback()
                raise HTTPException(status_code=409, detail="Return quantity exceeds the unreturned invoice quantity")

            previous_returned_quantity = updated_returned_quantity - requested.quantity
            item_refund = returned_value(sale_item, updated_returned_quantity) - returned_value(
                sale_item,
                previous_returned_quantity,
            )
            item_refund = money(item_refund)
            refund_total += item_refund
            disposition = "quarantined"
            if requested.restock:
                batch = sale_item.batch
                updated_stock = db.execute(
                    update(MedicineBatch)
                    .where(
                        MedicineBatch.id == batch.id,
                        MedicineBatch.status == "active",
                        MedicineBatch.expiry_date >= date.today(),
                    )
                    .values(quantity=MedicineBatch.quantity + requested.quantity)
                    .returning(MedicineBatch.quantity)
                ).scalar_one_or_none()
                if updated_stock is None:
                    db.rollback()
                    raise HTTPException(status_code=409, detail="Batch is no longer eligible for restocking")
                disposition = "restocked"
                db.add(
                    StockTransaction(
                        product_id=sale_item.product_id,
                        batch_id=batch.id,
                        location_id=batch.location_id,
                        kind="adjustment",
                        quantity_delta=requested.quantity,
                        previous_quantity=updated_stock - requested.quantity,
                        updated_quantity=updated_stock,
                        reason=f"Verified return {sale_return.return_number} by {payload.operator_reference}",
                    )
                )
            db.add(
                SaleReturnItem(
                    sale_return_id=sale_return.id,
                    sale_item_id=sale_item.id,
                    quantity=requested.quantity,
                    disposition=disposition,
                    restock_verified_by=requested.restock_verified_by if requested.restock else None,
                    refund_amount=item_refund,
                )
            )

        refund_total = money(refund_total)
        sale_return.refund_amount = refund_total
        db.add(
            PaymentRecord(
                return_id=sale_return.id,
                kind="refund",
                method=payload.refund_method,
                amount=refund_total,
                reference=payload.refund_reference,
                idempotency_key=hashlib.sha256(
                    f"refund:{payload.idempotency_key}".encode("utf-8")
                ).hexdigest(),
            )
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Return conflicts with an existing refund") from error
    return sale_return_to_dict(load_sale_return(db, sale_return.id))


@router.get("/{sale_id}/returns", response_model=list[SaleReturnRead])
def list_sale_returns(sale_id: int, db: Session = Depends(get_db)):
    if db.get(Sale, sale_id) is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    returns = db.scalars(
        select(SaleReturn)
        .options(
            joinedload(SaleReturn.sale),
            joinedload(SaleReturn.items).joinedload(SaleReturnItem.sale_item).joinedload(SaleItem.product),
            joinedload(SaleReturn.items).joinedload(SaleReturnItem.sale_item).joinedload(SaleItem.batch),
        )
        .where(SaleReturn.sale_id == sale_id)
        .order_by(SaleReturn.created_at.desc(), SaleReturn.id.desc())
    ).unique().all()
    return [sale_return_to_dict(item) for item in returns]
