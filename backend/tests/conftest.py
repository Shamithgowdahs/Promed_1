import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.app.auth import STAFF_SESSION_COOKIE, hash_password, issue_session
from backend.app.db import get_db
from backend.app.main import app
from backend.app.models import AccountUser, Base, InventoryLocation


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    database_path = tmp_path / "test.sqlite3"
    test_engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(test_engine)
    test_sessions = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    with test_sessions() as db:
        db.add_all(
            InventoryLocation(code=code, name=f"Storage Box {code}")
            for code in ("A1", "A2", "B1", "B2")
        )
        owner = AccountUser(
            email="test-owner@promed.local",
            display_name="Test Owner",
            password_hash=hash_password("test-owner-password"),
            role="owner",
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        owner_session = issue_session(db, owner)
        db.commit()

    def override_get_db():
        with test_sessions() as db:
            yield db

    monkeypatch.setattr("backend.app.main.initialize_database", lambda: None)
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.cookies.set(STAFF_SESSION_COOKIE, owner_session, path="/api")
    yield client, database_path
    client.close()
    app.dependency_overrides.clear()
    test_engine.dispose()
