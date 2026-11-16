from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from backend.app.auth import require_owner
from backend.app.db import get_db
from backend.app.models import AccountUser, InventoryLocation, MedicineBatch, Product, ProductCategory
from backend.app.schemas import (
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    InventoryLocationCreate,
    InventoryLocationRead,
    InventoryLocationUpdate,
    ProductCreate,
    ProductInventoryUpdate,
    ProductRead,
)
from backend.app.services.inventory import InventoryOperationError, product_to_dict
from backend.app.services.product_management import build_product
from backend.app.services.store_categories import category_name_key, category_slug

router = APIRouter(tags=["catalog"])


@router.get("/categories", response_model=list[CategoryRead])
def list_categories(db: Session = Depends(get_db)):
    return db.scalars(select(ProductCategory).order_by(ProductCategory.name)).all()


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    _owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    base_slug = category_slug(payload.name)
    slug = base_slug
    suffix = 2
    while db.scalar(select(ProductCategory.id).where(ProductCategory.slug == slug)) is not None:
        slug = f"{base_slug[:70]}-{suffix}"
        suffix += 1
    category = ProductCategory(
        name=payload.name,
        name_key=category_name_key(payload.name),
        slug=slug,
        description=payload.description,
        image_url=payload.image_url,
        active=payload.active,
    )
    db.add(category)
    try:
        db.commit()
        db.refresh(category)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A category with this name already exists") from error
    return category


@router.patch("/categories/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    _owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    category = db.get(ProductCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        category.name = changes["name"]
        category.name_key = category_name_key(changes["name"])
    for field in ("description", "image_url", "active"):
        if field in changes:
            setattr(category, field, changes[field])
    try:
        db.commit()
        db.refresh(category)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A category with this name already exists") from error
    return category


@router.get("/locations", response_model=list[InventoryLocationRead])
def list_locations(db: Session = Depends(get_db)):
    return db.scalars(select(InventoryLocation).order_by(InventoryLocation.code)).all()


@router.post("/locations", response_model=InventoryLocationRead, status_code=status.HTTP_201_CREATED)
def create_location(payload: InventoryLocationCreate, db: Session = Depends(get_db)):
    location = InventoryLocation(code=payload.code, name=payload.name)
    db.add(location)
    try:
        db.commit()
        db.refresh(location)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="An inventory location with this code already exists") from error
    return location


@router.put("/locations/{location_id}", response_model=InventoryLocationRead)
def update_location(location_id: int, payload: InventoryLocationUpdate, db: Session = Depends(get_db)):
    location = db.get(InventoryLocation, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Inventory location not found")
    if payload.code != location.code and db.scalar(
        select(MedicineBatch.id).where(MedicineBatch.location_id == location.id).limit(1)
    ) is not None:
        raise HTTPException(
            status_code=409,
            detail="A location code cannot be changed after stock history exists; update its name instead",
        )
    location.code = payload.code
    location.name = payload.name
    try:
        db.commit()
        db.refresh(location)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="An inventory location with this code already exists") from error
    return location


@router.get("/products", response_model=list[ProductRead])
def list_products(
    q: str | None = Query(default=None, max_length=160),
    barcode: str | None = Query(default=None, max_length=64),
    location_code: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    statement = select(Product).options(joinedload(Product.category)).where(Product.active.is_(True))
    if q and q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Product.name.ilike(term),
                Product.generic_name.ilike(term),
                Product.barcode.ilike(term),
                Product.category.has(ProductCategory.name.ilike(term)),
            )
        )
    if barcode:
        statement = statement.where(Product.barcode == barcode.strip())
    if location_code:
        location = db.scalar(
            select(InventoryLocation).where(InventoryLocation.code == location_code.strip().upper())
        )
        if location is None:
            raise HTTPException(status_code=404, detail="Inventory location not found")
        statement = statement.where(Product.batches.any(MedicineBatch.location_id == location.id))
    products = db.scalars(statement.order_by(Product.name).limit(limit)).unique().all()
    return [product_to_dict(db, product) for product in products]


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    _owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        product = build_product(db, payload)
        db.commit()
        db.refresh(product)
    except InventoryOperationError as error:
        db.rollback()
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A product with this barcode or category already exists") from error
    return product_to_dict(db, product)


@router.get("/products/{product_id}", response_model=ProductRead)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.scalar(
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.id == product_id, Product.active.is_(True))
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_to_dict(db, product)


@router.patch("/products/{product_id}", response_model=ProductRead)
def update_product_inventory(
    product_id: int,
    payload: ProductInventoryUpdate,
    _owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if product is None or not product.active:
        raise HTTPException(status_code=404, detail="Product not found")
    if payload.min_threshold is not None:
        product.min_threshold = payload.min_threshold
    if payload.requires_prescription is not None:
        product.requires_prescription = payload.requires_prescription
    for field in (
        "manufacturer",
        "image_url",
        "description",
        "ingredients_strengths",
        "common_uses",
        "directions",
        "warnings",
        "product_information_verified",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(product, field, value)
    if product.product_information_verified and not any(
        (
            product.manufacturer,
            product.description,
            product.ingredients_strengths,
            product.common_uses,
            product.directions,
            product.warnings,
        )
    ):
        raise HTTPException(status_code=422, detail="Verified product information must include at least one product detail")
    db.commit()
    return product_to_dict(db, product)
