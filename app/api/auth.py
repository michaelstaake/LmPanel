import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.models import scan_models_dir
from app.core.activity_logger import log_event
from app.core.app_settings import get_or_create_app_settings
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token, generate_api_key, hash_api_key, hash_password, verify_cloudflare_turnstile, verify_password
from app.models.api_key import ApiKey
from app.models.device import Device
from app.models.model_config import ModelConfig
from app.models.package import Package
from app.models.user import User
from app.utils.brute_force import get_brute_force_manager
from app.utils.schemas import ApiKeyCreateRequest, BootstrapAdminRequest, BootstrapStatusResponse, LoginRequest, LoginResponse, ProfileUpdateRequest, UserRegistrationRequest, UserResponse, build_api_base_url

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else None


def _check_brute_force(ip: str | None, username: str | None, app_settings) -> None:
    if not app_settings.brute_force_enabled:
        return

    manager = get_brute_force_manager()
    window_seconds = app_settings.brute_force_window_minutes * 60
    block_seconds = app_settings.brute_force_block_minutes * 60

    if ip:
        if manager.is_blocked(ip):
            raise HTTPException(status_code=429, detail="Too many failed login attempts. Please try again later.")
    if username:
        if manager.is_blocked(f"user:{username}"):
            raise HTTPException(status_code=429, detail="Too many failed login attempts. Please try again later.")


def _record_brute_force_failure(ip: str | None, username: str | None, app_settings) -> None:
    if not app_settings.brute_force_enabled:
        return

    manager = get_brute_force_manager()
    window_seconds = app_settings.brute_force_window_minutes * 60
    block_seconds = app_settings.brute_force_block_minutes * 60
    max_failures = app_settings.brute_force_max_failures

    if ip:
        manager.record_failure(ip, window_seconds, max_failures, block_seconds)
    if username:
        manager.record_failure(f"user:{username}", window_seconds, max_failures, block_seconds)


def _record_brute_force_success(ip: str | None, username: str | None) -> None:
    manager = get_brute_force_manager()
    if ip:
        manager.record_success(ip)
    if username:
        manager.record_success(f"user:{username}")


@router.get("/bootstrap-status", response_model=BootstrapStatusResponse)
def bootstrap_status(db: Session = Depends(get_db)) -> BootstrapStatusResponse:
    has_admin_user = db.query(User.id).filter(User.is_admin.is_(True), User.is_active.is_(True)).first() is not None
    has_enabled_device = db.query(Device.id).filter(Device.enabled.is_(True)).first() is not None
    has_active_model = db.query(ModelConfig.id).filter(ModelConfig.activated.is_(True)).first() is not None
    app_settings = get_or_create_app_settings(db)
    settings = get_settings()
    setup_complete = _setup_complete_path().exists()
    public_url = app_settings.public_url or ""

    if not setup_complete and has_admin_user:
        _mark_setup_complete()
        setup_complete = True

    return BootstrapStatusResponse(
        requires_setup=not setup_complete,
        has_admin_user=has_admin_user,
        has_enabled_device=has_enabled_device,
        has_active_model=has_active_model,
        users_can_register=app_settings.users_can_register,
        sitename=app_settings.sitename,
        favicon_path=app_settings.favicon_path,
        logo_path=app_settings.logo_path,
        knowledge_base_enabled=app_settings.knowledge_base_enabled,
        cloudflare_turnstile_enabled=app_settings.cloudflare_turnstile_enabled,
        cloudflare_turnstile_site_key=app_settings.cloudflare_turnstile_site_key,
        public_url=public_url,
        api_base_url=build_api_base_url(public_url, settings.app_port),
    )


@router.post("/bootstrap-admin", response_model=LoginResponse)
def bootstrap_admin(payload: BootstrapAdminRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    ip = get_client_ip(request)
    app_settings = get_or_create_app_settings(db)
    _check_brute_force(ip, None, app_settings)

    try:
        if db.query(User.id).first() is not None:
            _record_brute_force_failure(ip, None, app_settings)
            raise HTTPException(status_code=409, detail="Initial admin has already been created")

        admin_user = User(
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password),
            is_admin=True,
            is_active=True,
            package_id=1,
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        scan_models_dir(db)
        log_event(db, "auth.bootstrap_admin", user_id=admin_user.id, username=admin_user.username, ip_address=get_client_ip(request))
        token = create_access_token(admin_user.username)
        _record_brute_force_success(ip, None)
        return LoginResponse(access_token=token)
    except HTTPException as exc:
        if exc.status_code not in (200,):
            _record_brute_force_failure(ip, None, app_settings)
        raise
    except IntegrityError as exc:
        db.rollback()
        logger.exception("Integrity error while bootstrapping admin user")
        raise HTTPException(status_code=409, detail="Username or email already exists") from exc
    except OperationalError as exc:
        db.rollback()
        logger.exception("Operational database error while bootstrapping admin user")
        message = str(exc).lower()
        if "readonly" in message:
            detail = "Database is read-only. Ensure ./data is writable by the backend container and retry."
        elif "no such table" in message or "has no column" in message:
            detail = "Database schema is missing or outdated. Recreate the database or run migrations, then retry."
        else:
            detail = "Database operational error while creating initial admin. Check backend logs and retry."
        raise HTTPException(status_code=500, detail=detail) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Database error while bootstrapping admin user")
        raise HTTPException(status_code=500, detail="Database error while creating initial admin") from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Unexpected error while bootstrapping admin user")
        raise HTTPException(status_code=500, detail="Unexpected server error while creating initial admin") from exc


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    ip = get_client_ip(request)
    app_settings = get_or_create_app_settings(db)
    _check_brute_force(ip, payload.username, app_settings)

    if app_settings.cloudflare_turnstile_enabled:
        if not payload.turnstile_response:
            log_event(db, "auth.login_failed", username=payload.username, ip_address=ip)
            raise HTTPException(status_code=400, detail="Cloudflare Turnstile verification is required")
        if app_settings.cloudflare_turnstile_secret_key:
            turnstile_valid = await verify_cloudflare_turnstile(
                app_settings.cloudflare_turnstile_secret_key,
                payload.turnstile_response,
                ip,
            )
            if not turnstile_valid:
                _record_brute_force_failure(ip, payload.username, app_settings)
                log_event(db, "auth.login_failed", username=payload.username, ip_address=ip)
                raise HTTPException(status_code=400, detail="Cloudflare Turnstile verification failed")

    user = db.query(User).filter(User.username == payload.username, User.is_active.is_(True)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        _record_brute_force_failure(ip, payload.username, app_settings)
        log_event(db, "auth.login_failed", username=payload.username, ip_address=ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    log_event(db, "auth.login", user_id=user.id, username=user.username, ip_address=ip)
    _record_brute_force_success(ip, payload.username)
    token = create_access_token(user.username)
    return LoginResponse(
        access_token=token,
        terms_accepted=user.terms_accepted_at is not None,
        terms_enabled=app_settings.terms_enabled,
    )


@router.post("/register", response_model=LoginResponse)
async def register(payload: UserRegistrationRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    ip = get_client_ip(request)
    app_settings = get_or_create_app_settings(db)
    _check_brute_force(ip, payload.username, app_settings)
    if not app_settings.users_can_register:
        _record_brute_force_failure(ip, payload.username, app_settings)
        raise HTTPException(status_code=403, detail="User registration is disabled")

    if app_settings.cloudflare_turnstile_enabled:
        if not payload.turnstile_response:
            _record_brute_force_failure(ip, payload.username, app_settings)
            log_event(db, "auth.register_failed", username=payload.username, ip_address=ip)
            raise HTTPException(status_code=400, detail="Cloudflare Turnstile verification is required")
        if app_settings.cloudflare_turnstile_secret_key:
            turnstile_valid = await verify_cloudflare_turnstile(
                app_settings.cloudflare_turnstile_secret_key,
                payload.turnstile_response,
                ip,
            )
            if not turnstile_valid:
                _record_brute_force_failure(ip, payload.username, app_settings)
                log_event(db, "auth.register_failed", username=payload.username, ip_address=ip)
                raise HTTPException(status_code=400, detail="Cloudflare Turnstile verification failed")

    existing_user = db.query(User.id).filter((User.username == payload.username) | (User.email == payload.email)).first()
    if existing_user is not None:
        _record_brute_force_failure(ip, payload.username, app_settings)
        raise HTTPException(status_code=409, detail="Username or email already exists")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        is_admin=False,
        is_active=True,
        package_id=2,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_event(db, "auth.register", user_id=user.id, username=user.username, ip_address=ip)
    _record_brute_force_success(ip, payload.username)
    token = create_access_token(user.username)
    return LoginResponse(
        access_token=token,
        terms_accepted=False,
        terms_enabled=app_settings.terms_enabled,
    )


@router.get("/me", response_model=UserResponse)
def current_user(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserResponse:
    package_name = None
    if current_user.package_id is not None:
        package = db.query(Package).filter(Package.id == current_user.package_id).first()
        if package:
            package_name = package.name
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_admin=current_user.is_admin,
        is_active=current_user.is_active,
        terms_accepted=current_user.terms_accepted_at is not None,
        package_id=current_user.package_id,
        package_name=package_name,
    )


@router.patch("/me", response_model=UserResponse)
def update_current_user(
    payload: ProfileUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    if payload.email is None and payload.password is None:
        raise HTTPException(status_code=400, detail="No profile changes were provided")

    email_changed = payload.email is not None
    password_changed = payload.password is not None

    if payload.email is not None:
        existing_user = (
            db.query(User)
            .filter(User.email == payload.email, User.id != current_user.id)
            .first()
        )
        if existing_user:
            raise HTTPException(status_code=409, detail="A user with that email already exists")
        current_user.email = payload.email

    if payload.password is not None:
        current_user.password_hash = hash_password(payload.password)

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    package_name = None
    if current_user.package_id is not None:
        package = db.query(Package).filter(Package.id == current_user.package_id).first()
        if package:
            package_name = package.name

    ip = get_client_ip(request)
    if email_changed:
        log_event(db, "auth.email_changed", user_id=current_user.id, username=current_user.username, ip_address=ip)
    if password_changed:
        log_event(db, "auth.password_changed", user_id=current_user.id, username=current_user.username, ip_address=ip)

    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_admin=current_user.is_admin,
        is_active=current_user.is_active,
        package_id=current_user.package_id,
        package_name=package_name,
    )


@router.get("/api-keys")
def list_api_keys(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == current_user.id)
        .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
        .all()
    )
    return [_serialize_api_key(api_key, current_user) for api_key in rows]


@router.post("/api-keys")
def create_api_key(payload: ApiKeyCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    plain_text_key = generate_api_key()
    api_key = ApiKey(user_id=current_user.id, name=payload.name, key_hash=hash_api_key(plain_text_key))
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"status": "ok", "api_key": _serialize_api_key(api_key, current_user), "plain_text_key": plain_text_key}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_id == current_user.id).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(api_key)
    db.commit()
    return {"status": "ok"}


def _serialize_api_key(api_key: ApiKey, user: User) -> dict:
    return {
        "id": api_key.id,
        "user_id": api_key.user_id,
        "user_username": user.username,
        "name": api_key.name,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
    }


def _setup_complete_path() -> Path:
    settings = get_settings()
    return Path(settings.data_dir) / ".setup-complete"


def _mark_setup_complete() -> None:
    flag_path = _setup_complete_path()
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text("complete\n", encoding="utf-8")
