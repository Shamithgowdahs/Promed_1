from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from backend.app.db import (
    migrate_batch_management,
    migrate_inventory_transaction_snapshots,
    migrate_stage5,
    migrate_stage6,
)
from backend.app.models import Base, PaymentRecord, Product, Sale, StockTransaction


def create_product(client, **overrides):
    payload = {
        "name": "Test Medicine",
        "generic_name": "Test generic",
        "barcode": "TEST-100",
        "category_name": "Test category",
        "min_threshold": 5,
        "unit_price": "4.25",
    }
    payload.update(overrides)
    response = client.post("/api/products", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def receive(client, product_id, **overrides):
    payload = {
        "product_id": product_id,
        "batch_number": "BATCH-1",
        "expiry_date": (date.today() + timedelta(days=180)).isoformat(),
        "quantity": 20,
        "location_code": "A1",
    }
    payload.update(overrides)
    return client.post("/api/inventory/receipts", json=payload)


def test_empty_database_has_only_location_master_data(api_client):
    client, _database_path = api_client
    assert client.get("/api/products").json() == []
    assert [item["code"] for item in client.get("/api/locations").json()] == ["A1", "A2", "B1", "B2"]
    assert client.get("/api/dashboard").json()["stock_units"] == 0


def test_product_creation_retrieval_and_search(api_client):
    client, _database_path = api_client
    product = create_product(client)

    fetched = client.get(f"/api/products/{product['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Test Medicine"
    assert fetched.json()["stock_quantity"] == 0
    assert client.get("/api/products?q=generic").json()[0]["id"] == product["id"]
    assert client.get("/api/products?barcode=TEST-100").json()[0]["id"] == product["id"]


def test_receipts_adjustments_and_search_do_not_mutate_stock(api_client):
    client, _database_path = api_client
    product = create_product(client)
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 0

    receipt = receive(client, product["id"])
    assert receipt.status_code == 201, receipt.text
    batch = receipt.json()
    assert batch["quantity"] == 20

    product_read = client.get(f"/api/products/{product['id']}").json()
    assert product_read["stock_quantity"] == 20
    assert product_read["batches"][0]["batch_number"] == "BATCH-1"
    assert product_read["locations"] == ["A1"]
    assert product_read["location_quantities"] == [{"location_code": "A1", "quantity": 20}]
    assert client.get("/api/products", params={"q": "Test Medicine"}).json()[0]["stock_quantity"] == 20
    assert client.get("/api/products", params={"barcode": "TEST-100"}).json()[0]["stock_quantity"] == 20

    adjustment = client.post(
        "/api/inventory/adjustments",
        json={"batch_id": batch["id"], "quantity_delta": -3, "reason": "Count correction"},
    )
    assert adjustment.status_code == 201, adjustment.text
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 17
    transactions = client.get("/api/inventory/transactions", params={"product_id": product["id"]}).json()
    assert [item["kind"] for item in transactions] == ["adjustment", "receipt"]
    assert (transactions[0]["previous_quantity"], transactions[0]["updated_quantity"]) == (20, 17)
    assert (transactions[1]["previous_quantity"], transactions[1]["updated_quantity"]) == (0, 20)
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["stock_units"] == 17
    assert dashboard["low_stock_count"] == 0
    assert dashboard["recent_transactions"][0]["quantity_delta"] == -3


def test_validation_and_stock_constraints(api_client):
    client, _database_path = api_client
    invalid_product = client.post(
        "/api/products",
        json={"name": " ", "category_name": "Category", "unit_price": -1},
    )
    assert invalid_product.status_code == 422

    product = create_product(client)
    duplicate = client.post(
        "/api/products",
        json={
            "name": "Duplicate Medicine",
            "barcode": "TEST-100",
            "category_name": "Test category",
        },
    )
    assert duplicate.status_code == 409
    expired = receive(
        client,
        product["id"],
        expiry_date=(date.today() - timedelta(days=1)).isoformat(),
    )
    assert expired.status_code == 422
    assert receive(client, product["id"], location_code="UNKNOWN").status_code == 404

    batch = receive(client, product["id"]).json()
    zero_delta = client.post(
        "/api/inventory/adjustments",
        json={"batch_id": batch["id"], "quantity_delta": 0, "reason": "Invalid"},
    )
    assert zero_delta.status_code == 422
    missing_reason = client.post(
        "/api/inventory/adjustments",
        json={"batch_id": batch["id"], "quantity_delta": -1, "reason": "  "},
    )
    assert missing_reason.status_code == 422
    zero_receipt = receive(client, product["id"], quantity=0)
    assert zero_receipt.status_code == 422
    over_adjust = client.post(
        "/api/inventory/adjustments",
        json={"batch_id": batch["id"], "quantity_delta": -21, "reason": "Invalid count"},
    )
    assert over_adjust.status_code == 409
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 20


def test_concurrent_receipts_are_atomic_and_ledger_snapshots_are_sequential(api_client):
    client, _database_path = api_client
    product = create_product(client)

    def submit_receipt(_):
        return receive(client, product["id"], quantity=1).status_code

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(submit_receipt, range(16)))

    assert statuses == [201] * 16
    saved_product = client.get(f"/api/products/{product['id']}").json()
    assert saved_product["stock_quantity"] == 16
    transactions = client.get("/api/inventory/transactions", params={"product_id": product["id"]}).json()
    assert len(transactions) == 16
    snapshots = {(item["previous_quantity"], item["updated_quantity"]) for item in transactions}
    assert snapshots == {(quantity, quantity + 1) for quantity in range(16)}

    batch_id = saved_product["batches"][0]["id"]

    def submit_adjustment(_):
        return client.post(
            "/api/inventory/adjustments",
            json={"batch_id": batch_id, "quantity_delta": -1, "reason": "Missing stock"},
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as executor:
        adjustment_statuses = list(executor.map(submit_adjustment, range(8)))

    assert adjustment_statuses == [201] * 8
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 8
    adjustment_transactions = [
        item
        for item in client.get("/api/inventory/transactions", params={"product_id": product["id"]}).json()
        if item["kind"] == "adjustment"
    ]
    assert {
        (item["previous_quantity"], item["updated_quantity"]) for item in adjustment_transactions
    } == {(quantity, quantity - 1) for quantity in range(9, 17)}


def test_low_stock_reorder_quantity_and_threshold_update(api_client):
    client, _database_path = api_client
    product = create_product(client, min_threshold=10)
    assert receive(client, product["id"], quantity=7).status_code == 201

    low_stock = client.get("/api/inventory/low-stock")
    assert low_stock.status_code == 200
    assert low_stock.json() == [
        {
            "product_id": product["id"],
            "product_name": "Test Medicine",
            "barcode": "TEST-100",
            "stock_quantity": 7,
            "min_threshold": 10,
            "suggested_reorder_quantity": 13,
            "location_quantities": [{"location_code": "A1", "quantity": 7}],
        }
    ]

    updated = client.patch(f"/api/products/{product['id']}", json={"min_threshold": 4})
    assert updated.status_code == 200
    assert updated.json()["min_threshold"] == 4
    assert client.get("/api/inventory/low-stock").json() == []
    assert client.patch(f"/api/products/{product['id']}", json={"min_threshold": -1}).status_code == 422


def test_location_management_and_receipt_at_new_location(api_client):
    client, _database_path = api_client
    created = client.post("/api/locations", json={"code": "c1", "name": "Cold cabinet"})
    assert created.status_code == 201, created.text
    location = created.json()
    assert location["code"] == "C1"
    assert client.post("/api/locations", json={"code": "C1", "name": "Duplicate"}).status_code == 409

    updated = client.put(
        f"/api/locations/{location['id']}",
        json={"code": "C1", "name": "Refrigerated cabinet"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Refrigerated cabinet"
    assert client.post("/api/locations", json={"code": "bad code", "name": "Invalid"}).status_code == 422

    product = create_product(client)
    assert receive(client, product["id"], location_code="C1", quantity=3).status_code == 201
    stored_product = client.get(f"/api/products/{product['id']}").json()
    assert stored_product["location_quantities"] == [{"location_code": "C1", "quantity": 3}]
    rename_code = client.put(
        f"/api/locations/{location['id']}",
        json={"code": "C2", "name": "Refrigerated cabinet"},
    )
    assert rename_code.status_code == 409


def test_legacy_transaction_snapshot_migration(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"
    legacy_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE medicine_batches (id INTEGER PRIMARY KEY, quantity INTEGER NOT NULL)"))
        connection.execute(
            text(
                "CREATE TABLE stock_transactions ("
                "id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL, quantity_delta INTEGER NOT NULL, "
                "created_at TEXT NOT NULL)"
            )
        )
        connection.execute(text("INSERT INTO medicine_batches (id, quantity) VALUES (1, 9)"))
        connection.execute(
            text(
                "INSERT INTO stock_transactions (id, batch_id, quantity_delta, created_at) VALUES "
                "(1, 1, 12, '2025-01-01'), (2, 1, -3, '2025-01-02')"
            )
        )

    migrate_inventory_transaction_snapshots(legacy_engine)
    with legacy_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT previous_quantity, updated_quantity FROM stock_transactions ORDER BY id"
            )
        ).all()
    assert rows == [(0, 12), (12, 9)]
    legacy_engine.dispose()


def test_sales_allocate_fefo_batches_and_orders_do_not_change_stock(api_client):
    client, _database_path = api_client
    product = create_product(client)
    expiring = date.today() + timedelta(days=20)
    later = date.today() + timedelta(days=200)
    first = receive(client, product["id"], batch_number="EARLY", expiry_date=expiring.isoformat(), quantity=3)
    second = receive(client, product["id"], batch_number="LATE", expiry_date=later.isoformat(), quantity=10)
    assert first.status_code == second.status_code == 201

    sale = client.post("/api/sales", json={"items": [{"product_id": product["id"], "quantity": 5}]})
    assert sale.status_code == 201, sale.text
    sale_data = sale.json()
    assert sale_data["total_amount"] == "21.25"
    assert [item["batch_number"] for item in sale_data["items"]] == ["EARLY", "LATE"]
    sale_transactions = client.get("/api/inventory/transactions", params={"product_id": product["id"]}).json()
    sale_entries = [item for item in sale_transactions if item["kind"] == "sale"]
    assert {(item["previous_quantity"], item["updated_quantity"]) for item in sale_entries} == {(3, 0), (10, 8)}
    assert client.get("/api/dashboard").json()["today_sales_amount"] == "21.25"
    remaining = client.get(f"/api/products/{product['id']}").json()
    assert remaining["stock_quantity"] == 8
    assert {batch["batch_number"]: batch["quantity"] for batch in remaining["batches"]} == {"EARLY": 0, "LATE": 8}
    insufficient = client.post(
        "/api/sales",
        json={"items": [{"product_id": product["id"], "quantity": 9}]},
    )
    assert insufficient.status_code == 409
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 8

    order = client.post("/api/orders", json={"items": [{"product_id": product["id"], "quantity": 2}]})
    assert order.status_code == 201
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 8


def test_database_records_survive_engine_reopen(api_client):
    client, database_path = api_client
    product = create_product(client)
    batch = receive(client, product["id"], quantity=11).json()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with Session(engine) as db:
        stored = db.scalar(select(Product).where(Product.id == product["id"]))
        assert stored is not None
        assert stored.name == "Test Medicine"
        transaction = db.scalar(select(StockTransaction).where(StockTransaction.batch_id == batch["id"]))
        assert transaction is not None
        assert (transaction.previous_quantity, transaction.updated_quantity) == (0, 11)
    engine.dispose()


def test_order_status_settings_and_low_stock_metric(api_client):
    client, _database_path = api_client
    product = create_product(client, min_threshold=5)
    assert receive(client, product["id"], quantity=5).status_code == 201
    assert client.get("/api/dashboard").json()["low_stock_count"] == 1

    order = client.post("/api/orders", json={"items": [{"product_id": product["id"], "quantity": 2}]})
    order_id = order.json()["id"]
    assert client.patch(f"/api/orders/{order_id}", json={"status": "fulfilled"}).status_code == 200
    assert client.patch(f"/api/orders/{order_id}", json={"status": "cancelled"}).status_code == 409

    updated = client.put("/api/settings/currency", json={"value": "USD"})
    assert updated.status_code == 200
    assert updated.json()["value"] == "USD"


def test_expiry_endpoint_and_dashboard_count_use_batch_dates(api_client):
    client, _database_path = api_client
    product = create_product(client)
    expiry_date = date.today() + timedelta(days=20)
    assert receive(
        client,
        product["id"],
        batch_number="EXPIRING",
        expiry_date=expiry_date.isoformat(),
        quantity=4,
    ).status_code == 201

    expiring = client.get("/api/inventory/expiry", params={"within_days": 30})
    assert expiring.status_code == 200
    assert expiring.json()[0]["batch_number"] == "EXPIRING"
    assert expiring.json()[0]["days_remaining"] == 20
    assert client.get("/api/inventory/expiry", params={"within_days": 10}).json() == []
    assert client.get("/api/dashboard").json()["expiring_batch_count"] == 1


def test_batch_metadata_supplier_filters_and_status_history(api_client):
    client, _database_path = api_client
    product = create_product(client)
    supplier_response = client.post(
        "/api/suppliers",
        json={
            "name": "Local wholesaler",
            "contact_details": "555-0100",
            "address": "Warehouse district",
            "reference_code": "SUP-1",
        },
    )
    assert supplier_response.status_code == 201, supplier_response.text
    supplier_id = supplier_response.json()["id"]
    assert client.post(
        "/api/suppliers",
        json={"name": "Duplicate reference", "reference_code": "SUP-1"},
    ).status_code == 409

    manufacturing_date = date.today() - timedelta(days=180)
    early = receive(
        client,
        product["id"],
        batch_number="EARLY-1",
        expiry_date=(date.today() + timedelta(days=20)).isoformat(),
        manufacturing_date=manufacturing_date.isoformat(),
        purchase_date=date.today().isoformat(),
        supplier_id=supplier_id,
        purchase_price="50.00",
        quantity=10,
        location_code="A2",
    )
    later = receive(
        client,
        product["id"],
        batch_number="LATE-1",
        expiry_date=(date.today() + timedelta(days=120)).isoformat(),
        quantity=7,
        location_code="A1",
    )
    assert early.status_code == later.status_code == 201
    early_batch = early.json()
    assert early_batch["supplier_name"] == "Local wholesaler"
    assert early_batch["supplier_reference"] == "SUP-1"
    assert early_batch["manufacturing_date"] == manufacturing_date.isoformat()
    assert early_batch["purchase_price"] == "50.00"
    assert early_batch["unit_cost"] == "5.00"
    assert early_batch["received_quantity"] == 10
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 17

    filtered = client.get(
        "/api/inventory/batches",
        params={
            "product_name": "Test Medicine",
            "batch_number": "EARLY",
            "expiry_category": "within_30_days",
            "category_id": product["category_id"],
            "location_code": "A2",
            "status": "active",
        },
    )
    assert filtered.status_code == 200
    assert [batch["id"] for batch in filtered.json()] == [early_batch["id"]]
    safe_batches = client.get(
        "/api/inventory/expiry",
        params={"expiry_category": "safe"},
    ).json()
    assert [batch["batch_number"] for batch in safe_batches] == ["LATE-1"]

    history = client.get(f"/api/inventory/batches/{early_batch['id']}/history").json()
    assert [item["kind"] for item in history["transactions"]] == ["receipt"]
    assert history["transactions"][0]["updated_quantity"] == 10
    status_change = client.patch(
        f"/api/inventory/batches/{early_batch['id']}/status",
        json={"status": "quarantined", "reason": "Supplier documentation pending"},
    )
    assert status_change.status_code == 200
    updated_history = client.get(f"/api/inventory/batches/{early_batch['id']}/history").json()
    assert updated_history["status_events"][0]["updated_status"] == "quarantined"
    assert updated_history["batch"]["available_quantity"] == 0
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["available_stock_units"] == 7
    assert {item["category"] for item in dashboard["expiry_categories"]} == {
        "expired", "within_30_days", "within_60_days", "within_90_days", "safe"
    }

    invalid_dates = receive(
        client,
        product["id"],
        batch_number="BAD-DATES",
        expiry_date=(date.today() + timedelta(days=100)).isoformat(),
        manufacturing_date=(date.today() + timedelta(days=1)).isoformat(),
    )
    assert invalid_dates.status_code == 422


def test_sales_exclude_expired_quarantined_and_damaged_batches(api_client):
    client, database_path = api_client
    product = create_product(client)
    expired = receive(
        client,
        product["id"],
        batch_number="AGED-OUT",
        expiry_date=(date.today() + timedelta(days=1)).isoformat(),
        purchase_date=(date.today() - timedelta(days=2)).isoformat(),
        quantity=5,
    ).json()
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE medicine_batches SET expiry_date = :expiry_date WHERE id = :batch_id"),
            {"expiry_date": (date.today() - timedelta(days=1)).isoformat(), "batch_id": expired["id"]},
        )
    engine.dispose()

    quarantined = receive(
        client,
        product["id"],
        batch_number="QUARANTINED",
        expiry_date=(date.today() + timedelta(days=2)).isoformat(),
        quantity=5,
    ).json()
    damaged = receive(
        client,
        product["id"],
        batch_number="DAMAGED",
        expiry_date=(date.today() + timedelta(days=3)).isoformat(),
        quantity=5,
    ).json()
    early = receive(
        client,
        product["id"],
        batch_number="FEFO-EARLY",
        expiry_date=(date.today() + timedelta(days=10)).isoformat(),
        quantity=3,
    ).json()
    late = receive(
        client,
        product["id"],
        batch_number="FEFO-LATE",
        expiry_date=(date.today() + timedelta(days=100)).isoformat(),
        quantity=10,
    ).json()
    for batch, status_value in ((quarantined, "quarantined"), (damaged, "damaged")):
        response = client.patch(
            f"/api/inventory/batches/{batch['id']}/status",
            json={"status": status_value, "reason": f"Mark {status_value}"},
        )
        assert response.status_code == 200

    sale = client.post("/api/sales", json={"items": [{"product_id": product["id"], "quantity": 5}]})
    assert sale.status_code == 201, sale.text
    assert [(item["batch_id"], item["quantity"]) for item in sale.json()["items"]] == [
        (early["id"], 3),
        (late["id"], 2),
    ]
    assert client.get(f"/api/products/{product['id']}").json()["expired_stock_quantity"] == 5
    insufficient = client.post("/api/sales", json={"items": [{"product_id": product["id"], "quantity": 9}]})
    assert insufficient.status_code == 409
    remaining = client.get(f"/api/products/{product['id']}").json()
    assert remaining["available_stock_quantity"] == 8
    assert {batch["id"]: batch["quantity"] for batch in remaining["batches"]} == {
        expired["id"]: 5,
        quarantined["id"]: 5,
        damaged["id"]: 5,
        early["id"]: 0,
        late["id"]: 8,
    }


def test_batch_migration_backfills_metadata_and_preserves_history(tmp_path):
    database_path = tmp_path / "legacy-batches.sqlite3"
    legacy_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE suppliers (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE medicine_batches ("
                "id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, location_id INTEGER NOT NULL, "
                "batch_number TEXT NOT NULL, expiry_date DATE NOT NULL, quantity INTEGER NOT NULL, "
                "unit_cost NUMERIC, created_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE stock_transactions ("
                "id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL, kind TEXT NOT NULL, "
                "quantity_delta INTEGER NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO medicine_batches "
                "(id, product_id, location_id, batch_number, expiry_date, quantity, unit_cost, created_at) "
                "VALUES (1, 1, 1, 'LEGACY', '2099-12-31', 7, 2.50, '2024-06-05 12:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO stock_transactions (id, batch_id, kind, quantity_delta) "
                "VALUES (1, 1, 'receipt', 10), (2, 1, 'sale', -3)"
            )
        )

    migrate_batch_management(legacy_engine)
    migrate_batch_management(legacy_engine)
    with legacy_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT purchase_date, received_quantity, status, quantity "
                "FROM medicine_batches WHERE id = 1"
            )
        ).one()
        transactions = connection.execute(
            text("SELECT COUNT(*) FROM stock_transactions WHERE batch_id = 1")
        ).scalar_one()
        indexes = {index["name"] for index in inspect(legacy_engine).get_indexes("medicine_batches")}
        foreign_keys = connection.execute(text("PRAGMA foreign_key_list(medicine_batches)")).all()
    assert row == ("2024-06-05", 10, "active", 7)
    assert transactions == 2
    assert {
        "ix_medicine_batches_expiry_date",
        "ix_batches_product_expiry",
        "ix_batches_status",
    }.issubset(indexes)
    assert any(item[2] == "suppliers" and item[3] == "supplier_id" for item in foreign_keys)
    legacy_engine.dispose()


def configure_sales(client, **overrides):
    payload = {
        "store_name": "PROMED Local Store",
        "store_phone": "555-0100",
        "store_address": "Store address",
        "tax_rate_percent": "5.00",
        "currency_code": "USD",
    }
    payload.update(overrides)
    response = client.put("/api/sales/config", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def checkout_payload(product_id, **overrides):
    payload = {
        "items": [{"product_id": product_id, "quantity": 4}],
        "operator_reference": "operator-1",
        "payment_method": "cash",
        "payment_amount": "20.00",
        "idempotency_key": "checkout-test-key-1",
    }
    payload.update(overrides)
    return payload


def test_pos_checkout_fefo_payment_invoice_and_idempotency(api_client):
    client, _database_path = api_client
    configure_sales(client)
    product = create_product(client)
    early = receive(
        client,
        product["id"],
        batch_number="POS-EARLY",
        expiry_date=(date.today() + timedelta(days=10)).isoformat(),
        quantity=2,
    ).json()
    late = receive(
        client,
        product["id"],
        batch_number="POS-LATE",
        expiry_date=(date.today() + timedelta(days=50)).isoformat(),
        quantity=5,
    ).json()
    before = client.get(f"/api/products?barcode={product['barcode']}").json()[0]
    assert before["available_stock_quantity"] == 7

    payload = checkout_payload(product["id"])
    response = client.post("/api/sales/checkout", json=payload)
    assert response.status_code == 201, response.text
    invoice = response.json()
    assert invoice["subtotal_amount"] == "17.00"
    assert invoice["tax_amount"] == "0.85"
    assert invoice["total_amount"] == "17.85"
    assert invoice["payment"]["method"] == "cash"
    assert invoice["payment"]["cash_received"] == "20.00"
    assert invoice["payment"]["change_given"] == "2.15"
    allocations = [(item["batch_number"], item["quantity"]) for item in invoice["items"]]
    assert allocations == [("POS-EARLY", 2), ("POS-LATE", 2)]

    duplicate = client.post("/api/sales/checkout", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["sale_id"] == invoice["sale_id"]
    assert client.get(f"/api/products/{product['id']}").json()["available_stock_quantity"] == 3
    assert any(
        item["kind"] == "sale"
        for item in client.get("/api/inventory/transactions", params={"product_id": product["id"]}).json()
    )

    pdf = client.get(f"/api/sales/{invoice['sale_id']}/invoice.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    summary = client.get("/api/sales/summary")
    assert summary.status_code == 200
    assert summary.json()["today_transactions"] == 1
    assert summary.json()["today_revenue"] == "17.85"
    assert client.get("/api/sales/history", params={"invoice_number": invoice["invoice_number"]}).json()[0]["sale_id"] == invoice["sale_id"]
    engine = create_engine(f"sqlite:///{_database_path.as_posix()}")
    with Session(engine) as db:
        stored_sale = db.get(Sale, invoice["sale_id"])
        stored_payment = db.query(PaymentRecord).filter_by(sale_id=invoice["sale_id"]).one()
        assert stored_sale.invoice_number == invoice["invoice_number"]
        assert stored_sale.total_amount == Decimal("17.85")
        assert stored_payment.amount == Decimal("17.85")
    engine.dispose()


def test_pos_checkout_requires_configuration_payment_and_prescription(api_client):
    client, _database_path = api_client
    product = create_product(client, requires_prescription=True)
    batch = receive(client, product["id"], quantity=5).json()
    payload = checkout_payload(
        product["id"],
        payment_amount="4.25",
        prescription_reference="RX-REF-1",
        pharmacist_reference="pharmacist-1",
    )
    assert client.post("/api/sales/checkout", json=payload).status_code == 409
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 5

    configure_sales(client)
    missing_references = checkout_payload(product["id"], payment_amount="4.47")
    rejected = client.post("/api/sales/checkout", json=missing_references)
    assert rejected.status_code == 422
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 5

    wrong_payment = checkout_payload(
        product["id"],
        payment_amount="1.00",
        prescription_reference="RX-REF-1",
        pharmacist_reference="pharmacist-1",
        payment_method="card",
        payment_reference="AUTH-1",
    )
    rejected_payment = client.post("/api/sales/checkout", json=wrong_payment)
    assert rejected_payment.status_code == 422
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 5

    expired = create_product(
        client,
        name="Expired Stock Test",
        barcode="TEST-EXPIRED-2",
    )
    expired_batch = receive(client, expired["id"], batch_number="EXPIRED-POS", quantity=5).json()
    engine = create_engine(f"sqlite:///{_database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE medicine_batches SET expiry_date = :expiry, purchase_date = :purchase "
                "WHERE id = :batch_id"
            ),
            {
                "expiry": (date.today() - timedelta(days=1)).isoformat(),
                "purchase": (date.today() - timedelta(days=2)).isoformat(),
                "batch_id": expired_batch["id"],
            },
        )
    engine.dispose()
    expired_payload = checkout_payload(
        expired["id"],
        idempotency_key="checkout-expired-key",
        payment_amount="17.85",
    )
    assert client.post("/api/sales/checkout", json=expired_payload).status_code == 409
    assert client.get(f"/api/products/{expired['id']}").json()["stock_quantity"] == 5


def test_pos_checkout_insufficient_item_does_not_partially_deduct_stock(api_client):
    client, _database_path = api_client
    configure_sales(client, tax_rate_percent="0.00")
    first = create_product(client, name="Atomic First", barcode="ATOMIC-FIRST")
    second = create_product(client, name="Atomic Second", barcode="ATOMIC-SECOND")
    receive(client, first["id"], batch_number="ATOMIC-FIRST-BATCH", quantity=5)
    receive(client, second["id"], batch_number="ATOMIC-SECOND-BATCH", quantity=1)
    response = client.post(
        "/api/sales/checkout",
        json=checkout_payload(
            first["id"],
            items=[
                {"product_id": first["id"], "quantity": 2},
                {"product_id": second["id"], "quantity": 2},
            ],
            idempotency_key="checkout-insufficient-atomic",
        ),
    )
    assert response.status_code == 409
    assert client.get(f"/api/products/{first['id']}").json()["stock_quantity"] == 5
    assert client.get(f"/api/products/{second['id']}").json()["stock_quantity"] == 1
    assert client.get("/api/sales").json() == []


def test_pos_records_upi_and_card_payments(api_client):
    client, _database_path = api_client
    configure_sales(client, tax_rate_percent="0.00")
    product = create_product(client)
    receive(client, product["id"], quantity=2)
    for method in ("upi", "card"):
        response = client.post(
            "/api/sales/checkout",
            json=checkout_payload(
                product["id"],
                items=[{"product_id": product["id"], "quantity": 1}],
                payment_method=method,
                payment_amount="4.25",
                payment_reference=f"{method.upper()}-TEST-REF",
                idempotency_key=f"checkout-{method}-test-key",
            ),
        )
        assert response.status_code == 201, response.text
        assert response.json()["payment"]["method"] == method
        assert response.json()["payment"]["reference"] == f"{method.upper()}-TEST-REF"


def test_pos_discounts_require_authorization_and_recompute_tax(api_client):
    client, _database_path = api_client
    configure_sales(client, tax_rate_percent="5.00")
    product = create_product(client)
    receive(client, product["id"], quantity=2)
    payload = checkout_payload(
        product["id"],
        items=[{"product_id": product["id"], "quantity": 2}],
        discount_amount="1.00",
        discount_authorized_by="supervisor-reference",
        discount_reason="Approved discount",
        payment_amount="8.00",
        idempotency_key="checkout-discount-authorized",
    )
    unauthorized = {**payload, "discount_authorized_by": None}
    assert client.post("/api/sales/checkout", json=unauthorized).status_code == 422
    response = client.post("/api/sales/checkout", json=payload)
    assert response.status_code == 201, response.text
    invoice = response.json()
    assert invoice["subtotal_amount"] == "8.50"
    assert invoice["discount_amount"] == "1.00"
    assert invoice["tax_amount"] == "0.38"
    assert invoice["total_amount"] == "7.88"
    assert invoice["discount_authorized_by"] == "supervisor-reference"
    assert invoice["discount_reason"] == "Approved discount"


def test_returns_require_inspection_and_prevent_over_return(api_client):
    client, _database_path = api_client
    configure_sales(client, tax_rate_percent="0.00")
    product = create_product(client)
    batch = receive(client, product["id"], quantity=6).json()
    sale_response = client.post(
        "/api/sales/checkout",
        json=checkout_payload(
            product["id"],
            payment_amount="17.00",
            idempotency_key="checkout-return-key",
        ),
    )
    assert sale_response.status_code == 201, sale_response.text
    sale = sale_response.json()
    sale_item_id = sale["items"][0]["sale_item_id"]

    base_return = {
        "items": [{"sale_item_id": sale_item_id, "quantity": 2, "restock": True}],
        "reason": "Package sealed and inspected",
        "refund_method": "cash",
        "operator_reference": "operator-2",
        "idempotency_key": "return-inspection-key",
    }
    missing_inspector = client.post(f"/api/sales/{sale['sale_id']}/returns", json=base_return)
    assert missing_inspector.status_code == 422

    base_return["items"][0]["restock_verified_by"] = "inspector-1"
    returned = client.post(f"/api/sales/{sale['sale_id']}/returns", json=base_return)
    assert returned.status_code == 201, returned.text
    assert returned.json()["refund_amount"] == "8.50"
    assert returned.json()["items"][0]["disposition"] == "restocked"
    assert returned.json()["items"][0]["restock_verified_by"] == "inspector-1"
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 4
    assert client.get("/api/sales/returns").json()[0]["return_number"] == returned.json()["return_number"]

    duplicate = client.post(f"/api/sales/{sale['sale_id']}/returns", json=base_return)
    assert duplicate.status_code == 200
    excessive = {
        **base_return,
        "items": [{"sale_item_id": sale_item_id, "quantity": 3, "restock": False}],
        "idempotency_key": "return-excess-key",
    }
    assert client.post(f"/api/sales/{sale['sale_id']}/returns", json=excessive).status_code == 409
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 4


def test_expired_and_quarantined_returns_cannot_be_restocked(api_client):
    client, database_path = api_client
    configure_sales(client, tax_rate_percent="0.00")
    product = create_product(client)
    expired_batch = receive(
        client,
        product["id"],
        batch_number="RETURN-EXPIRED",
        expiry_date=(date.today() + timedelta(days=10)).isoformat(),
        quantity=5,
    ).json()
    quarantined_batch = receive(
        client,
        product["id"],
        batch_number="RETURN-QUARANTINED",
        expiry_date=(date.today() + timedelta(days=20)).isoformat(),
        quantity=5,
    ).json()
    checkout = client.post(
        "/api/sales/checkout",
        json=checkout_payload(
            product["id"],
            items=[{"product_id": product["id"], "quantity": 7}],
            payment_amount="29.75",
            idempotency_key="checkout-return-status-key",
        ),
    )
    assert checkout.status_code == 201, checkout.text
    sale = checkout.json()
    sale_items_by_batch = {item["batch_number"]: item["sale_item_id"] for item in sale["items"]}

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE medicine_batches SET expiry_date = :expiry, purchase_date = :purchase "
                "WHERE id = :batch_id"
            ),
            {
                "expiry": (date.today() - timedelta(days=1)).isoformat(),
                "purchase": (date.today() - timedelta(days=2)).isoformat(),
                "batch_id": expired_batch["id"],
            },
        )
    engine.dispose()
    quarantined = client.patch(
        f"/api/inventory/batches/{quarantined_batch['id']}/status",
        json={"status": "quarantined", "reason": "Return safety test"},
    )
    assert quarantined.status_code == 200

    for batch_number, key in (
        ("RETURN-EXPIRED", "return-expired-status"),
        ("RETURN-QUARANTINED", "return-quarantined-status"),
    ):
        response = client.post(
            f"/api/sales/{sale['sale_id']}/returns",
            json={
                "items": [
                    {
                        "sale_item_id": sale_items_by_batch[batch_number],
                        "quantity": 1,
                        "restock": True,
                        "restock_verified_by": "inspector-1",
                    }
                ],
                "reason": "Inspection required",
                "refund_method": "cash",
                "operator_reference": "operator-1",
                "idempotency_key": key,
            },
        )
        assert response.status_code == 409
    saved_product = client.get(f"/api/products/{product['id']}").json()
    assert saved_product["stock_quantity"] == 3


def test_order_workflow_prescription_gate_and_no_stock_reservation(api_client):
    client, _database_path = api_client
    product = create_product(client, requires_prescription=True)
    receive(client, product["id"], quantity=9)
    create_response = client.post(
        "/api/orders/workflow",
        json={
            "items": [{"product_id": product["id"], "quantity": 2}],
            "customer_name": "Local Customer",
            "customer_phone": "555-0101",
            "fulfillment_method": "delivery",
            "delivery_address": "Delivery location",
            "prescription_reference": "RX-ORDER-1",
        },
    )
    assert create_response.status_code == 201, create_response.text
    order = create_response.json()
    assert order["status"] == "RECEIVED"
    assert order["prescription_status"] == "pending"
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 9

    order_id = order["id"]
    assert client.patch(f"/api/orders/{order_id}/workflow", json={"status": "ACCEPTED"}).status_code == 409
    reviewed = client.patch(f"/api/orders/{order_id}/workflow", json={"status": "PHARMACIST_REVIEW"})
    assert reviewed.status_code == 200
    assert client.patch(f"/api/orders/{order_id}/workflow", json={"status": "ACCEPTED"}).status_code == 409
    verification = client.patch(
        f"/api/orders/{order_id}/prescription",
        json={
            "status": "verified",
            "pharmacist_reference": "pharmacist-1",
            "prescription_reference": "RX-ORDER-1",
        },
    )
    assert verification.status_code == 200, verification.text
    assert verification.json()["order"]["prescription_status"] == "verified"

    for next_status in ("ACCEPTED", "PREPARING", "OUT_FOR_DELIVERY", "COMPLETED"):
        response = client.patch(
            f"/api/orders/{order_id}/workflow",
            json={"status": next_status, "operator_reference": "operator-1"},
        )
        assert response.status_code == 200, response.text
    history = client.get(f"/api/orders/{order_id}/workflow")
    assert history.status_code == 200, history.text
    assert [event["updated_status"] for event in history.json()["status_events"]] == [
        "RECEIVED",
        "PHARMACIST_REVIEW",
        "ACCEPTED",
        "PREPARING",
        "OUT_FOR_DELIVERY",
        "COMPLETED",
    ]
    assert history.json()["prescription_events"][-1]["pharmacist_reference"] == "pharmacist-1"
    assert client.get(f"/api/products/{product['id']}").json()["stock_quantity"] == 9


def test_order_validation_and_pickup_delivery_transitions(api_client):
    client, _database_path = api_client
    product = create_product(client)
    missing_address = client.post(
        "/api/orders/workflow",
        json={
            "items": [{"product_id": product["id"], "quantity": 1}],
            "fulfillment_method": "delivery",
        },
    )
    assert missing_address.status_code == 422
    order = client.post(
        "/api/orders/workflow",
        json={
            "items": [{"product_id": product["id"], "quantity": 1}],
            "fulfillment_method": "pickup",
        },
    ).json()
    order_id = order["id"]
    for next_status in ("PHARMACIST_REVIEW", "ACCEPTED", "PREPARING"):
        assert client.patch(f"/api/orders/{order_id}/workflow", json={"status": next_status}).status_code == 200
    assert client.patch(f"/api/orders/{order_id}/workflow", json={"status": "OUT_FOR_DELIVERY"}).status_code == 409
    assert client.patch(f"/api/orders/{order_id}/workflow", json={"status": "READY_FOR_PICKUP"}).status_code == 200
    assert client.patch(f"/api/orders/{order_id}/workflow", json={"status": "COMPLETED"}).status_code == 200


def test_stage5_migration_is_additive_and_idempotent(tmp_path):
    database_path = tmp_path / "legacy-stage5.sqlite3"
    legacy_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, unit_price NUMERIC NOT NULL)"))
        connection.execute(
            text("CREATE TABLE sales (id INTEGER PRIMARY KEY, invoice_number TEXT, total_amount NUMERIC NOT NULL)")
        )
        connection.execute(
            text("CREATE TABLE sale_items (id INTEGER PRIMARY KEY, unit_price NUMERIC NOT NULL, quantity INTEGER NOT NULL)")
        )
        connection.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT NOT NULL)"))
        connection.execute(
            text("CREATE TABLE order_items (id INTEGER PRIMARY KEY, unit_price NUMERIC NOT NULL, product_id INTEGER)")
        )
        connection.execute(text("CREATE TABLE sale_return_items (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO products (id, unit_price) VALUES (1, 4.25)"))
        connection.execute(text("INSERT INTO sales (id, invoice_number, total_amount) VALUES (1, 'INV-OLD', 8.50)"))
        connection.execute(text("INSERT INTO sale_items (id, unit_price, quantity) VALUES (1, 4.25, 2)"))
        connection.execute(text("INSERT INTO orders (id, status) VALUES (1, 'pending')"))
        connection.execute(text("INSERT INTO order_items (id, unit_price, product_id) VALUES (1, 0, 1)"))
        connection.execute(text("INSERT INTO sale_return_items (id) VALUES (1)"))

    migrate_stage5(legacy_engine)
    migrate_stage5(legacy_engine)
    with legacy_engine.connect() as connection:
        sale = connection.execute(
            text("SELECT invoice_number, subtotal_amount FROM sales WHERE id = 1")
        ).one()
        order = connection.execute(
            text("SELECT status, workflow_status FROM orders WHERE id = 1")
        ).one()
        order_item_price = connection.execute(
            text("SELECT unit_price FROM order_items WHERE id = 1")
        ).scalar_one()
        return_verification = connection.execute(
            text("SELECT restock_verified_by FROM sale_return_items WHERE id = 1")
        ).scalar_one()
        product_columns = {item["name"] for item in inspect(legacy_engine).get_columns("products")}
    assert sale == ("INV-OLD", 8.5)
    assert order == ("pending", "RECEIVED")
    assert order_item_price == 4.25
    assert return_verification is None
    assert "requires_prescription" in product_columns
    legacy_engine.dispose()


def test_stage6_migration_preserves_existing_orders_and_is_idempotent(tmp_path):
    database_path = tmp_path / "legacy-stage6.sqlite3"
    legacy_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE account_users (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, unit_price NUMERIC NOT NULL)"))
        connection.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, order_number TEXT NOT NULL)"))
        connection.execute(
            text(
                "CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER, "
                "quantity INTEGER NOT NULL, unit_price NUMERIC NOT NULL)"
            )
        )
        connection.execute(text("INSERT INTO products (id, unit_price) VALUES (1, 4.25)"))
        connection.execute(text("INSERT INTO orders (id, order_number) VALUES (1, 'ORD-LEGACY')"))
        connection.execute(
            text("INSERT INTO order_items (id, order_id, quantity, unit_price) VALUES (1, 1, 2, 4.25)")
        )

    migrate_stage6(legacy_engine)
    migrate_stage6(legacy_engine)
    with legacy_engine.connect() as connection:
        order = connection.execute(
            text("SELECT order_number, total_amount, customer_id FROM orders WHERE id = 1")
        ).one()
        product_columns = {item["name"] for item in inspect(legacy_engine).get_columns("products")}
    assert order == ("ORD-LEGACY", 8.5, None)
    assert {
        "manufacturer",
        "image_url",
        "ingredients_strengths",
        "product_information_verified",
    }.issubset(product_columns)
    legacy_engine.dispose()
