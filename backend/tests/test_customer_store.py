import sqlite3
from datetime import date, timedelta

from backend.app.auth import STAFF_SESSION_COOKIE


def register_customer(client, email="customer@example.test"):
    return client.post(
        "/api/auth/customer/register",
        json={
            "email": email,
            "display_name": "Store Customer",
            "phone": "+91 9876543210",
            "password": "secure-customer-password",
        },
    )


def create_store_product(client, **overrides):
    payload = {
        "name": "Customer Catalog Product",
        "barcode": "STORE-100",
        "category_name": "Store Category",
        "unit_price": "4.25",
    }
    payload.update(overrides)
    response = client.post("/api/products", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def receive_store_stock(client, product_id, quantity=3):
    return client.post(
        "/api/inventory/receipts",
        json={
            "product_id": product_id,
            "batch_number": "STORE-BATCH",
            "expiry_date": (date.today() + timedelta(days=120)).isoformat(),
            "quantity": quantity,
            "location_code": "A1",
        },
    )


def test_customer_auth_catalog_order_isolation_and_no_stock_deduction(api_client):
    client, database_path = api_client
    product = create_store_product(
        client,
        manufacturer="Verified maker",
        description="Recorded product description",
        ingredients_strengths="Recorded ingredients",
        product_information_verified=True,
    )
    receipt = receive_store_stock(client, product["id"])
    assert receipt.status_code == 201

    catalog = client.get("/api/store/catalog/products", params={"barcode": "STORE-100"})
    assert catalog.status_code == 200
    catalog_product = catalog.json()[0]
    assert catalog_product["available_quantity"] == 3
    assert catalog_product["manufacturer"] == "Verified maker"
    assert catalog_product["product_information_verified"] is True
    assert "batches" not in catalog_product
    assert "purchase_price" not in catalog_product
    assert "supplier_id" not in catalog_product
    assert client.get(
        "/api/store/catalog/products",
        params={"q": "Customer Catalog", "available": True},
    ).json()[0]["id"] == product["id"]

    invalid = client.post(
        "/api/auth/customer/register",
        json={
            "email": "new@example.test",
            "display_name": "New Customer",
            "phone": "+91 9876543210",
            "password": "short",
        },
    )
    assert invalid.status_code == 422

    registered = register_customer(client)
    assert registered.status_code == 201, registered.text
    assert registered.json()["role"] == "customer"
    assert client.post(
        "/api/auth/staff/login",
        json={"email": "customer@example.test", "password": "secure-customer-password"},
    ).status_code == 401
    stored_hash = sqlite3.connect(database_path).execute(
        "SELECT password_hash FROM account_users WHERE email = ?",
        ("customer@example.test",),
    ).fetchone()[0]
    assert stored_hash != "secure-customer-password"
    assert stored_hash.startswith("pbkdf2_sha256$")

    order_payload = {
        "items": [{"product_id": product["id"], "quantity": 2}],
        "fulfillment_method": "pickup",
        "idempotency_key": "test-order-key-001",
    }
    overstock = {**order_payload, "items": [{"product_id": product["id"], "quantity": 4}]}
    assert client.post("/api/customer/orders", json=overstock).status_code == 409
    order_response = client.post("/api/customer/orders", json=order_payload)
    assert order_response.status_code == 201, order_response.text
    order = order_response.json()
    assert order["total_amount"] == "8.50"
    assert order["status"] == "RECEIVED"
    assert order["items"][0]["unit_price"] == "4.25"

    duplicate = client.post("/api/customer/orders", json=order_payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == order["id"]
    assert client.get("/api/store/catalog/products", params={"barcode": "STORE-100"}).json()[0][
        "available_quantity"
    ] == 3
    assert client.get("/api/customer/orders").json()[0]["order_number"] == order["order_number"]

    batch = receipt.json()
    quarantine = client.patch(
        f"/api/inventory/batches/{batch['id']}/status",
        json={"status": "quarantined", "reason": "Storefront exclusion test"},
    )
    assert quarantine.status_code == 200
    unavailable = client.get(
        "/api/store/catalog/products",
        params={"barcode": "STORE-100", "available": False},
    )
    assert unavailable.status_code == 200
    assert unavailable.json()[0]["availability_status"] == "unavailable"
    assert unavailable.json()[0]["available_quantity"] == 0

    first_customer_cookie = client.cookies.get("promed_customer_session")
    client.cookies.delete("promed_customer_session")
    assert register_customer(client, "other@example.test").status_code == 201
    assert client.get("/api/customer/orders").json() == []
    assert client.get(f"/api/customer/orders/{order['id']}").status_code == 404
    assert client.get(f"/api/customer/orders/by-number/{order['order_number']}").status_code == 404
    assert client.post(
        "/api/auth/customer/logout",
        json={},
    ).status_code == 204
    assert client.get("/api/auth/customer/me").json() is None
    assert client.get("/api/customer/orders").status_code == 401
    assert client.post(
        "/api/auth/customer/login",
        json={"email": "OTHER@example.test", "password": "secure-customer-password"},
    ).status_code == 200

    client.cookies.delete("promed_staff_session")
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/orders/workflow").status_code == 401
    assert client.cookies.get("promed_customer_session") != first_customer_cookie


def test_store_categories_and_empty_catalog_status_do_not_require_inventory(api_client):
    client, _database_path = api_client

    categories = client.get("/api/store/catalog/categories")
    assert categories.status_code == 200
    assert [category["slug"] for category in categories.json()] == [
        "medicines",
        "creams-gels",
        "first-aid-wound-care",
        "personal-care",
        "baby-care",
        "health-nutrition",
        "vitamins-minerals",
        "medical-equipment",
        "hygiene-sanitary-products",
    ]
    assert client.get("/api/store/catalog/products").json() == []
    assert client.get("/api/store/catalog/status").json() == {
        "active_product_count": 0,
        "eligible_product_count": 0,
        "category_record_count": 0,
    }


def test_store_category_slug_filters_real_products_and_excludes_quarantined_stock(api_client):
    client, _database_path = api_client
    product = create_store_product(client, category_name="Creams & Gels")
    batch = receive_store_stock(client, product["id"]).json()

    category = next(
        item for item in client.get("/api/store/catalog/categories").json()
        if item["slug"] == "creams-gels"
    )
    assert category["database_category_ids"] == [product["category_id"]]
    assert client.get(
        "/api/store/catalog/products",
        params={"category": "creams-gels", "available": True},
    ).json()[0]["id"] == product["id"]
    assert client.get(
        "/api/store/catalog/products",
        params={"category": "unknown-category"},
    ).status_code == 422
    assert client.get(
        "/api/store/catalog/products",
        params={"category": "creams-gels", "category_id": product["category_id"]},
    ).status_code == 422
    assert client.get("/api/store/catalog/status").json()["eligible_product_count"] == 1

    quarantine = client.patch(
        f"/api/inventory/batches/{batch['id']}/status",
        json={"status": "quarantined", "reason": "Storefront eligibility test"},
    )
    assert quarantine.status_code == 200
    assert client.get("/api/store/catalog/status").json()["eligible_product_count"] == 0
    unavailable = client.get(
        "/api/store/catalog/products",
        params={"category": "creams-gels", "available": False},
    )
    assert unavailable.status_code == 200
    assert unavailable.json()[0]["available_quantity"] == 0


def test_prescription_order_requires_review_and_operator_cannot_review(api_client):
    client, _database_path = api_client
    product = create_store_product(
        client,
        name="Prescription Store Product",
        barcode="STORE-RX-1",
        requires_prescription=True,
    )
    assert receive_store_stock(client, product["id"], quantity=2).status_code == 201
    assert register_customer(client).status_code == 201

    response = client.post(
        "/api/customer/orders",
        json={
            "items": [{"product_id": product["id"], "quantity": 1}],
            "fulfillment_method": "delivery",
            "delivery_address": "10 Store Road, Bengaluru",
            "idempotency_key": "rx-order-key-001",
        },
    )
    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "PHARMACIST_REVIEW"
    assert order["requires_pharmacist_review"] is True

    created_operator = client.post(
        "/api/auth/staff/users",
        json={
            "email": "operator@example.test",
            "display_name": "Store Operator",
            "phone": "+91 9999999999",
            "password": "secure-operator-password",
            "role": "operator",
        },
    )
    assert created_operator.status_code == 201, created_operator.text
    login = client.post(
        "/api/auth/staff/login",
        json={"email": "operator@example.test", "password": "secure-operator-password"},
    )
    assert login.status_code == 200, login.text
    managed = client.get("/api/orders/workflow").json()[0]
    assert managed["prescription_status"] == "pending"
    assert managed["prescription_reference"] is None
    history = client.get(f"/api/orders/{order['id']}/workflow").json()
    assert history["prescription_events"] == []

    verify = client.patch(
        f"/api/orders/{order['id']}/prescription",
        json={"status": "verified", "pharmacist_reference": "NOT-A-PHARMACIST"},
    )
    assert verify.status_code == 403
