import os
import re
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Base, InventoryLocation
from backend.app.services.store_categories import seed_store_categories

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BACKEND_DIR / "data" / "promed.sqlite3"


def build_engine(database_url: str | None = None):
    database_url = database_url or os.getenv("PROMED_DATABASE_URL")
    if database_url:
        engine = create_engine(database_url, connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {})
    else:
        DEFAULT_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            URL.create("sqlite", database=str(DEFAULT_DATABASE_PATH)),
            connect_args={"check_same_thread": False},
        )

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_sqlite_constraints(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_inventory_transaction_snapshots(engine)
    migrate_batch_management(engine)
    migrate_stage5(engine)
    migrate_stage6(engine)
    migrate_stage7(engine)
    with SessionLocal() as db:
        seed_store_categories(db)
        for code in ("A1", "A2", "B1", "B2"):
            if db.query(InventoryLocation).filter_by(code=code).first() is None:
                db.add(InventoryLocation(code=code, name=f"Storage Box {code}"))
        db.commit()


def migrate_batch_management(target_engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return

    columns = {column["name"] for column in inspect(target_engine).get_columns("medicine_batches")}
    migrations = {
        "manufacturing_date": "DATE",
        "purchase_date": "DATE",
        "supplier_id": "INTEGER REFERENCES suppliers(id) ON DELETE SET NULL",
        "purchase_price": "NUMERIC(12, 2)",
        "received_quantity": "INTEGER NOT NULL DEFAULT 0 CHECK (received_quantity >= 0)",
        "status": "VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'quarantined', 'damaged'))",
    }
    with target_engine.begin() as connection:
        for column_name, definition in migrations.items():
            if column_name not in columns:
                connection.execute(
                    text(f"ALTER TABLE medicine_batches ADD COLUMN {column_name} {definition}")
                )
        connection.execute(
            text(
                "UPDATE medicine_batches SET purchase_date = date(created_at) "
                "WHERE purchase_date IS NULL"
            )
        )
        connection.execute(
            text(
                "UPDATE medicine_batches SET received_quantity = COALESCE("
                "(SELECT SUM(quantity_delta) FROM stock_transactions "
                "WHERE stock_transactions.batch_id = medicine_batches.id AND kind = 'receipt'), "
                "quantity) WHERE received_quantity = 0"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_medicine_batches_supplier_id "
                "ON medicine_batches (supplier_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_medicine_batches_expiry_date "
                "ON medicine_batches (expiry_date)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_batches_product_expiry "
                "ON medicine_batches (product_id, expiry_date)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_batches_status "
                "ON medicine_batches (status)"
            )
        )


def migrate_stage5(target_engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return

    additions = {
        "products": {
            "requires_prescription": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "sales": {
            "subtotal_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "discount_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "tax_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "tax_rate_percent": "NUMERIC(5, 2) NOT NULL DEFAULT 0",
            "customer_name": "VARCHAR(160)",
            "customer_phone": "VARCHAR(32)",
            "operator_reference": "VARCHAR(80)",
            "store_name": "VARCHAR(160)",
            "store_phone": "VARCHAR(32)",
            "store_address": "VARCHAR(320)",
            "currency_code": "VARCHAR(3)",
            "discount_authorized_by": "VARCHAR(80)",
            "discount_reason": "VARCHAR(240)",
            "prescription_reference": "VARCHAR(160)",
            "pharmacist_reference": "VARCHAR(80)",
            "idempotency_key": "VARCHAR(80)",
            "request_fingerprint": "VARCHAR(64)",
        },
        "sale_items": {
            "discount_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "tax_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "line_total": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "returned_quantity": "INTEGER NOT NULL DEFAULT 0",
        },
        "sale_return_items": {
            "restock_verified_by": "VARCHAR(80)",
        },
        "orders": {
            "workflow_status": "VARCHAR(24) NOT NULL DEFAULT 'RECEIVED'",
            "customer_name": "VARCHAR(160)",
            "customer_phone": "VARCHAR(32)",
            "delivery_address": "VARCHAR(320)",
            "fulfillment_method": "VARCHAR(16) NOT NULL DEFAULT 'pickup'",
            "notes": "VARCHAR(500)",
            "operator_reference": "VARCHAR(80)",
        },
        "order_items": {
            "unit_price": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
        },
    }

    with target_engine.begin() as connection:
        inspector = inspect(target_engine)
        for table_name, columns_to_add in additions.items():
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in columns_to_add.items():
                if column_name not in existing_columns:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
                    )

        connection.execute(
            text(
                "UPDATE sales SET subtotal_amount = total_amount "
                "WHERE subtotal_amount = 0 AND total_amount > 0"
            )
        )
        connection.execute(
            text(
                "UPDATE sale_items SET line_total = unit_price * quantity "
                "WHERE line_total = 0 AND unit_price * quantity > 0"
            )
        )
        connection.execute(
            text(
                "UPDATE orders SET workflow_status = CASE status "
                "WHEN 'fulfilled' THEN 'COMPLETED' WHEN 'cancelled' THEN 'CANCELLED' "
                "ELSE 'RECEIVED' END WHERE workflow_status = 'RECEIVED'"
            )
        )
        connection.execute(
            text(
                "UPDATE order_items SET unit_price = COALESCE("
                "(SELECT unit_price FROM products WHERE products.id = order_items.product_id), 0) "
                "WHERE unit_price = 0"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_idempotency_key "
                "ON sales (idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_sales_customer_phone ON sales (customer_phone)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_orders_customer_phone ON orders (customer_phone)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_orders_workflow_status ON orders (workflow_status)")
        )


def migrate_stage6(target_engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return

    additions = {
        "products": {
            "manufacturer": "VARCHAR(160)",
            "image_url": "VARCHAR(500)",
            "description": "TEXT",
            "ingredients_strengths": "TEXT",
            "common_uses": "TEXT",
            "directions": "TEXT",
            "warnings": "TEXT",
            "product_information_verified": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "orders": {
            "customer_id": "INTEGER REFERENCES account_users(id) ON DELETE SET NULL",
            "total_amount": "NUMERIC(12, 2) NOT NULL DEFAULT 0",
            "idempotency_key": "VARCHAR(80)",
            "request_fingerprint": "VARCHAR(64)",
        },
    }

    with target_engine.begin() as connection:
        inspector = inspect(target_engine)
        for table_name, columns_to_add in additions.items():
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in columns_to_add.items():
                if column_name not in existing_columns:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
                    )

        connection.execute(
            text(
                "UPDATE orders SET total_amount = COALESCE("
                "(SELECT SUM(order_items.quantity * order_items.unit_price) "
                "FROM order_items WHERE order_items.order_id = orders.id), 0) "
                "WHERE total_amount = 0"
            )
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders (customer_id)")
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idempotency_key "
                "ON orders (idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
        )


def migrate_stage7(target_engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return

    additions = {
        "product_categories": {
            "name_key": "VARCHAR(80) NOT NULL DEFAULT ''",
            "slug": "VARCHAR(80) NOT NULL DEFAULT ''",
            "description": "TEXT",
            "image_url": "VARCHAR(500)",
            "active": "BOOLEAN NOT NULL DEFAULT 1",
        },
        "products": {
            "unit_of_measure": "VARCHAR(40) NOT NULL DEFAULT 'unit'",
        },
    }

    with target_engine.begin() as connection:
        inspector = inspect(target_engine)
        for table_name, columns_to_add in additions.items():
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in columns_to_add.items():
                if column_name not in existing_columns:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
                    )

        rows = connection.execute(
            text("SELECT id, name, name_key, slug FROM product_categories ORDER BY id")
        ).mappings().all()
        used_slugs = {row["slug"] for row in rows if row["slug"]}
        for row in rows:
            name_key = " ".join(row["name"].casefold().split())
            slug = row["slug"]
            if not slug:
                base_slug = re.sub(r"[^a-z0-9]+", "-", row["name"].casefold()).strip("-")[:70] or "category"
                slug = base_slug
                if slug in used_slugs:
                    slug = f"{base_slug}-{row['id']}"
                used_slugs.add(slug)
            connection.execute(
                text("UPDATE product_categories SET name_key = :name_key, slug = :slug WHERE id = :id"),
                {"name_key": name_key, "slug": slug, "id": row["id"]},
            )

        duplicate_name_keys = connection.execute(
            text(
                "SELECT name_key FROM product_categories GROUP BY name_key "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).scalar_one_or_none()
        if duplicate_name_keys:
            raise RuntimeError(
                "Cannot enforce unique category names: existing categories differ only by case or whitespace"
            )

        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_product_categories_name_key ON product_categories (name_key)")
        )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_product_categories_slug ON product_categories (slug)")
        )


def migrate_inventory_transaction_snapshots(target_engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return

    columns = {column["name"] for column in inspect(target_engine).get_columns("stock_transactions")}
    missing_columns = {
        "previous_quantity": "INTEGER NOT NULL DEFAULT 0",
        "updated_quantity": "INTEGER NOT NULL DEFAULT 0",
    }
    added_snapshot_columns = False
    with target_engine.begin() as connection:
        for column_name, column_definition in missing_columns.items():
            if column_name not in columns:
                connection.execute(
                    text(f"ALTER TABLE stock_transactions ADD COLUMN {column_name} {column_definition}")
                )
                added_snapshot_columns = True

        if not added_snapshot_columns:
            return

        batches = connection.execute(
            text("SELECT id, quantity FROM medicine_batches ORDER BY id")
        ).mappings()
        for batch in batches:
            transactions = connection.execute(
                text(
                    "SELECT id, quantity_delta FROM stock_transactions "
                    "WHERE batch_id = :batch_id ORDER BY created_at, id"
                ),
                {"batch_id": batch["id"]},
            ).mappings().all()
            balance = batch["quantity"] - sum(item["quantity_delta"] for item in transactions)
            for transaction in transactions:
                updated_quantity = balance + transaction["quantity_delta"]
                connection.execute(
                    text(
                        "UPDATE stock_transactions "
                        "SET previous_quantity = :previous_quantity, updated_quantity = :updated_quantity "
                        "WHERE id = :transaction_id"
                    ),
                    {
                        "previous_quantity": balance,
                        "updated_quantity": updated_quantity,
                        "transaction_id": transaction["id"],
                    },
                )
                balance = updated_quantity
