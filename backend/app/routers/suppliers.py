from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Supplier
from backend.app.schemas import SupplierCreate, SupplierRead, SupplierUpdate

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierRead])
def list_suppliers(db: Session = Depends(get_db)):
    return db.scalars(select(Supplier).order_by(Supplier.name)).all()


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)):
    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    try:
        db.commit()
        db.refresh(supplier)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A supplier with this reference already exists") from error
    return supplier


@router.patch("/{supplier_id}", response_model=SupplierRead)
def update_supplier(supplier_id: int, payload: SupplierUpdate, db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for field, value in payload.model_dump().items():
        setattr(supplier, field, value)
    try:
        db.commit()
        db.refresh(supplier)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="A supplier with this reference already exists") from error
    return supplier
