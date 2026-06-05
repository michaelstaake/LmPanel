import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
from jose import jwt

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def generate_api_key() -> str:
    return f"ppk_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(api_key: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(api_key), key_hash)


async def verify_cloudflare_turnstile(secret_key: str, token: str, remote_ip: str | None = None) -> bool:
    if not token.strip():
        return False

    form_data: dict[str, str] = {
        "secret": secret_key,
        "response": token,
    }
    if remote_ip:
        form_data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data=form_data,
            )
            data = response.json()
    except Exception:
        logger.exception("Cloudflare Turnstile siteverify request failed")
        return False

    error_codes = data.get("error-codes", [])
    if not data.get("success"):
        logger.warning(
            "Cloudflare Turnstile verification failed: %s",
            error_codes,
            extra={"error_codes": error_codes, "hostname": data.get("hostname")},
        )
        return False

    logger.info(
        "Cloudflare Turnstile verification succeeded",
        extra={"hostname": data.get("hostname"), "action": data.get("action")},
    )
    return True
