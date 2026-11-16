from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.app.db import get_db
from backend.app.auth import require_staff
from backend.app.models import (
    AccountUser,
    Order,
    OrderItem,
    OrderStatusEvent,
    PrescriptionVerification,
    Product,
)
from backend.app.schemas import (
    OrderCreate,
    OrderRead,
    OrderStatusUpdate,
    OrderWorkflowHistoryRead,
    OrderWorkflowRead,
    OrderWorkflowStatus,
    OrderWorkflowStatusUpdate,
    PrescriptionVerificationCreate,
)
from backend.app.services.inventory import eligible_stock_quantity

router = APIRouter(prefix="/orders", tags=["orders"])

ALLOWED_TRANSITIONS = {
    "RECEIVED": {"PHARMACIST_REVIEW", "CANCELLED"},
    "PHARMACIST_REVIEW": {"ACCEPTED", "REJECTED", "CANCELLED"},
    "ACCEPTED": {"PREPARING", "CANCELLED"},
    "PREPARING": {"READY_FOR_PICKUP", "OUT_FOR_DELIVERY", "CANCELLED"},
    "READY_FOR_PICKUP": {"COMPLETED", "CANCELLED"},
    "OUT_FOR_DELIVERY": {"COMPLETED"},
    "COMPLETED": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
}


def order_to_dict(order: Order) -> dict:
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "created_at": order.created_at,
        "items": [
            {"product_id": item.product_id, "product_name": item.product.name, "quantity": item.quantity}
            for item in order.items
        ],
    }


def order_workflow_statement():
    return select(Order).options(
        joinedload(Order.items).joinedload(OrderItem.product),
        joinedload(Order.prescription_verifications),
    )


def workflow_status_for(order: Order) -> tuple[str, str | None]:
    if not any(item.product.requires_prescription for item in order.items):
        return "not_required", None
    latest = max(
        order.prescription_verifications,
        key=lambda item: (item.created_at, item.id),
        default=None,
    )
    if latest is None:
        return "pending", None
    return latest.status, latest.prescription_reference


def order_workflow_to_dict(order: Order, include_prescription_details: bool = True) -> dict:
    prescription_status, prescription_reference = workflow_status_for(order)
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.workflow_status,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "fulfillment_method": order.fulfillment_method,
        "delivery_address": order.delivery_address,
        "notes": order.notes,
        "operator_reference": order.operator_reference,
        "prescription_status": prescription_status if include_prescription_details else (
            "not_required" if prescription_status == "not_required" else "pending"
        ),
        "prescription_reference": prescription_reference if include_prescription_details else None,
        "created_at": order.created_at,
        "total_amount": order.total_amount,
        "items": [
            {
                "product_id": item.product_id,
                "product_name": item.product.name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "requires_prescription": item.product.requires_prescription,
            }
            for item in order.items
        ],
    }


def order_history_to_dict(order: Order, include_prescription_details: bool = True) -> dict:
    return {
        "order": order_workflow_to_dict(order, include_prescription_details),
        "status_events": [
            {
                "id": event.id,
                "previous_status": event.previous_status,
                "updated_status": event.updated_status,
                "operator_reference": event.operator_reference,
                "note": event.note,
                "created_at": event.created_at,
            }
            for event in sorted(order.status_events, key=lambda event: (event.created_at, event.id))
        ],
        "prescription_events": [
            {
                "id": event.id,
                "status": event.status,
                "prescription_reference": event.prescription_reference,
                "pharmacist_reference": event.pharmacist_reference,
                "note": event.note,
                "created_at": event.created_at,
            }
            for event in sorted(
                order.prescription_verifications,
                key=lambda event: (event.created_at, event.id),
            )
        ] if include_prescription_details else [],
    }


def load_order(db: Session, order_id: int) -> Order:
    order = db.execute(order_workflow_statement().where(Order.id == order_id)).unique().scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def create_order_record(db: Session, payload: OrderCreate) -> Order:
    order = Order(
        order_number=f"ORD-{uuid4().hex[:12].upper()}",
        status="pending",
        workflow_status="RECEIVED",
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        fulfillment_method=payload.fulfillment_method,
        delivery_address=payload.delivery_address,
        notes=payload.notes,
        operator_reference=payload.operator_reference,
    )
    db.add(order)
    db.flush()
    requires_prescription = False
    total_amount = 0
    for item in payload.items:
        product = db.get(Product, item.product_id)
        if product is None or not product.active:
            db.rollback()
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        requires_prescription = requires_prescription or product.requires_prescription
        total_amount += product.unit_price * item.quantity
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=item.quantity,
                unit_price=product.unit_price,
            )
        )
    order.total_amount = total_amount
    db.add(
        OrderStatusEvent(
            order_id=order.id,
            previous_status=None,
            updated_status="RECEIVED",
            operator_reference=payload.operator_reference,
            note="Order created",
        )
    )
    if requires_prescription:
        db.add(
            PrescriptionVerification(
                order_id=order.id,
                status="pending",
                prescription_reference=payload.prescription_reference,
                pharmacist_reference=None,
                note="Awaiting pharmacist review",
            )
        )
    db.commit()
    return load_order(db, order.id)


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    order = create_order_record(db, payload)
    return order_to_dict(order)


@router.post("/workflow", response_model=OrderWorkflowRead, status_code=status.HTTP_201_CREATED)
def create_managed_order(payload: OrderCreate, db: Session = Depends(get_db)):
    return order_workflow_to_dict(create_order_record(db, payload))


@router.get("", response_model=list[OrderRead])
def list_orders(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    orders = db.scalars(
        select(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
    ).unique().all()
    return [order_to_dict(order) for order in orders]


@router.get("/workflow", response_model=list[OrderWorkflowRead])
def list_managed_orders(
    status_filter: OrderWorkflowStatus | None = Query(default=None, alias="status"),
    customer_phone: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    staff: AccountUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    statement = order_workflow_statement()
    if status_filter:
        statement = statement.where(Order.workflow_status == status_filter)
    if customer_phone and customer_phone.strip():
        statement = statement.where(Order.customer_phone == customer_phone.strip())
    orders = db.scalars(statement.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit)).unique().all()
    return [order_workflow_to_dict(order, staff.role != "operator") for order in orders]


@router.get("/{order_id}/workflow", response_model=OrderWorkflowHistoryRead)
def get_order_workflow(
    order_id: int,
    staff: AccountUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    order = db.execute(
        order_workflow_statement()
        .options(joinedload(Order.status_events))
        .execution_options(populate_existing=True)
        .where(Order.id == order_id)
    ).unique().scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order_history_to_dict(order, staff.role != "operator")


@router.patch("/{order_id}/prescription", response_model=OrderWorkflowHistoryRead)
def verify_order_prescription(
    payload: PrescriptionVerificationCreate,
    order_id: int = Path(gt=0),
    staff: AccountUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    if staff.role not in {"owner", "pharmacist"}:
        raise HTTPException(status_code=403, detail="A pharmacist or owner must verify prescriptions")
    order = load_order(db, order_id)
    if not any(item.product.requires_prescription for item in order.items):
        raise HTTPException(status_code=409, detail="This order does not contain a prescription-required product")
    if order.workflow_status != "PHARMACIST_REVIEW":
        raise HTTPException(status_code=409, detail="Move the order to pharmacist review before verifying a prescription")
    _latest_status, latest_reference = workflow_status_for(order)
    reference = payload.prescription_reference or latest_reference
    if payload.status == "verified" and not reference:
        raise HTTPException(status_code=422, detail="A prescription reference is required before verification")
    event = PrescriptionVerification(
        order_id=order.id,
        status=payload.status,
        prescription_reference=reference,
        pharmacist_reference=payload.pharmacist_reference,
        note=payload.note,
    )
    db.add(event)
    db.commit()
    return get_order_workflow(order.id, staff=staff, db=db)


@router.patch("/{order_id}/workflow", response_model=OrderWorkflowRead)
def update_order_workflow(
    payload: OrderWorkflowStatusUpdate,
    order_id: int = Path(gt=0),
    staff: AccountUser = Depends(require_staff),
    db: Session = Depends(get_db),
):
    order = load_order(db, order_id)
    previous_status = order.workflow_status
    if staff.role == "pharmacist" and payload.status not in {
        "PHARMACIST_REVIEW",
        "ACCEPTED",
        "REJECTED",
        "CANCELLED",
    }:
        raise HTTPException(status_code=403, detail="Pharmacist accounts cannot manage fulfilment statuses")
    if staff.role == "operator" and payload.status not in {
        "PREPARING",
        "READY_FOR_PICKUP",
        "OUT_FOR_DELIVERY",
        "COMPLETED",
        "CANCELLED",
    }:
        raise HTTPException(status_code=403, detail="Operator accounts cannot review or accept orders")
    if payload.status not in ALLOWED_TRANSITIONS[previous_status]:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid order status transition: {previous_status} to {payload.status}",
        )
    if payload.status == "READY_FOR_PICKUP" and order.fulfillment_method != "pickup":
        raise HTTPException(status_code=409, detail="Home-delivery orders cannot be marked ready for pickup")
    if payload.status == "OUT_FOR_DELIVERY" and order.fulfillment_method != "delivery":
        raise HTTPException(status_code=409, detail="Pickup orders cannot be sent out for delivery")
    if payload.status == "ACCEPTED" and any(
        item.product.requires_prescription for item in order.items
    ):
        prescription_status, _reference = workflow_status_for(order)
        if prescription_status != "verified":
            raise HTTPException(status_code=409, detail="A pharmacist must verify the prescription before acceptance")
    if payload.status == "ACCEPTED" and order.customer_id is not None:
        for item in order.items:
            if item.quantity > eligible_stock_quantity(db, item.product_id):
                raise HTTPException(
                    status_code=409,
                    detail=f"Order cannot be accepted: {item.product.name} no longer has enough eligible stock",
                )

    order.workflow_status = payload.status
    if payload.status == "COMPLETED":
        order.status = "fulfilled"
    elif payload.status in ("REJECTED", "CANCELLED"):
        order.status = "cancelled"
    db.add(
        OrderStatusEvent(
            order_id=order.id,
            previous_status=previous_status,
            updated_status=payload.status,
            operator_reference=payload.operator_reference,
            note=payload.note,
        )
    )
    db.commit()
    return order_workflow_to_dict(load_order(db, order.id), staff.role != "operator")


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: int = Path(gt=0), db: Session = Depends(get_db)):
    order = db.scalar(
        select(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .where(Order.id == order_id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order_to_dict(order)


@router.patch("/{order_id}", response_model=OrderRead)
def update_order_status(
    payload: OrderStatusUpdate,
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    order = db.scalar(
        select(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .where(Order.id == order_id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "pending" and payload.status != order.status:
        raise HTTPException(status_code=409, detail="Only pending orders can change status")
    previous_workflow_status = order.workflow_status
    order.status = payload.status
    if payload.status == "fulfilled":
        order.workflow_status = "COMPLETED"
    elif payload.status == "cancelled":
        order.workflow_status = "CANCELLED"
    if previous_workflow_status != order.workflow_status:
        db.add(
            OrderStatusEvent(
                order_id=order.id,
                previous_status=previous_workflow_status,
                updated_status=order.workflow_status,
                note="Updated through the legacy order status endpoint",
            )
        )
    db.commit()
    db.refresh(order)
    return order_to_dict(order)
