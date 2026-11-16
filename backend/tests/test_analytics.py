from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.auth import STAFF_SESSION_COOKIE, hash_password, issue_session
from backend.app.models import (
    AccountUser,
    InventoryLocation,
    MedicineBatch,
    Product,
    ProductCategory,
    Sale,
    SaleItem,
    StoreConfiguration,
    Supplier,
)


def _insert_report_fixture(database_path):
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        category = ProductCategory(name="Medicines", name_key="medicines", slug="medicines")
        supplier = Supplier(name="Test Supplier")
        db.add_all([category, supplier])
        db.flush()
        product = Product(
            name="Recorded Product",
            category_id=category.id,
            unit_price=Decimal("10.00"),
            min_threshold=2,
            active=True,
        )
        db.add(product)
        db.flush()
        location = db.query(InventoryLocation).filter_by(code="A1").one()
        batch = MedicineBatch(
            product_id=product.id,
            location_id=location.id,
            supplier_id=supplier.id,
            batch_number="RECORDED-BATCH",
            expiry_date=date.today() + timedelta(days=200),
            purchase_date=date.today(),
            purchase_price=Decimal("30.00"),
            quantity=8,
            received_quantity=10,
            unit_cost=Decimal("3.00"),
            status="active",
        )
        sale = Sale(
            invoice_number="INV-TEST-ANALYTICS",
            subtotal_amount=Decimal("20.00"),
            total_amount=Decimal("24.00"),
            tax_amount=Decimal("4.00"),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add_all([batch, sale])
        db.flush()
        db.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                batch_id=batch.id,
                quantity=2,
                unit_price=Decimal("10.00"),
                discount_amount=Decimal("0.00"),
                tax_amount=Decimal("4.00"),
                line_total=Decimal("24.00"),
            )
        )
        db.add(
            StoreConfiguration(
                id=1,
                store_name="Test Pharmacy",
                store_phone="000",
                tax_rate_percent=Decimal("20.00"),
                currency_code="INR",
            )
        )
        db.commit()
        result = {"product_id": product.id}
    engine.dispose()
    return result


def test_owner_analytics_uses_recorded_sales_and_costs(api_client):
    client, database_path = api_client
    _insert_report_fixture(database_path)
    today = date.today().isoformat()

    dashboard = client.get(f"/api/analytics/dashboard?date_from={today}&date_to={today}")
    assert dashboard.status_code == 200, dashboard.text
    data = dashboard.json()
    assert data["sales"]["transaction_count"] == 1
    assert data["sales"]["gross_sales"] == 24
    assert data["sales"]["net_revenue"] == 24
    assert data["sales"]["units_sold"] == 2
    assert data["profit"]["calculable"] is True
    assert data["profit"]["estimated_gross_profit"] == 14
    assert data["inventory"]["eligible_units"] == 8
    assert data["purchase_summary"]["recorded_purchase_value"] == 30

    report = client.get(f"/api/analytics/reports/profit?date_from={today}&date_to={today}")
    assert report.status_code == 200, report.text
    assert report.json()["rows"][0]["estimated_gross_profit"] == 14

    by_location = client.get("/api/analytics/reports/inventory-by-location?category=Medicines")
    assert by_location.status_code == 200, by_location.text
    assert by_location.json()["rows"][0]["location_code"] == "A1"
    assert by_location.json()["rows"][0]["on_hand_units"] == 8
    assert client.get("/api/analytics/reports/inventory-by-location?category=No%20such%20category").json()["rows"] == []

    csv_export = client.get(f"/api/analytics/reports/sales/export?format=csv&date_from={today}&date_to={today}")
    assert csv_export.status_code == 200
    assert "text/csv" in csv_export.headers["content-type"]
    assert "INV-TEST-ANALYTICS" in csv_export.text

    pdf_export = client.get(f"/api/analytics/reports/sales/export?format=pdf&date_from={today}&date_to={today}")
    assert pdf_export.status_code == 200
    assert pdf_export.content.startswith(b"%PDF")


def test_profit_is_unavailable_when_a_sold_batch_has_no_recorded_cost(api_client):
    client, database_path = api_client
    _insert_report_fixture(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        batch = db.query(MedicineBatch).filter_by(batch_number="RECORDED-BATCH").one()
        batch.unit_cost = None
        db.commit()
    engine.dispose()

    today = date.today().isoformat()
    response = client.get(f"/api/analytics/dashboard?date_from={today}&date_to={today}")
    assert response.status_code == 200
    assert response.json()["profit"]["calculable"] is False
    assert response.json()["profit"]["estimated_gross_profit"] is None
    assert response.json()["profit"]["missing_cost_units"] == 2


def test_inactive_products_are_excluded_from_eligible_stock_analytics(api_client):
    client, database_path = api_client
    records = _insert_report_fixture(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        product = db.get(Product, records["product_id"])
        product.active = False
        db.commit()
    engine.dispose()

    response = client.get("/api/analytics/dashboard")
    assert response.status_code == 200
    assert response.json()["inventory"]["on_hand_units"] == 8
    assert response.json()["inventory"]["eligible_units"] == 0


def test_analytics_is_owner_only_and_validates_date_ranges(api_client):
    client, database_path = api_client
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        operator = AccountUser(
            email="test-operator@promed.local",
            display_name="Test Operator",
            password_hash=hash_password("test-operator-password"),
            role="operator",
        )
        db.add(operator)
        db.flush()
        token = issue_session(db, operator)
        db.commit()
    engine.dispose()

    client.cookies.set(STAFF_SESSION_COOKIE, token, path="/api")
    forbidden = client.get("/api/analytics/dashboard")
    assert forbidden.status_code == 403

    client.cookies.clear()
    owner_login = client.post(
        "/api/auth/staff/login",
        json={"email": "test-owner@promed.local", "password": "test-owner-password"},
    )
    assert owner_login.status_code == 200
    invalid_range = client.get("/api/analytics/dashboard?date_from=2025-03-02&date_to=2025-03-01")
    assert invalid_range.status_code == 422
