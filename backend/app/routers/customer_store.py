import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, joinedload

from backend.app.auth import (
    CUSTOMER_SESSION_COOKIE,
    STAFF_SESSION_COOKIE,
    clear_session_cookie,
    hash_password,
    issue_session,
    require_customer,
    require_owner,
    require_staff,
    set_session_cookie,
    verify_password,
)
from backend.app.db import get_db
from backend.app.models import (
    AccountUser,
    MedicineBatch,
    Order,
    OrderItem,
    OrderStatusEvent,
    PrescriptionVerification,
    Product,
    ProductCategory,
    UserSession,
)
from backend.app.schemas import (
    AccountLogin,
    AccountRead,
    CustomerOrderCreate,
    CustomerOrderRead,
    CustomerProductRead,
    CustomerProfileUpdate,
    CustomerRegister,
    StaffAccountCreate,
)
from backend.app.services.inventory import eligible_stock_quantity
from backend.app.services.store_categories import STORE_CATEGORIES, normalized_category_name

catalog_router = APIRouter(prefix="/store/catalog", tags=["customer catalog"])
auth_router = APIRouter(prefix="/auth", tags=["authentication"])
customer_router = APIRouter(prefix="/customer", tags=["customer orders"])

def _normalized_category_name(value: str) -> str:
    return normalized_category_name(value)


def account_to_dict(user: AccountUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "phone": user.phone,
        "role": user.role,
    }


def customer_order_statement():
    return select(Order).options(
        joinedload(Order.items).joinedload(OrderItem.product),
        joinedload(Order.status_events),
    )


def customer_order_to_dict(order: Order) -> dict:
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.workflow_status,
        "created_at": order.created_at,
        "fulfillment_method": order.fulfillment_method,
        "delivery_address": order.delivery_address,
        "total_amount": order.total_amount,
        "requires_pharmacist_review": any(item.product.requires_prescription for item in order.items),
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
        "status_timeline": [
            {"status": event.updated_status, "created_at": event.created_at}
            for event in sorted(order.status_events, key=lambda event: (event.created_at, event.id))
        ],
    }


def _session_from_cookie(db: Session, request: Request, cookie_name: str, session_type: str) -> UserSession | None:
    raw_token = request.cookies.get(cookie_name)
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode("ascii", errors="ignore")).hexdigest()
    return db.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.session_type == session_type,
            UserSession.revoked_at.is_(None),
        )
    )


@catalog_router.get("/categories")
def list_store_categories(db: Session = Depends(get_db)):
    database_categories = db.scalars(select(ProductCategory).order_by(ProductCategory.name)).all()
    categories_by_slug = {category.slug: category for category in database_categories}
    results = []
    matched_category_ids = set()

    for store_category in STORE_CATEGORIES:
        category = categories_by_slug.get(store_category["slug"])
        if category is None:
            aliases = {
                _normalized_category_name(name)
                for name in (store_category["name"], *store_category["aliases"])
            }
            category = next(
                (item for item in database_categories if _normalized_category_name(item.name) in aliases),
                None,
            )
        if category is not None:
            matched_category_ids.add(category.id)
        results.append(
            {
                "id": category.id if category else None,
                "database_category_ids": [category.id] if category else [],
                "slug": store_category["slug"],
                "name": category.name if category else store_category["name"],
                "description": (
                    category.description if category and category.description is not None
                    else store_category["description"]
                ),
                "image_url": category.image_url if category and category.image_url else store_category["image_url"],
                "active": category.active if category else True,
                "category_type": "store",
            }
        )

    active_categories = db.scalars(
        select(ProductCategory)
        .join(Product, Product.category_id == ProductCategory.id)
        .where(Product.active.is_(True), ProductCategory.active.is_(True))
        .distinct()
        .order_by(ProductCategory.name)
    ).all()
    for category in active_categories:
        if category.id in matched_category_ids:
            continue
        results.append(
            {
                "id": category.id,
                "database_category_ids": [category.id],
                "slug": f"category-{category.id}",
                "name": category.name,
                "description": "Additional category from active product records.",
                "image_url": category.image_url,
                "active": category.active,
                "category_type": "custom",
            }
        )
    return results


@catalog_router.get("/status")
def get_store_catalog_status(db: Session = Depends(get_db)):
    active_product_count = db.scalar(
        select(func.count(Product.id)).where(Product.active.is_(True))
    ) or 0
    eligible_product_count = db.scalar(
        select(func.count(func.distinct(MedicineBatch.product_id)))
        .join(Product, Product.id == MedicineBatch.product_id)
        .where(
            Product.active.is_(True),
            MedicineBatch.status == "active",
            MedicineBatch.expiry_date >= date.today(),
            MedicineBatch.quantity > 0,
        )
    ) or 0
    category_record_count = db.scalar(select(func.count(ProductCategory.id))) or 0
    return {
        "active_product_count": int(active_product_count),
        "eligible_product_count": int(eligible_product_count),
        "category_record_count": int(category_record_count),
    }


@catalog_router.get("/products", response_model=list[CustomerProductRead])
def list_store_products(
    q: str | None = Query(default=None, max_length=160),
    barcode: str | None = Query(default=None, max_length=64),
    category_id: int | None = Query(default=None, gt=0),
    category: str | None = Query(default=None, max_length=80),
    available: bool | None = None,
    sort: Literal["name-asc", "name-desc", "price-asc", "price-desc"] = "name-asc",
    limit: int = Query(default=200, ge=1, le=200),
    db: Session = Depends(get_db),
):
    eligible_stock = (
        select(MedicineBatch.product_id, func.sum(MedicineBatch.quantity).label("quantity"))
        .where(
            MedicineBatch.status == "active",
            MedicineBatch.expiry_date >= date.today(),
            MedicineBatch.quantity > 0,
        )
        .group_by(MedicineBatch.product_id)
        .subquery()
    )
    statement = (
        select(Product, ProductCategory.name, func.coalesce(eligible_stock.c.quantity, 0).label("quantity"))
        .join(ProductCategory, Product.category_id == ProductCategory.id)
        .outerjoin(eligible_stock, eligible_stock.c.product_id == Product.id)
        .where(Product.active.is_(True), ProductCategory.active.is_(True))
    )
    if q and q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Product.name.ilike(term),
                Product.generic_name.ilike(term),
                Product.barcode.ilike(term),
                Product.manufacturer.ilike(term),
                ProductCategory.name.ilike(term),
            )
        )
    if barcode and barcode.strip():
        statement = statement.where(Product.barcode == barcode.strip())
    if category is not None:
        if category_id is not None:
            raise HTTPException(status_code=422, detail="Provide either category or category_id, not both")
        requested_category = category.strip().casefold()
        matching_store_category = next(
            (item for item in STORE_CATEGORIES if item["slug"] == requested_category),
            None,
        )
        if matching_store_category is not None:
            aliases = {
                _normalized_category_name(name)
                for name in (matching_store_category["name"], *matching_store_category["aliases"])
            }
            matching_category_ids = [
                item.id
                for item in db.scalars(select(ProductCategory)).all()
                if item.slug == requested_category or _normalized_category_name(item.name) in aliases
            ]
            statement = statement.where(Product.category_id.in_(matching_category_ids))
        elif db.scalar(select(ProductCategory.id).where(ProductCategory.slug == requested_category)) is not None:
            statement = statement.where(
                Product.category_id.in_(
                    select(ProductCategory.id).where(ProductCategory.slug == requested_category)
                )
            )
        elif requested_category.startswith("category-") and requested_category[9:].isdigit():
            statement = statement.where(Product.category_id == int(requested_category[9:]))
        elif requested_category.isdigit():
            statement = statement.where(Product.category_id == int(requested_category))
        else:
            raise HTTPException(status_code=422, detail="Unknown store category")
    if category_id is not None:
        statement = statement.where(Product.category_id == category_id)
    if available is True:
        statement = statement.where(func.coalesce(eligible_stock.c.quantity, 0) > 0)
    elif available is False:
        statement = statement.where(func.coalesce(eligible_stock.c.quantity, 0) <= 0)

    ordering = {
        "name-asc": (Product.name.asc(),),
        "name-desc": (Product.name.desc(),),
        "price-asc": (Product.unit_price.asc(), Product.name.asc()),
        "price-desc": (Product.unit_price.desc(), Product.name.asc()),
    }[sort]
    products = db.execute(statement.order_by(*ordering).limit(limit)).all()
    return [
        {
            "id": product.id,
            "name": product.name,
            "category_id": product.category_id,
            "category_name": category_name,
            "unit_of_measure": product.unit_of_measure,
            "manufacturer": product.manufacturer,
            "image_url": product.image_url,
            "unit_price": product.unit_price,
            "available_quantity": int(quantity or 0),
            "availability_status": "available" if quantity else "unavailable",
            "requires_prescription": product.requires_prescription,
            "description": product.description,
            "ingredients_strengths": product.ingredients_strengths,
            "common_uses": product.common_uses,
            "directions": product.directions,
            "warnings": product.warnings,
            "product_information_verified": product.product_information_verified,
        }
        for product, category_name, quantity in products
    ]


@auth_router.post("/customer/register", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def register_customer(
    payload: CustomerRegister,
    response: Response,
    db: Session = Depends(get_db),
):
    user = AccountUser(
        email=payload.email,
        display_name=payload.display_name,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role="customer",
    )
    db.add(user)
    db.flush()
    token = issue_session(db, user)
    db.commit()
    db.refresh(user)
    set_session_cookie(response, token, "customer")
    return account_to_dict(user)


@auth_router.post("/customer/login", response_model=AccountRead)
def customer_login(
    payload: AccountLogin,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.scalar(select(AccountUser).where(AccountUser.email == payload.email))
    if user is None or user.role != "customer" or not user.active or not verify_password(
        payload.password,
        user.password_hash if user else None,
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = issue_session(db, user)
    db.commit()
    set_session_cookie(response, token, "customer")
    return account_to_dict(user)


@auth_router.get("/customer/me", response_model=AccountRead | None)
def customer_profile(request: Request, db: Session = Depends(get_db)):
    session = _session_from_cookie(db, request, CUSTOMER_SESSION_COOKIE, "customer")
    if session is None or not session.user.active or session.user.role != "customer":
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    return account_to_dict(session.user)


@auth_router.patch("/customer/me", response_model=AccountRead)
def update_customer_profile(
    payload: CustomerProfileUpdate,
    user: AccountUser = Depends(require_customer),
    db: Session = Depends(get_db),
):
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.phone is not None:
        user.phone = payload.phone
    db.commit()
    db.refresh(user)
    return account_to_dict(user)


@auth_router.post("/customer/logout", status_code=status.HTTP_204_NO_CONTENT)
def customer_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session = _session_from_cookie(db, request, CUSTOMER_SESSION_COOKIE, "customer")
    if session is not None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    clear_session_cookie(response, "customer")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@auth_router.post("/staff/login", response_model=AccountRead)
def staff_login(
    payload: AccountLogin,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.scalar(select(AccountUser).where(AccountUser.email == payload.email))
    if user is None or user.role == "customer" or not user.active or not verify_password(
        payload.password,
        user.password_hash if user else None,
    ):
        raise HTTPException(status_code=401, detail="Invalid staff credentials")
    token = issue_session(db, user)
    db.commit()
    set_session_cookie(response, token, "staff")
    return account_to_dict(user)


@auth_router.get("/staff/me", response_model=AccountRead | None)
def staff_profile(request: Request, db: Session = Depends(get_db)):
    session = _session_from_cookie(db, request, STAFF_SESSION_COOKIE, "staff")
    if session is None or not session.user.active or session.user.role == "customer":
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    return account_to_dict(session.user)


@auth_router.post("/staff/logout", status_code=status.HTTP_204_NO_CONTENT)
def staff_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session = _session_from_cookie(db, request, STAFF_SESSION_COOKIE, "staff")
    if session is not None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    clear_session_cookie(response, "staff")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@auth_router.post("/staff/users", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_staff_account(
    payload: StaffAccountCreate,
    owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    user = AccountUser(
        email=payload.email,
        display_name=payload.display_name,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return account_to_dict(user)


@customer_router.post("/orders", response_model=CustomerOrderRead, status_code=status.HTTP_201_CREATED)
def create_customer_order(
    payload: CustomerOrderCreate,
    user: AccountUser = Depends(require_customer),
    db: Session = Depends(get_db),
):
    if not user.phone:
        raise HTTPException(status_code=422, detail="Add a contact phone number to your account before checkout")

    fingerprint_payload = {
        "items": [item.model_dump() for item in payload.items],
        "fulfillment_method": payload.fulfillment_method,
        "delivery_address": payload.delivery_address,
        "customer_id": user.id,
        "customer_phone": user.phone,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    db.execute(text("BEGIN IMMEDIATE"))
    existing = db.scalar(select(Order).where(Order.idempotency_key == payload.idempotency_key))
    if existing is not None:
        if existing.customer_id != user.id or existing.request_fingerprint != fingerprint:
            db.rollback()
            raise HTTPException(status_code=409, detail="This order submission key was already used")
        order = db.execute(
            customer_order_statement().where(Order.id == existing.id, Order.customer_id == user.id)
        ).unique().scalar_one()
        db.commit()
        return customer_order_to_dict(order)

    products: list[tuple[Product, int]] = []
    total = Decimal("0.00")
    needs_review = False
    for item in payload.items:
        product = db.get(Product, item.product_id)
        if product is None or not product.active:
            db.rollback()
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} is unavailable")
        available_quantity = eligible_stock_quantity(db, product.id)
        if item.quantity > available_quantity:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Only {available_quantity} eligible units of {product.name} are currently available",
            )
        products.append((product, item.quantity))
        total += product.unit_price * item.quantity
        needs_review = needs_review or product.requires_prescription

    total = total.quantize(Decimal("0.01"))
    initial_status = "PHARMACIST_REVIEW" if needs_review else "RECEIVED"
    order = Order(
        order_number=f"WEB-{uuid4().hex[:12].upper()}",
        status="pending",
        workflow_status=initial_status,
        customer_id=user.id,
        customer_name=user.display_name,
        customer_phone=user.phone,
        fulfillment_method=payload.fulfillment_method,
        delivery_address=payload.delivery_address,
        total_amount=total,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=fingerprint,
    )
    db.add(order)
    db.flush()
    for product, quantity in products:
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=product.unit_price,
            )
        )
    db.add(
        OrderStatusEvent(
            order_id=order.id,
            previous_status=None,
            updated_status=initial_status,
            note=(
                "Prescription-required item; pharmacist review required"
                if needs_review
                else "Customer order received"
            ),
        )
    )
    if needs_review:
        db.add(
            PrescriptionVerification(
                order_id=order.id,
                status="pending",
                pharmacist_reference=None,
                prescription_reference=None,
                note="Awaiting pharmacist review; do not submit prescription documents through this preview",
            )
        )
    db.commit()
    order = db.execute(
        customer_order_statement().where(Order.id == order.id, Order.customer_id == user.id)
    ).unique().scalar_one()
    return customer_order_to_dict(order)


@customer_router.get("/orders", response_model=list[CustomerOrderRead])
def list_customer_orders(
    user: AccountUser = Depends(require_customer),
    db: Session = Depends(get_db),
):
    orders = db.scalars(
        customer_order_statement()
        .where(Order.customer_id == user.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(100)
    ).unique().all()
    return [customer_order_to_dict(order) for order in orders]


@customer_router.get("/orders/by-number/{order_number}", response_model=CustomerOrderRead)
def track_customer_order(
    order_number: str = Path(min_length=1, max_length=40),
    user: AccountUser = Depends(require_customer),
    db: Session = Depends(get_db),
):
    order = db.execute(
        customer_order_statement().where(
            Order.order_number == order_number,
            Order.customer_id == user.id,
        )
    ).unique().scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return customer_order_to_dict(order)


@customer_router.get("/orders/{order_id}", response_model=CustomerOrderRead)
def get_customer_order(
    order_id: int = Path(gt=0),
    user: AccountUser = Depends(require_customer),
    db: Session = Depends(get_db),
):
    order = db.execute(
        customer_order_statement().where(Order.id == order_id, Order.customer_id == user.id)
    ).unique().scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return customer_order_to_dict(order)


@customer_router.post("/orders/{order_id}/cancel", response_model=CustomerOrderRead)
def cancel_customer_order(
    order_id: int = Path(gt=0),
    user: AccountUser = Depends(require_customer),
    db: Session = Depends(get_db),
):
    order = db.execute(
        customer_order_statement().where(Order.id == order_id, Order.customer_id == user.id)
    ).unique().scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.workflow_status not in {"RECEIVED", "PHARMACIST_REVIEW"}:
        raise HTTPException(status_code=409, detail="This order can no longer be cancelled online")
    previous_status = order.workflow_status
    order.workflow_status = "CANCELLED"
    order.status = "cancelled"
    db.add(
        OrderStatusEvent(
            order_id=order.id,
            previous_status=previous_status,
            updated_status="CANCELLED",
            note="Cancelled by customer",
        )
    )
    db.commit()
    order = db.execute(
        customer_order_statement().where(Order.id == order.id, Order.customer_id == user.id)
    ).unique().scalar_one()
    return customer_order_to_dict(order)
