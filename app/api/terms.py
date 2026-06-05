from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, get_current_user
from app.core.app_settings import get_or_create_app_settings
from app.core.db import get_db
from app.models.user import User
from app.utils.schemas import TermsStatusResponse

router = APIRouter(prefix="/api/terms", tags=["terms"])


@router.get("/content")
def get_terms_content(db: Session = Depends(get_db)) -> dict:
    app_settings = get_or_create_app_settings(db)
    return {
        "terms_enabled": app_settings.terms_enabled,
        "terms_content": app_settings.terms_content or "",
    }


@router.get("/settings")
def get_terms_settings(current_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    app_settings = get_or_create_app_settings(db)
    return {
        "terms_enabled": app_settings.terms_enabled,
        "terms_content": app_settings.terms_content or "",
    }


@router.patch("/settings")
def update_terms_settings(payload: dict, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    app_settings = get_or_create_app_settings(db)
    app_settings.terms_enabled = payload.get("terms_enabled", app_settings.terms_enabled)
    app_settings.terms_content = payload.get("terms_content", app_settings.terms_content)
    db.add(app_settings)
    db.commit()
    db.refresh(app_settings)
    return {
        "terms_enabled": app_settings.terms_enabled,
        "terms_content": app_settings.terms_content or "",
    }


@router.get("/status", response_model=TermsStatusResponse)
def get_terms_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TermsStatusResponse:
    app_settings = get_or_create_app_settings(db)
    terms_accepted = current_user.terms_accepted_at is not None
    return TermsStatusResponse(
        terms_enabled=app_settings.terms_enabled,
        terms_accepted=terms_accepted,
    )


@router.post("/accept")
def accept_terms(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    app_settings = get_or_create_app_settings(db)
    if not app_settings.terms_enabled:
        raise HTTPException(status_code=400, detail="Terms and policies are not enabled")
    if current_user.terms_accepted_at is not None:
        raise HTTPException(status_code=400, detail="Terms have already been accepted")
    from datetime import datetime, timezone
    current_user.terms_accepted_at = datetime.now(timezone.utc)
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return {"status": "ok"}


@router.post("/decline")
def decline_terms(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    current_user.terms_accepted_at = None
    db.add(current_user)
    db.commit()
    return {"status": "logged_out"}
