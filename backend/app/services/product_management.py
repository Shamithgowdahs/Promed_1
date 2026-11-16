from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import Product, ProductCategory
from backend.app.schemas import BatchReceive, ProductCreate, ProductUpdate
from backend.app.services.inventory import (
    InventoryOperationError,
    product_to_dict,
    record_stock_receipt,
    resolve_category,
)


def product_management_to_dict(db: Session, product: Product) -> dict:
    return {
        **product_to_dict(db, product),
        "unit_of_measure": product.unit_of_measure,
        "active": product.active,
        "manufacturer": product.manufacturer,
        "image_url": product.image_url,
        "description": product.description,
        "ingredients_strengths": product.ingredients_strengths,
        "common_uses": product.common_uses,
        "directions": product.directions,
        "warnings": product.warnings,
        "product_information_verified": product.product_information_verified,
    }


def product_details_are_valid(payload) -> bool:
    return not payload.product_information_verified or any(
        (
            payload.manufacturer,
            payload.description,
            payload.ingredients_strengths,
            payload.common_uses,
            payload.directions,
            payload.warnings,
        )
    )


def build_product(db: Session, payload: ProductCreate) -> Product:
    try:
        category = resolve_category(db, payload.category_id, payload.category_name)
    except ValueError as error:
        raise InventoryOperationError(404, str(error)) from error
    if not product_details_are_valid(payload):
        raise InventoryOperationError(
            422,
            "Verified product information must include at least one product detail",
        )
    if payload.initial_stock and not payload.active:
        raise InventoryOperationError(422, "Initial stock can only be received for an active product")

    product = Product(
        name=payload.name,
        generic_name=payload.generic_name,
        barcode=payload.barcode,
        category=category,
        min_threshold=payload.min_threshold,
        unit_price=payload.unit_price,
        unit_of_measure=payload.unit_of_measure,
        requires_prescription=payload.requires_prescription,
        active=payload.active,
        manufacturer=payload.manufacturer,
        image_url=payload.image_url,
        description=payload.description,
        ingredients_strengths=payload.ingredients_strengths,
        common_uses=payload.common_uses,
        directions=payload.directions,
        warnings=payload.warnings,
        product_information_verified=payload.product_information_verified,
    )
    db.add(product)
    db.flush()
    if payload.initial_stock:
        batch_payload = BatchReceive(
            product_id=product.id,
            **payload.initial_stock.model_dump(),
        )
        record_stock_receipt(db, product, batch_payload)
    return product


def update_product(db: Session, product: Product, payload: ProductUpdate) -> Product:
    changes = payload.model_dump(exclude_unset=True)
    if "category_id" in changes:
        category_id = changes["category_id"]
        if category_id is None:
            raise InventoryOperationError(422, "A product must have a category")
        category = db.get(ProductCategory, category_id)
        if category is None or not category.active:
            raise InventoryOperationError(404, "Active category not found")
        product.category = category

    for field, value in changes.items():
        if field != "category_id":
            setattr(product, field, value)

    if "active" in changes and product.active and not product.category.active:
        raise InventoryOperationError(409, "Activate the product category before activating this product")
    if not product_details_are_valid(product):
        raise InventoryOperationError(
            422,
            "Verified product information must include at least one product detail",
        )
    return product


def get_managed_products(
    db: Session,
    q: str | None,
    category_id: int | None,
    active: bool | None,
    limit: int,
) -> list[Product]:
    statement = select(Product).options(selectinload(Product.category))
    if q and q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(
            Product.name.ilike(term)
            | Product.generic_name.ilike(term)
            | Product.barcode.ilike(term)
            | Product.manufacturer.ilike(term)
            | Product.category.has(ProductCategory.name.ilike(term))
        )
    if category_id is not None:
        statement = statement.where(Product.category_id == category_id)
    if active is not None:
        statement = statement.where(Product.active.is_(active))
    return list(db.scalars(statement.order_by(Product.name, Product.id).limit(limit)).unique().all())
