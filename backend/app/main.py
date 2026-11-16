import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.app.db import SessionLocal, initialize_database
from backend.app.auth import require_staff
from backend.app.routers import (
    analytics,
    catalog,
    customer_store,
    dashboard,
    inventory,
    orders,
    product_management,
    sales,
    settings,
    suppliers,
)

logger = logging.getLogger("promed.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="PROMED Pharmacy API",
    version="1.0.0",
    description="Local SQLite-backed pharmacy inventory and operations API.",
    lifespan=lifespan,
)

configured_origins = os.getenv(
    "PROMED_CORS_ORIGINS",
    "http://127.0.0.1:5500,http://localhost:5500",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in configured_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(catalog.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(product_management.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(inventory.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(dashboard.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(sales.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(orders.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(settings.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(suppliers.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(analytics.router, prefix="/api", dependencies=[Depends(require_staff)])
app.include_router(customer_store.catalog_router, prefix="/api")
app.include_router(customer_store.auth_router, prefix="/api")
app.include_router(customer_store.customer_router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health_check():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.exception_handler(IntegrityError)
async def handle_integrity_error(_request: Request, _error: IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "The request conflicts with existing data or constraints"})


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(_request: Request, error: SQLAlchemyError):
    logger.exception("Database operation failed", exc_info=error)
    return JSONResponse(status_code=500, content={"detail": "Database operation failed"})
