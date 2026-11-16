from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import ApplicationSetting
from backend.app.schemas import SettingRead, SettingUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def setting_to_dict(setting: ApplicationSetting) -> dict:
    return {"key": setting.key, "value": setting.value, "updated_at": setting.updated_at}


@router.get("", response_model=list[SettingRead])
def list_settings(db: Session = Depends(get_db)):
    return [setting_to_dict(item) for item in db.scalars(select(ApplicationSetting).order_by(ApplicationSetting.key))]


@router.put("/{key}", response_model=SettingRead)
def set_setting(
    payload: SettingUpdate,
    key: str = Path(min_length=1, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$"),
    db: Session = Depends(get_db),
):
    setting = db.get(ApplicationSetting, key)
    if setting is None:
        setting = ApplicationSetting(key=key, value=payload.value)
        db.add(setting)
    else:
        setting.value = payload.value
        setting.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(setting)
    return setting_to_dict(setting)
