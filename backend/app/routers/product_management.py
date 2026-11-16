from io import BytesIO
from pathlib import Path
from uuid import uuid4
import warnings

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from backend.app.auth import require_owner
from backend.app.db import get_db
from backend.app.models import AccountUser, Product
from backend.app.schemas import ProductCreate, ProductManagementRead, ProductUpdate
from backend.app.services.inventory import InventoryOperationError
from backend.app.services.product_management import (
    build_product,
    get_managed_products,
    product_management_to_dict,
    update_product,
)

router = APIRouter(prefix="/management", tags=["product management"])

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_CONTENT_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
PRODUCT_IMAGE_ROOT = Path(__file__).resolve().parents[3] / "assets" / "products"


@router.get("/products", response_model=list[ProductManagementRead])
def list_managed_products(
    q: str | None = Query(default=None, max_length=160),
    category_id: int | None = Query(default=None, gt=0),
    active: bool | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    _owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    products = get_managed_products(db, q, category_id, active, limit)
    return [product_management_to_dict(db, product) for product in products]


@router.post(
    "/products",
    response_model=ProductManagementRead,
    status_code=status.HTTP_201_CREATED,
)
def create_managed_product(
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
    return product_management_to_dict(db, product)


@router.patch("/products/{product_id}", response_model=ProductManagementRead)
def update_managed_product(
    product_id: int,
    payload: ProductUpdate,
    _owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    product = db.scalar(
        select(Product)
        .options(selectinload(Product.category))
        .where(Product.id == product_id)
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        update_product(db, product, payload)
        db.commit()
        db.refresh(product)
    except InventoryOperationError as error:
        db.rollback()
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A product with this barcode already exists") from error
    return product_management_to_dict(db, product)


def _delete_managed_image(image_url: str | None) -> None:
    if not image_url or not image_url.startswith("/assets/products/"):
        return
    relative_path = image_url.removeprefix("/assets/products/")
    image_path = (PRODUCT_IMAGE_ROOT / relative_path).resolve()
    root = PRODUCT_IMAGE_ROOT.resolve()
    if image_path.is_relative_to(root) and image_path.is_file():
        image_path.unlink()


@router.post("/products/{product_id}/image")
async def upload_product_image(
    product_id: int,
    request: Request,
    _owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    product = db.scalar(
        select(Product)
        .options(selectinload(Product.category))
        .where(Product.id == product_id)
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    expected_format = IMAGE_CONTENT_TYPES.get(content_type)
    if expected_format is None:
        raise HTTPException(status_code=415, detail="Upload a JPG, PNG, or WebP image")

    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Product images must be 5 MB or smaller")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded image is empty")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source = Image.open(BytesIO(content))
            if source.format != expected_format:
                raise HTTPException(status_code=415, detail="Image content does not match its file type")
            source.verify()
            image = Image.open(BytesIO(content))
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Product images must be 20 megapixels or smaller")
            image.load()
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise HTTPException(status_code=413, detail="The uploaded image dimensions are too large") from error
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(status_code=415, detail="The uploaded file is not a valid supported image") from error

    category_directory = PRODUCT_IMAGE_ROOT / product.category.slug
    try:
        category_directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise HTTPException(status_code=500, detail="The product image directory is not writable") from error
    filename = f"{uuid4().hex}.webp"
    image_path = category_directory / filename
    image_url = f"/assets/products/{product.category.slug}/{filename}"
    try:
        image.save(image_path, format="WEBP", quality=86, method=6)
    except OSError as error:
        raise HTTPException(status_code=500, detail="The product image could not be stored") from error

    previous_image_url = product.image_url
    product.image_url = image_url
    try:
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="The product image could not be saved") from error
    _delete_managed_image(previous_image_url)
    return {"image_url": image_url}


@router.delete("/products/{product_id}/image", status_code=status.HTTP_204_NO_CONTENT)
def remove_product_image(
    product_id: int,
    _owner: AccountUser = Depends(require_owner),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    previous_image_url = product.image_url
    if previous_image_url is None:
        return None
    product.image_url = None
    db.commit()
    _delete_managed_image(previous_image_url)
    return None
