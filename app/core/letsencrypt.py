from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.backends import default_backend

from app.core.config import Settings, get_settings
from app.utils.schemas import normalize_public_url

logger = logging.getLogger(__name__)

RENEWAL_THRESHOLD_DAYS = 30


def parse_domain_from_public_url(public_url: str) -> str:
    normalized = normalize_public_url(public_url)
    if not normalized:
        raise ValueError("Public URL is not configured")
    parsed = urlparse(normalized)
    if not parsed.hostname:
        raise ValueError("Public URL must include a hostname")
    return parsed.hostname


def can_use_letsencrypt(public_url: str, has_cloudflare_token: bool, has_email: bool) -> bool:
    try:
        parse_domain_from_public_url(public_url)
    except ValueError:
        return False
    return has_cloudflare_token and has_email


def resolve_cloudflare_token(settings: Settings, stored_token: str | None) -> str | None:
    env_token = settings.cloudflare_api_token.strip()
    if env_token:
        return env_token
    if stored_token and stored_token.strip():
        return stored_token.strip()
    return None


def resolve_letsencrypt_email(settings: Settings, stored_email: str | None) -> str | None:
    env_email = settings.letsencrypt_email.strip()
    if env_email:
        return env_email
    if stored_email and stored_email.strip():
        return stored_email.strip()
    return None


def read_cert_status(cert_path: Path, key_path: Path, expected_domain: str | None = None) -> dict | None:
    if not cert_path.exists() or not key_path.exists():
        return None

    try:
        pem_data = cert_path.read_bytes()
        certificate = x509.load_pem_x509_certificate(pem_data, default_backend())
    except Exception:
        logger.exception("Failed to read certificate at %s", cert_path)
        return None

    issuer_parts = []
    for attribute in certificate.issuer:
        issuer_parts.append(f"{attribute.oid}={attribute.value}")
    issuer = ", ".join(issuer_parts)

    subject_cn = None
    for attribute in certificate.subject:
        if attribute.oid == x509.oid.NameOID.COMMON_NAME:
            subject_cn = attribute.value
            break

    san_names: list[str] = []
    try:
        san_extension = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        san_names = [name.value for name in san_extension.value if isinstance(name.value, str)]
    except x509.ExtensionNotFound:
        pass

    not_after = certificate.not_valid_after_utc
    now = datetime.now(timezone.utc)
    days_remaining = max(0, (not_after - now).days)
    is_self_signed = certificate.issuer == certificate.subject
    is_lets_encrypt = any("letsencrypt" in part.lower() for part in issuer_parts)

    domain_matches = True
    if expected_domain:
        names = set(san_names)
        if subject_cn:
            names.add(subject_cn)
        domain_matches = expected_domain in names

    return {
        "subject": subject_cn,
        "issuer": issuer,
        "not_after": not_after.isoformat(),
        "days_remaining": days_remaining,
        "is_self_signed": is_self_signed,
        "is_lets_encrypt": is_lets_encrypt,
        "san_names": san_names,
        "domain_matches": domain_matches,
    }


def _certbot_paths(settings: Settings) -> tuple[Path, Path, Path]:
    config_dir = Path(settings.resolved_letsencrypt_config_dir())
    config_dir.mkdir(parents=True, exist_ok=True)
    work_dir = config_dir / "work"
    logs_dir = config_dir / "logs"
    work_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    return config_dir, work_dir, logs_dir


def _cloudflare_credentials_path(settings: Settings) -> Path:
    config_dir = Path(settings.resolved_letsencrypt_config_dir())
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "cloudflare.ini"


def _write_cloudflare_credentials(path: Path, api_token: str) -> None:
    path.write_text(f"dns_cloudflare_api_token = {api_token}\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _remove_cloudflare_credentials(path: Path) -> None:
    if path.exists():
        path.unlink()


def _run_certbot(args: list[str], settings: Settings) -> None:
    config_dir, work_dir, logs_dir = _certbot_paths(settings)
    command = [
        "certbot",
        *args,
        "--non-interactive",
        "--agree-tos",
        f"--config-dir={config_dir}",
        f"--work-dir={work_dir}",
        f"--logs-dir={logs_dir}",
    ]
    if settings.letsencrypt_use_staging:
        command.append("--staging")

    logger.info("Running certbot: %s", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "certbot failed").strip()
        raise RuntimeError(detail)


def _install_certificate(domain: str, settings: Settings) -> None:
    config_dir = Path(settings.resolved_letsencrypt_config_dir())
    live_dir = config_dir / "live" / domain
    fullchain = live_dir / "fullchain.pem"
    privkey = live_dir / "privkey.pem"
    if not fullchain.exists() or not privkey.exists():
        raise RuntimeError(f"Certificate files were not created for {domain}")

    cert_destination = Path(settings.ssl_certfile)
    key_destination = Path(settings.ssl_keyfile)
    cert_destination.parent.mkdir(parents=True, exist_ok=True)
    key_destination.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(fullchain, cert_destination)
    shutil.copy2(privkey, key_destination)
    try:
        os.chmod(key_destination, 0o600)
    except OSError:
        logger.warning("Could not set permissions on %s", key_destination)


def issue_certificate(domain: str, email: str, api_token: str, settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    credentials_path = _cloudflare_credentials_path(active_settings)
    _write_cloudflare_credentials(credentials_path, api_token)
    try:
        _run_certbot(
            [
                "certonly",
                "--dns-cloudflare",
                f"--dns-cloudflare-credentials={credentials_path}",
                "-d",
                domain,
                "--email",
                email,
            ],
            active_settings,
        )
        _install_certificate(domain, active_settings)
    finally:
        _remove_cloudflare_credentials(credentials_path)


def _renew_certificate(
    domain: str,
    api_token: str,
    settings: Settings,
    *,
    force: bool = False,
) -> bool:
    cert_path = Path(settings.ssl_certfile)
    key_path = Path(settings.ssl_keyfile)
    status = read_cert_status(cert_path, key_path, expected_domain=domain)
    if (
        not force
        and status
        and status.get("is_lets_encrypt")
        and status.get("days_remaining", 0) > RENEWAL_THRESHOLD_DAYS
    ):
        return False

    credentials_path = _cloudflare_credentials_path(settings)
    _write_cloudflare_credentials(credentials_path, api_token)
    try:
        _run_certbot(
            [
                "renew",
                "--dns-cloudflare",
                f"--dns-cloudflare-credentials={credentials_path}",
            ],
            settings,
        )
        _install_certificate(domain, settings)
        return True
    finally:
        _remove_cloudflare_credentials(credentials_path)


def renew_if_needed(
    domain: str,
    email: str,
    api_token: str,
    settings: Settings | None = None,
) -> bool:
    active_settings = settings or get_settings()
    renewed = _renew_certificate(domain, api_token, active_settings, force=False)
    if renewed:
        reload_tls_services(active_settings)
    return renewed


def renew_certificate(
    domain: str,
    api_token: str,
    settings: Settings | None = None,
) -> None:
    active_settings = settings or get_settings()
    _renew_certificate(domain, api_token, active_settings, force=True)
    reload_tls_services(active_settings)


async def schedule_daily_ssl_renewal() -> None:
    while True:
        await asyncio.sleep(86400)
        try:
            from app.core.db import SessionLocal
            from app.core.app_settings import get_or_create_app_settings

            db = SessionLocal()
            try:
                app_settings = get_or_create_app_settings(db)
                settings = get_settings()
                public_url = app_settings.public_url or ""
                cloudflare_token = resolve_cloudflare_token(settings, app_settings.cloudflare_api_token)
                email = resolve_letsencrypt_email(settings, app_settings.letsencrypt_email)
                if not can_use_letsencrypt(public_url, bool(cloudflare_token), bool(email)):
                    continue

                domain = parse_domain_from_public_url(public_url)
                renewed = await asyncio.to_thread(
                    renew_if_needed,
                    domain,
                    email or "",
                    cloudflare_token or "",
                    settings,
                )
                if renewed:
                    from app.core.activity_logger import log_event as write_log

                    write_log(db, "ssl.cert_renewed", details={"domain": domain, "source": "scheduler"})
                    logger.info("Renewed Let's Encrypt certificate for %s", domain)
            finally:
                db.close()
        except Exception as exc:
            logger.exception("Daily SSL renewal check failed")
            try:
                from app.core.db import SessionLocal
                from app.core.activity_logger import log_event as write_log

                db = SessionLocal()
                try:
                    write_log(db, "ssl.cert_renew_failed", details={"error": str(exc), "source": "scheduler"})
                finally:
                    db.close()
            except Exception:
                logger.exception("Failed to write SSL renewal failure log")


def reload_tls_services(settings: Settings | None = None) -> None:
    active_settings = settings or get_settings()
    try:
        import docker  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Docker SDK is not available") from exc

    client = docker.from_env()
    frontend = client.containers.get(active_settings.docker_frontend_container)
    frontend.exec_run(["nginx", "-s", "reload"])

    backend = client.containers.get(active_settings.docker_backend_container)
    backend.restart(timeout=30)
