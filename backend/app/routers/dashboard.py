from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.schemas import DashboardRead
from backend.app.services.dashboard import get_dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardRead)
def dashboard(db: Session = Depends(get_db)):
    return get_dashboard(db)
