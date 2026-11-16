from datetime import date, timedelta
from io import BytesIO

from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.models import Base, ProductCategory
from backend.app.services.store_categories import STORE_CATEGORIES, seed_store_categories


def create_upload_image(color):
    buffer = BytesIO()
    Image.new("RGB", (24, 24), color).save(buffer, format="PNG")
    return buffer.getvalue()


def seed_test_categories(database_path):
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with Session(engine) as db:
        seed_store_categories(db)
        db.commit()
    engine.dispose()


def test_store_categories_seed_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'categories.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        assert seed_store_categories(db) == 9
        db.commit()
        assert seed_store_categories(db) == 0
        db.commit()
        categories = db.scalars(select(ProductCategory).order_by(ProductCategory.id)).all()
        assert len(categories) == 9
        assert len({category.id for category in categories}) == 9
        assert {category.name for category in categories} == {
            definition["name"] for definition in STORE_CATEGORIES
        }
        assert all(category.active and category.description and category.image_url for category in categories)
    engine.dispose()


def test_category_management_edits_status_and_prevents_duplicates(api_client):
    client, database_path = api_client
    seed_test_categories(database_path)
    created = client.post(
        "/api/categories",
        json={"name": "Clinic Supplies", "description": "Recorded supplies"},
    )
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]
    assert client.post("/api/categories", json={"name": " clinic supplies "}).status_code == 409

    updated = client.patch(
        f"/api/categories/{category_id}",
        json={"name": "Clinic Essentials", "description": "Updated description"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Clinic Essentials"
    assert updated.json()["description"] == "Updated description"
    deactivated = client.patch(f"/api/categories/{category_id}", json={"active": False})
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False
    assert client.patch(f"/api/categories/{category_id}", json={"active": True}).json()["active"] is True


def test_owner_product_management_and_storefront_inventory_sync(api_client):
    client, database_path = api_client
    seed_test_categories(database_path)
    category_response = client.get("/api/categories")
    assert category_response.status_code == 200
    category_id = category_response.json()[0]["id"]

    payload = {
        "name": "Owner-managed product",
        "category_id": category_id,
        "unit_price": "12.50",
        "unit_of_measure": "box",
        "manufacturer": "Recorded manufacturer",
        "initial_stock": {
            "batch_number": "STAGE7-BATCH",
            "manufacturing_date": (date.today() - timedelta(days=30)).isoformat(),
            "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
            "purchase_date": date.today().isoformat(),
            "purchase_price": "50.00",
            "quantity": 8,
            "location_code": "A1",
        },
    }
    created = client.post("/api/management/products", json=payload)
    assert created.status_code == 201, created.text
    product = created.json()
    assert product["stock_quantity"] == 8
    assert product["available_stock_quantity"] == 8
    assert product["batches"][0]["batch_number"] == "STAGE7-BATCH"
    assert product["batches"][0]["purchase_price"] == "50.00"
    assert client.get("/api/inventory/transactions", params={"product_id": product["id"]}).json()[0]["kind"] == "receipt"

    assert client.get("/api/management/products", params={"q": "Owner-managed"}).json()[0]["id"] == product["id"]
    assert client.get("/api/management/products", params={"category_id": category_id}).json()[0]["id"] == product["id"]
    storefront = client.get("/api/store/catalog/products", params={"category_id": category_id})
    assert storefront.status_code == 200, storefront.text
    customer_product = next(item for item in storefront.json() if item["id"] == product["id"])
    assert customer_product["unit_price"] == "12.50"
    assert "purchase_price" not in customer_product

    updated = client.patch(
        f"/api/management/products/{product['id']}",
        json={"name": "Updated owner-managed product", "unit_price": "13.25"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Updated owner-managed product"
    deactivated = client.patch(f"/api/management/products/{product['id']}", json={"active": False})
    assert deactivated.status_code == 200, deactivated.text
    assert client.get("/api/management/products", params={"active": False}).json()[0]["id"] == product["id"]
    assert all(item["id"] != product["id"] for item in client.get("/api/store/catalog/products").json())


def test_product_image_upload_replace_remove_and_validation(api_client, tmp_path, monkeypatch):
    client, database_path = api_client
    seed_test_categories(database_path)
    category_id = client.get("/api/categories").json()[0]["id"]
    product = client.post(
        "/api/management/products",
        json={"name": "Image upload product", "category_id": category_id},
    ).json()
    image_root = tmp_path / "uploads"
    monkeypatch.setattr("backend.app.routers.product_management.PRODUCT_IMAGE_ROOT", image_root)

    first_upload = client.post(
        f"/api/management/products/{product['id']}/image",
        content=create_upload_image("red"),
        headers={"content-type": "image/png"},
    )
    assert first_upload.status_code == 200, first_upload.text
    first_image_url = first_upload.json()["image_url"]
    first_image_path = image_root / first_image_url.removeprefix("/assets/products/")
    assert first_image_path.is_file()
    assert first_image_path.suffix == ".webp"

    second_upload = client.post(
        f"/api/management/products/{product['id']}/image",
        content=create_upload_image("blue"),
        headers={"content-type": "image/png"},
    )
    assert second_upload.status_code == 200, second_upload.text
    second_image_url = second_upload.json()["image_url"]
    second_image_path = image_root / second_image_url.removeprefix("/assets/products/")
    assert second_image_path.is_file()
    assert not first_image_path.exists()

    assert client.post(
        f"/api/management/products/{product['id']}/image",
        content=b"not an image",
        headers={"content-type": "image/png"},
    ).status_code == 415
    assert client.post(
        f"/api/management/products/{product['id']}/image",
        content=b"data",
        headers={"content-type": "application/octet-stream"},
    ).status_code == 415
    assert client.post(
        f"/api/management/products/{product['id']}/image",
        content=b"x" * (5 * 1024 * 1024 + 1),
        headers={"content-type": "image/png"},
    ).status_code == 413

    removed = client.delete(f"/api/management/products/{product['id']}/image")
    assert removed.status_code == 204
    assert not second_image_path.exists()
    assert client.get("/api/management/products").json()[0]["image_url"] is None


def test_invalid_initial_stock_rolls_back_product_creation(api_client):
    client, database_path = api_client
    seed_test_categories(database_path)
    category_id = client.get("/api/categories").json()[0]["id"]
    response = client.post(
        "/api/management/products",
        json={
            "name": "Must not persist",
            "category_id": category_id,
            "initial_stock": {
                "batch_number": "INVALID-SUPPLIER",
                "expiry_date": (date.today() + timedelta(days=180)).isoformat(),
                "purchase_date": date.today().isoformat(),
                "quantity": 3,
                "location_code": "A1",
                "supplier_id": 9999,
            },
        },
    )
    assert response.status_code == 404, response.text
    assert client.get("/api/management/products", params={"q": "Must not persist"}).json() == []


def test_product_management_requires_owner(api_client):
    client, _database_path = api_client
    assert client.get("/api/management/products").status_code == 200
    created_staff = client.post(
        "/api/auth/staff/users",
        json={
            "email": "stage7-operator@example.test",
            "display_name": "Stage 7 Operator",
            "password": "stage7-operator-password",
            "role": "operator",
        },
    )
    assert created_staff.status_code == 201, created_staff.text
    assert client.post(
        "/api/auth/staff/login",
        json={
            "email": "stage7-operator@example.test",
            "password": "stage7-operator-password",
        },
    ).status_code == 200
    assert client.get("/api/management/products").status_code == 403
    assert client.post("/api/management/products", json={}).status_code == 403
