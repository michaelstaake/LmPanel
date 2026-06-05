from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.core.app_settings import get_or_create_app_settings
from app.core.db import get_db
from app.core.web_search import PROVIDER_TYPES
from app.models.user import User
from app.models.web_search_provider import WebSearchProvider
from app.utils.schemas import (
    ActiveProviderResponse,
    ActiveProviderUpdateRequest,
    WebSearchProviderResponse,
    WebSearchProviderUpdateRequest,
)

router = APIRouter(prefix="/api/admin/web-search", tags=["web-search"])

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "brave": "Brave Search",
    "serper": "Serper",
}

PROVIDER_DESCRIPTIONS: dict[str, str] = {
    "brave": "Web search powered by the Brave Search API.",
    "serper": "Web search powered by the Serper.dev Google Search API.",
}


def seed_providers(db: Session) -> None:
    """Ensure one row per known provider type exists in the database."""
    changed = False
    for provider_type in PROVIDER_TYPES:
        existing = (
            db.query(WebSearchProvider)
            .filter(WebSearchProvider.provider_type == provider_type)
            .first()
        )
        if existing is None:
            db.add(WebSearchProvider(provider_type=provider_type))
            changed = True
    if changed:
        db.commit()


def _serialize_provider(provider: WebSearchProvider) -> WebSearchProviderResponse:
    return WebSearchProviderResponse(
        id=provider.id,
        provider_type=provider.provider_type,
        display_name=PROVIDER_DISPLAY_NAMES.get(provider.provider_type, provider.provider_type),
        description=PROVIDER_DESCRIPTIONS.get(provider.provider_type, ""),
        enabled=provider.enabled,
        api_key_set=bool(provider.api_key),
        result_count=provider.result_count,
    )


@router.get("/providers", response_model=list[WebSearchProviderResponse])
def list_providers(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> list[WebSearchProviderResponse]:
    seed_providers(db)
    providers = (
        db.query(WebSearchProvider).order_by(WebSearchProvider.id.asc()).all()
    )
    return [_serialize_provider(p) for p in providers]


@router.patch("/providers/{provider_type}", response_model=WebSearchProviderResponse)
def update_provider(
    provider_type: str,
    payload: WebSearchProviderUpdateRequest,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> WebSearchProviderResponse:
    if provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=404, detail="Provider not found")

    provider = (
        db.query(WebSearchProvider)
        .filter(WebSearchProvider.provider_type == provider_type)
        .first()
    )
    if provider is None:
        seed_providers(db)
        provider = (
            db.query(WebSearchProvider)
            .filter(WebSearchProvider.provider_type == provider_type)
            .first()
        )

    if payload.enabled is not None:
        provider.enabled = payload.enabled
    if payload.api_key is not None:
        provider.api_key = payload.api_key if payload.api_key != "" else None
    if payload.result_count is not None:
        provider.result_count = payload.result_count

    db.add(provider)
    db.commit()
    db.refresh(provider)
    return _serialize_provider(provider)


@router.get("/active", response_model=ActiveProviderResponse)
def get_active_provider(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> ActiveProviderResponse:
    settings = get_or_create_app_settings(db)
    if settings.active_web_search_provider_id is None:
        return ActiveProviderResponse(provider_type=None)
    provider = (
        db.query(WebSearchProvider)
        .filter(WebSearchProvider.id == settings.active_web_search_provider_id)
        .first()
    )
    return ActiveProviderResponse(provider_type=provider.provider_type if provider else None)


@router.patch("/active", response_model=ActiveProviderResponse)
def set_active_provider(
    payload: ActiveProviderUpdateRequest,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> ActiveProviderResponse:
    settings = get_or_create_app_settings(db)

    if payload.provider_type is None:
        settings.active_web_search_provider_id = None
    else:
        if payload.provider_type not in PROVIDER_TYPES:
            raise HTTPException(status_code=400, detail="Invalid provider type")
        provider = (
            db.query(WebSearchProvider)
            .filter(WebSearchProvider.provider_type == payload.provider_type)
            .first()
        )
        if provider is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        if not provider.enabled or not provider.api_key:
            raise HTTPException(
                status_code=400,
                detail="Provider must be enabled and have an API key set before it can be activated.",
            )
        settings.active_web_search_provider_id = provider.id

    db.add(settings)
    db.commit()
    return ActiveProviderResponse(provider_type=payload.provider_type)
