import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.core.activity_logger import log_event
from app.core.app_settings import get_or_create_app_settings
from app.core.config import get_settings
from app.core.db import get_db
from app.core.letsencrypt import (
    can_use_letsencrypt,
    issue_certificate,
    parse_domain_from_public_url,
    read_cert_status,
    reload_tls_services,
    renew_certificate,
    resolve_cloudflare_token,
    resolve_letsencrypt_email,
)
from app.core.task_manager import task_manager
from app.models.user import User
from app.utils.schemas import SslSettingsUpdateRequest, SslStatusResponse

router = APIRouter(prefix="/api/admin/ssl", tags=["ssl"])
logger = logging.getLogger(__name__)


def _build_ssl_status(app_settings) -> SslStatusResponse:
    settings = get_settings()
    public_url = app_settings.public_url or ""
    cloudflare_token = resolve_cloudflare_token(settings, app_settings.cloudflare_api_token)
    email = resolve_letsencrypt_email(settings, app_settings.letsencrypt_email)
    expected_domain = None
    if public_url:
        try:
            expected_domain = parse_domain_from_public_url(public_url)
        except ValueError:
            expected_domain = None

    certificate = read_cert_status(
        Path(settings.ssl_certfile),
        Path(settings.ssl_keyfile),
        expected_domain=expected_domain,
    )

    return SslStatusResponse(
        public_url=public_url,
        letsencrypt_available=can_use_letsencrypt(public_url, bool(cloudflare_token), bool(email)),
        cloudflare_api_token_set=bool(cloudflare_token),
        letsencrypt_email_set=bool(email),
        certificate=certificate,
    )


def _validate_letsencrypt_prerequisites(app_settings, *, require_email: bool = True) -> tuple[str, str, str]:
    settings = get_settings()
    public_url = app_settings.public_url or ""
    cloudflare_token = resolve_cloudflare_token(settings, app_settings.cloudflare_api_token)
    email = resolve_letsencrypt_email(settings, app_settings.letsencrypt_email)

    if not public_url:
        raise ValueError("Set the public URL in Configuration before using Let's Encrypt")
    if not cloudflare_token:
        raise ValueError("Configure a Cloudflare API token before using Let's Encrypt")
    if require_email and not email:
        raise ValueError("Configure a Let's Encrypt account email before obtaining a certificate")

    try:
        domain = parse_domain_from_public_url(public_url)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    return domain, email or "", cloudflare_token


def _validate_letsencrypt_prerequisites_http(app_settings, *, require_email: bool = True) -> tuple[str, str, str]:
    try:
        return _validate_letsencrypt_prerequisites(app_settings, require_email=require_email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _run_ssl_job(
    task_id: str,
    *,
    renew_only: bool,
    admin_user_id: int,
    admin_username: str,
) -> None:
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        app_settings = get_or_create_app_settings(db)
        domain, email, cloudflare_token = _validate_letsencrypt_prerequisites(app_settings)
        settings = get_settings()

        def _execute() -> None:
            if renew_only:
                renew_certificate(domain, cloudflare_token, settings)
            else:
                issue_certificate(domain, email, cloudflare_token, settings)
                reload_tls_services(settings)

        await asyncio.to_thread(_execute)
        log_event(
            db,
            "ssl.cert_renewed" if renew_only else "ssl.cert_issued",
            user_id=admin_user_id,
            username=admin_username,
            details={"domain": domain},
        )
        task_manager.complete_task(task_id)
    except Exception as exc:
        logger.exception("SSL Let's Encrypt task failed")
        log_event(
            db,
            "ssl.cert_renew_failed" if renew_only else "ssl.cert_issue_failed",
            user_id=admin_user_id,
            username=admin_username,
            details={"error": str(exc)},
        )
        task_manager.fail_task(task_id, str(exc))
    finally:
        db.close()


@router.get("/status", response_model=SslStatusResponse)
def get_ssl_status(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> SslStatusResponse:
    app_settings = get_or_create_app_settings(db)
    return _build_ssl_status(app_settings)


@router.patch("/settings", response_model=SslStatusResponse)
def update_ssl_settings(
    payload: SslSettingsUpdateRequest,
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> SslStatusResponse:
    app_settings = get_or_create_app_settings(db)

    if payload.letsencrypt_email is not None:
        app_settings.letsencrypt_email = payload.letsencrypt_email or None
    if payload.cloudflare_api_token is not None:
        app_settings.cloudflare_api_token = payload.cloudflare_api_token or None

    db.add(app_settings)
    db.commit()
    db.refresh(app_settings)
    log_event(db, "admin.ssl_settings_changed", user_id=admin_user.id, username=admin_user.username)
    return _build_ssl_status(app_settings)


async def _start_ssl_task(
    *,
    renew_only: bool,
    admin_user: User,
    db: Session,
) -> dict:
    app_settings = get_or_create_app_settings(db)
    _validate_letsencrypt_prerequisites_http(app_settings, require_email=not renew_only)

    task_id = str(uuid.uuid4())
    description = "Renewing Let's Encrypt certificate" if renew_only else "Obtaining Let's Encrypt certificate"
    async_task = asyncio.create_task(
        _run_ssl_job(
            task_id,
            renew_only=renew_only,
            admin_user_id=admin_user.id,
            admin_username=admin_user.username,
        )
    )
    task_manager.add_task(
        task_id=task_id,
        task_type="ssl_letsencrypt",
        description=description,
        async_task=async_task,
    )
    return {"status": "ok", "task_id": task_id}


@router.post("/letsencrypt")
async def obtain_letsencrypt_certificate(
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    return await _start_ssl_task(renew_only=False, admin_user=admin_user, db=db)


@router.post("/renew")
async def renew_letsencrypt_certificate(
    admin_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    return await _start_ssl_task(renew_only=True, admin_user=admin_user, db=db)
