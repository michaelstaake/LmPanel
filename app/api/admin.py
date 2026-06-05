from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, get_current_user
from app.core.activity_logger import log_event
from app.core.app_settings import get_or_create_app_settings
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import generate_api_key, hash_api_key, hash_password
from app.core.token_usage import get_user_token_usage, get_user_tool_usage
from app.core.usage_limits import are_tool_usage_limits_enabled, are_usage_limits_enabled, validate_tool_usage_limit_values, validate_usage_limit_values
from app.models.api_key import ApiKey
from app.models.package import Package
from app.models.user import User
from app.utils.schemas import (
    ApiKeyCreateRequest,
    AppSettingsResponse,
    AppSettingsUpdateRequest,
    PackageCreateRequest,
    PackageResponse,
    PackageUpdateRequest,
    UserCreateRequest,
    UserUpdateRequest,
)

GITHUB_REPO_OWNER = "michaelstaake"
GITHUB_REPO_NAME = "LmPanel"

router = APIRouter(prefix="/api/admin", tags=["admin"])
app_config = get_settings()
BACKGROUND_IMAGE_MAX_BYTES = 10 * 1024 * 1024
 BACKGROUND_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
 FAVICON_MAX_BYTES = 2 * 1024 * 1024
 FAVICON_EXTENSIONS = {".jpg", ".jpeg", ".png"}


@router.get("/settings", response_model=AppSettingsResponse)
def get_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AppSettingsResponse:
    app_settings = get_or_create_app_settings(db)
    return _serialize_app_settings(app_settings)


@router.patch("/settings", response_model=AppSettingsResponse)
def update_settings(payload: AppSettingsUpdateRequest, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> AppSettingsResponse:
    app_settings = get_or_create_app_settings(db)

    if payload.users_can_register is not None:
        app_settings.users_can_register = payload.users_can_register
    if payload.sitename is not None:
        app_settings.sitename = payload.sitename
    if payload.background_color is not None:
        app_settings.background_color = payload.background_color
    if payload.background_image_mode is not None:
        app_settings.background_image_mode = payload.background_image_mode
    if payload.knowledge_base_enabled is not None:
        app_settings.knowledge_base_enabled = payload.knowledge_base_enabled
    if payload.input_price_per_1m is not None:
        app_settings.input_price_per_1m = payload.input_price_per_1m
    if payload.output_price_per_1m is not None:
        app_settings.output_price_per_1m = payload.output_price_per_1m
    if payload.public_url is not None:
        app_settings.public_url = payload.public_url
    if payload.cloudflare_turnstile_enabled is not None:
        app_settings.cloudflare_turnstile_enabled = payload.cloudflare_turnstile_enabled
    if payload.cloudflare_turnstile_site_key is not None:
        app_settings.cloudflare_turnstile_site_key = payload.cloudflare_turnstile_site_key
    if payload.cloudflare_turnstile_secret_key is not None:
        app_settings.cloudflare_turnstile_secret_key = payload.cloudflare_turnstile_secret_key
    if payload.two_factor_enabled is not None:
        app_settings.two_factor_enabled = payload.two_factor_enabled
    if payload.update_check_mode is not None:
        app_settings.update_check_mode = payload.update_check_mode

    usage_limit_updates = {
        "usage_limit_tokens_60_minutes": payload.usage_limit_tokens_60_minutes,
        "usage_limit_tokens_24_hours": payload.usage_limit_tokens_24_hours,
        "usage_limit_tokens_7_days": payload.usage_limit_tokens_7_days,
        "usage_limit_tokens_30_days": payload.usage_limit_tokens_30_days,
    }
    if any(value is not None for value in usage_limit_updates.values()):
        merged_limits = {
            field_name: (
                getattr(payload, field_name)
                if getattr(payload, field_name) is not None
                else getattr(app_settings, field_name)
            )
            for field_name in usage_limit_updates
        }
        try:
            validate_usage_limit_values(**merged_limits)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for field_name, value in usage_limit_updates.items():
            if value is not None:
                setattr(app_settings, field_name, value)

    tool_usage_limit_updates = {
        "usage_limit_tools_60_minutes": payload.usage_limit_tools_60_minutes,
        "usage_limit_tools_24_hours": payload.usage_limit_tools_24_hours,
        "usage_limit_tools_7_days": payload.usage_limit_tools_7_days,
        "usage_limit_tools_30_days": payload.usage_limit_tools_30_days,
    }
    if any(value is not None for value in tool_usage_limit_updates.values()):
        merged_tool_limits = {
            field_name: (
                getattr(payload, field_name)
                if getattr(payload, field_name) is not None
                else getattr(app_settings, field_name)
            )
            for field_name in tool_usage_limit_updates
        }
        try:
            validate_tool_usage_limit_values(**merged_tool_limits)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for field_name, value in tool_usage_limit_updates.items():
            if value is not None:
                setattr(app_settings, field_name, value)

    db.add(app_settings)
    db.commit()
    db.refresh(app_settings)
    log_event(db, "admin.settings_changed", user_id=admin_user.id, username=admin_user.username)
    return _serialize_app_settings(app_settings)


@router.post("/settings/background-image", response_model=AppSettingsResponse)
async def upload_background_image(
    file: UploadFile = File(...),
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AppSettingsResponse:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in BACKGROUND_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Background image must be a JPG or PNG file")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Background image upload was empty")
    if len(content) > BACKGROUND_IMAGE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Background image must be 10 MB or smaller")

    app_settings = get_or_create_app_settings(db)
    backgrounds_directory = _backgrounds_directory()
    backgrounds_directory.mkdir(parents=True, exist_ok=True)

    _delete_background_file(app_settings.background_image_path)

    stored_name = f"background-{uuid4().hex}{extension}"
    destination = backgrounds_directory / stored_name
    destination.write_bytes(content)

    app_settings.background_image_path = f"/static/backgrounds/{stored_name}"
    db.add(app_settings)
    db.commit()
    db.refresh(app_settings)
    log_event(db, "admin.settings_changed", user_id=admin_user.id, username=admin_user.username)
    return _serialize_app_settings(app_settings)


@router.delete("/settings/background-image", response_model=AppSettingsResponse)
def delete_background_image(admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> AppSettingsResponse:
    app_settings = get_or_create_app_settings(db)
    _delete_background_file(app_settings.background_image_path)
    app_settings.background_image_path = None
    db.add(app_settings)
    db.commit()
    db.refresh(app_settings)
    log_event(db, "admin.settings_changed", user_id=admin_user.id, username=admin_user.username)
    return _serialize_app_settings(app_settings)


@router.post("/settings/favicon", response_model=AppSettingsResponse)
async def upload_favicon(
    file: UploadFile = File(...),
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AppSettingsResponse:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in FAVICON_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Favicon must be a JPG or PNG file")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Favicon upload was empty")
    if len(content) > FAVICON_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Favicon must be 2 MB or smaller")

    app_settings = get_or_create_app_settings(db)
    favicons_directory = _favicons_directory()
    favicons_directory.mkdir(parents=True, exist_ok=True)

    _delete_favicon_file(app_settings.favicon_path)

    stored_name = f"favicon-{uuid4().hex}{extension}"
    destination = favicons_directory / stored_name
    destination.write_bytes(content)

    app_settings.favicon_path = f"/static/favicons/{stored_name}"
    db.add(app_settings)
    db.commit()
    db.refresh(app_settings)
    log_event(db, "admin.settings_changed", user_id=admin_user.id, username=admin_user.username)
    return _serialize_app_settings(app_settings)


@router.delete("/settings/favicon", response_model=AppSettingsResponse)
def delete_favicon(admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> AppSettingsResponse:
    app_settings = get_or_create_app_settings(db)
    _delete_favicon_file(app_settings.favicon_path)
    app_settings.favicon_path = None
    db.add(app_settings)
    db.commit()
    db.refresh(app_settings)
    log_event(db, "admin.settings_changed", user_id=admin_user.id, username=admin_user.username)
    return _serialize_app_settings(app_settings)


class UpdateCheckResponse(BaseModel):
    latest_commit: str
    latest_version: str
    update_available: bool


@router.get("/updates/check", response_model=UpdateCheckResponse)
async def check_for_updates(admin_user: User = Depends(get_admin_user)) -> UpdateCheckResponse:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            commit_response = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/commits/main",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
        except Exception:
            commit_response = None

        try:
            release_response = await client.get(
                f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
        except Exception:
            release_response = None

    latest_commit = ""
    latest_version = ""

    if commit_response and commit_response.status_code == 200:
        latest_commit = commit_response.json().get("sha", "")

    if release_response and release_response.status_code == 200:
        latest_version = release_response.json().get("tag_name", "")

    import os
    current_commit = os.environ.get("VITE_APP_GIT_COMMIT", "")
    current_version = os.environ.get("VITE_APP_VERSION", "")

    update_available = False
    if latest_commit and current_commit and latest_commit != current_commit:
        update_available = True
    elif latest_version and current_version:
        current_tag = current_version if current_version.startswith("v") else f"v{current_version}"
        if latest_version != current_tag:
            update_available = True

    return UpdateCheckResponse(
        latest_commit=latest_commit,
        latest_version=latest_version,
        update_available=update_available,
    )


@router.get("/users")
def list_users(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(User).order_by(User.id.asc()).all()
    return [_serialize_user(u, db) for u in rows]


@router.get("/users/token-usage")
def get_users_token_usage(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[dict]:
    app_settings = get_or_create_app_settings(db)
    users = db.query(User).order_by(User.username.asc()).all()
    user_ids = [u.id for u in users]
    token_usage = get_user_token_usage(db, user_ids=user_ids, input_price_per_1m=app_settings.input_price_per_1m or 0.0, output_price_per_1m=app_settings.output_price_per_1m or 0.0)
    tool_usage = get_user_tool_usage(db, user_ids=user_ids)
    tool_map = {t["user_id"]: t for t in tool_usage}
    for item in token_usage:
        if item["user_id"] in tool_map:
            item["last_60_minutes"] = {**item["last_60_minutes"], **tool_map[item["user_id"]]["last_60_minutes"]}
            item["last_24_hours"] = {**item["last_24_hours"], **tool_map[item["user_id"]]["last_24_hours"]}
            item["last_7_days"] = {**item["last_7_days"], **tool_map[item["user_id"]]["last_7_days"]}
            item["last_30_days"] = {**item["last_30_days"], **tool_map[item["user_id"]]["last_30_days"]}
            item["forever"] = {**item["forever"], **tool_map[item["user_id"]]["forever"]}
    return token_usage


@router.get("/users/{user_id}/token-usage")
def get_single_user_token_usage(user_id: int, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[dict]:
    app_settings = get_or_create_app_settings(db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    token_usage = get_user_token_usage(db, user_ids=[user.id], input_price_per_1m=app_settings.input_price_per_1m or 0.0, output_price_per_1m=app_settings.output_price_per_1m or 0.0)
    tool_usage = get_user_tool_usage(db, user_ids=[user.id])
    if token_usage and tool_usage:
        token_usage[0]["last_60_minutes"] = {**token_usage[0]["last_60_minutes"], **tool_usage[0]["last_60_minutes"]}
        token_usage[0]["last_24_hours"] = {**token_usage[0]["last_24_hours"], **tool_usage[0]["last_24_hours"]}
        token_usage[0]["last_7_days"] = {**token_usage[0]["last_7_days"], **tool_usage[0]["last_7_days"]}
        token_usage[0]["last_30_days"] = {**token_usage[0]["last_30_days"], **tool_usage[0]["last_30_days"]}
        token_usage[0]["forever"] = {**token_usage[0]["forever"], **tool_usage[0]["forever"]}
    return token_usage


@router.post("/users")
def create_user(payload: UserCreateRequest, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    _ensure_user_uniqueness(db, payload.username, payload.email)

    package_id = payload.package_id
    if payload.is_admin and payload.package_id is None:
        package_id = 1
    elif not payload.is_admin and payload.package_id is None:
        package_id = 2

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
        is_active=payload.is_active,
        package_id=package_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, "admin.user_created", user_id=admin_user.id, username=admin_user.username, details={"new_username": user.username})
    return {"status": "ok", "user": _serialize_user(user, db)}


@router.patch("/users/{user_id}")
def update_user(user_id: int, payload: UserUpdateRequest, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_username = payload.username if payload.username is not None else user.username
    new_email = payload.email if payload.email is not None else user.email
    _ensure_user_uniqueness(db, new_username, new_email, excluded_user_id=user.id)

    would_be_admin = payload.is_admin if payload.is_admin is not None else user.is_admin
    would_be_active = payload.is_active if payload.is_active is not None else user.is_active
    if user.is_admin and (not would_be_admin or not would_be_active):
        remaining_admins = (
            db.query(User)
            .filter(User.id != user.id, User.is_admin.is_(True), User.is_active.is_(True))
            .count()
        )
        if remaining_admins == 0:
            raise HTTPException(status_code=400, detail="At least one active admin user is required")

    if payload.username is not None:
        user.username = payload.username
    if payload.email is not None:
        user.email = payload.email
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.package_id is not None:
        user.package_id = payload.package_id
    elif user.is_admin and user.package_id is None:
        user.package_id = 1

    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, "admin.user_updated", user_id=admin_user.id, username=admin_user.username, details={"target_username": user.username})
    return {"status": "ok", "user": _serialize_user(user, db)}


@router.patch("/users/{user_id}/email")
def update_user_email(user_id: int, payload: UserUpdateRequest, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_email = payload.email if payload.email is not None else user.email
    _ensure_user_uniqueness(db, user.username, new_email, excluded_user_id=user.id)

    if payload.email is not None:
        user.email = payload.email

    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, "admin.user_email_updated", user_id=admin_user.id, username=admin_user.username, details={"target_username": user.username})
    return {"status": "ok", "user": _serialize_user(user, db)}


@router.patch("/users/{user_id}/password")
def update_user_password(user_id: int, payload: UserUpdateRequest, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)

    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, "admin.user_password_updated", user_id=admin_user.id, username=admin_user.username, details={"target_username": user.username})
    return {"status": "ok", "user": _serialize_user(user, db)}


@router.patch("/users/{user_id}/toggle")
def toggle_user_active(user_id: int, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    would_be_admin = user.is_admin
    would_be_active = not user.is_active
    if user.is_admin and (not would_be_admin or not would_be_active):
        remaining_admins = (
            db.query(User)
            .filter(User.id != user.id, User.is_admin.is_(True), User.is_active.is_(True))
            .count()
        )
        if remaining_admins == 0:
            raise HTTPException(status_code=400, detail="At least one active admin user is required")

    user.is_active = would_be_active

    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, "admin.user_toggled", user_id=admin_user.id, username=admin_user.username, details={"target_username": user.username, "is_active": user.is_active})
    return {"status": "ok", "user": _serialize_user(user, db)}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_admin:
        remaining_admins = (
            db.query(User)
            .filter(User.id != user.id, User.is_admin.is_(True), User.is_active.is_(True))
            .count()
        )
        if remaining_admins == 0:
            raise HTTPException(status_code=400, detail="Cannot delete the last active admin user")

    db.delete(user)
    db.commit()
    log_event(db, "admin.user_deleted", user_id=admin_user.id, username=admin_user.username, details={"target_username": user.username})
    return {"status": "ok"}


@router.get("/api-keys")
def list_api_keys(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(ApiKey, User).join(User, User.id == ApiKey.user_id).order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).all()
    return [_serialize_api_key(api_key, user) for api_key, user in rows]


@router.post("/users/{user_id}/api-keys")
def create_api_key_for_user(user_id: int, payload: ApiKeyCreateRequest, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    plain_text_key = generate_api_key()
    api_key = ApiKey(user_id=user.id, name=payload.name, key_hash=hash_api_key(plain_text_key))
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"status": "ok", "api_key": _serialize_api_key(api_key, user), "plain_text_key": plain_text_key}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(api_key)
    db.commit()
    return {"status": "ok"}


@router.get("/packages")
def list_packages(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Package).order_by(Package.id.asc()).all()
    return [_serialize_package(p) for p in rows]


@router.post("/packages")
def create_package(payload: PackageCreateRequest, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    existing = db.query(Package).filter(Package.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="A package with that name already exists")

    package = Package(
        name=payload.name,
        is_admin_package=payload.is_admin_package,
        usage_limit_tokens_60_minutes=payload.usage_limit_tokens_60_minutes,
        usage_limit_tokens_24_hours=payload.usage_limit_tokens_24_hours,
        usage_limit_tokens_7_days=payload.usage_limit_tokens_7_days,
        usage_limit_tokens_30_days=payload.usage_limit_tokens_30_days,
        usage_limit_tools_60_minutes=payload.usage_limit_tools_60_minutes,
        usage_limit_tools_24_hours=payload.usage_limit_tools_24_hours,
        usage_limit_tools_7_days=payload.usage_limit_tools_7_days,
        usage_limit_tools_30_days=payload.usage_limit_tools_30_days,
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    log_event(db, "admin.package_created", user_id=admin_user.id, username=admin_user.username, details={"package_name": package.name})
    return {"status": "ok", "package": _serialize_package(package)}


@router.patch("/packages/{package_id}")
def update_package(package_id: int, payload: PackageUpdateRequest, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    package = db.query(Package).filter(Package.id == package_id).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")

    if package.is_admin_package:
        raise HTTPException(status_code=400, detail="Cannot edit the admin package")

    if package.is_default_package:
        if payload.name is not None and payload.name != package.name:
            raise HTTPException(status_code=400, detail="Cannot rename the default package")
        if payload.is_default_package is not None and payload.is_default_package != package.is_default_package:
            raise HTTPException(status_code=400, detail="Cannot change default package status")
    else:
        if payload.name is not None:
            existing = db.query(Package).filter(Package.name == payload.name, Package.id != package_id).first()
            if existing:
                raise HTTPException(status_code=409, detail="A package with that name already exists")
            package.name = payload.name

        if payload.is_admin_package is not None:
            package.is_admin_package = payload.is_admin_package

    if payload.usage_limit_tokens_60_minutes is not None:
        package.usage_limit_tokens_60_minutes = payload.usage_limit_tokens_60_minutes
    if payload.usage_limit_tokens_24_hours is not None:
        package.usage_limit_tokens_24_hours = payload.usage_limit_tokens_24_hours
    if payload.usage_limit_tokens_7_days is not None:
        package.usage_limit_tokens_7_days = payload.usage_limit_tokens_7_days
    if payload.usage_limit_tokens_30_days is not None:
        package.usage_limit_tokens_30_days = payload.usage_limit_tokens_30_days
    if payload.usage_limit_tools_60_minutes is not None:
        package.usage_limit_tools_60_minutes = payload.usage_limit_tools_60_minutes
    if payload.usage_limit_tools_24_hours is not None:
        package.usage_limit_tools_24_hours = payload.usage_limit_tools_24_hours
    if payload.usage_limit_tools_7_days is not None:
        package.usage_limit_tools_7_days = payload.usage_limit_tools_7_days
    if payload.usage_limit_tools_30_days is not None:
        package.usage_limit_tools_30_days = payload.usage_limit_tools_30_days

    db.add(package)
    db.commit()
    db.refresh(package)
    log_event(db, "admin.package_updated", user_id=admin_user.id, username=admin_user.username, details={"package_name": package.name})
    return {"status": "ok", "package": _serialize_package(package)}


@router.delete("/packages/{package_id}")
def delete_package(package_id: int, admin_user: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    package = db.query(Package).filter(Package.id == package_id).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")

    if package.is_admin_package or package.is_default_package:
        raise HTTPException(status_code=400, detail="Cannot delete the admin or default package")

    users_with_package = db.query(User).filter(User.package_id == package_id).count()
    if users_with_package > 0:
        raise HTTPException(status_code=400, detail="Cannot delete a package that is assigned to users")

    db.delete(package)
    db.commit()
    log_event(db, "admin.package_deleted", user_id=admin_user.id, username=admin_user.username, details={"package_name": package.name})
    return {"status": "ok"}


def _serialize_user(user: User, db: Session) -> dict:
    package_name = None
    if user.package_id is not None:
        package = db.query(Package).filter(Package.id == user.package_id).first()
        if package:
            package_name = package.name
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "package_id": user.package_id,
        "package_name": package_name,
    }


def _serialize_api_key(api_key: ApiKey, user: User) -> dict:
    return {
        "id": api_key.id,
        "user_id": api_key.user_id,
        "user_username": user.username,
        "name": api_key.name,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
    }


def _serialize_package(package: Package) -> dict:
    return {
        "id": package.id,
        "name": package.name,
        "is_admin_package": package.is_admin_package,
        "usage_limit_tokens_60_minutes": package.usage_limit_tokens_60_minutes,
        "usage_limit_tokens_24_hours": package.usage_limit_tokens_24_hours,
        "usage_limit_tokens_7_days": package.usage_limit_tokens_7_days,
        "usage_limit_tokens_30_days": package.usage_limit_tokens_30_days,
        "usage_limit_tools_60_minutes": package.usage_limit_tools_60_minutes,
        "usage_limit_tools_24_hours": package.usage_limit_tools_24_hours,
        "usage_limit_tools_7_days": package.usage_limit_tools_7_days,
        "usage_limit_tools_30_days": package.usage_limit_tools_30_days,
    }


def _ensure_user_uniqueness(db: Session, username: str, email: str, excluded_user_id: int | None = None) -> None:
    username_query = db.query(User).filter(User.username == username)
    email_query = db.query(User).filter(User.email == email)
    if excluded_user_id is not None:
        username_query = username_query.filter(User.id != excluded_user_id)
        email_query = email_query.filter(User.id != excluded_user_id)

    if username_query.first():
        raise HTTPException(status_code=409, detail="A user with that username already exists")
    if email_query.first():
        raise HTTPException(status_code=409, detail="A user with that email already exists")


def _serialize_app_settings(app_settings) -> AppSettingsResponse:
    return AppSettingsResponse(
        users_can_register=app_settings.users_can_register,
        sitename=app_settings.sitename,
        background_color=app_settings.background_color,
        background_image_path=app_settings.background_image_path,
        background_image_mode=app_settings.background_image_mode,
        favicon_path=app_settings.favicon_path,
        knowledge_base_enabled=app_settings.knowledge_base_enabled,
        input_price_per_1m=app_settings.input_price_per_1m,
        output_price_per_1m=app_settings.output_price_per_1m,
        public_url=app_settings.public_url or "",
        cloudflare_turnstile_enabled=app_settings.cloudflare_turnstile_enabled,
        cloudflare_turnstile_site_key=app_settings.cloudflare_turnstile_site_key,
        cloudflare_turnstile_secret_key_set=app_settings.cloudflare_turnstile_secret_key is not None,
        two_factor_enabled=app_settings.two_factor_enabled,
        usage_limit_tokens_60_minutes=app_settings.usage_limit_tokens_60_minutes,
        usage_limit_tokens_24_hours=app_settings.usage_limit_tokens_24_hours,
        usage_limit_tokens_7_days=app_settings.usage_limit_tokens_7_days,
        usage_limit_tokens_30_days=app_settings.usage_limit_tokens_30_days,
        usage_limit_tools_60_minutes=app_settings.usage_limit_tools_60_minutes,
        usage_limit_tools_24_hours=app_settings.usage_limit_tools_24_hours,
        usage_limit_tools_7_days=app_settings.usage_limit_tools_7_days,
        usage_limit_tools_30_days=app_settings.usage_limit_tools_30_days,
        update_check_mode=app_settings.update_check_mode,
    )


def _backgrounds_directory() -> Path:
    return Path(app_config.data_dir) / "backgrounds"


def _delete_background_file(background_image_path: str | None) -> None:
    if not background_image_path or not background_image_path.startswith("/static/backgrounds/"):
        return

    file_path = _backgrounds_directory() / Path(background_image_path).name
    if file_path.exists():
        file_path.unlink()


def _favicons_directory() -> Path:
    return Path(app_config.data_dir) / "favicons"


def _delete_favicon_file(favicon_path: str | None) -> None:
    if not favicon_path or not favicon_path.startswith("/static/favicons/"):
        return

    file_path = _favicons_directory() / Path(favicon_path).name
    if file_path.exists():
        file_path.unlink()
