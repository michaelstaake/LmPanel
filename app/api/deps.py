from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import hash_api_key
from app.models.api_key import ApiKey
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def _build_anonymous_api_user() -> User:
    return User(
        username="anonymous",
        email="anonymous@local",
        password_hash="",
        is_admin=False,
        is_active=True,
    )


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    credentials_exception = HTTPException(status_code=401, detail="Invalid credentials")
    if not credentials:
        raise credentials_exception

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str | None = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError as exc:
        api_key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(token)).first()
        if not api_key:
            raise credentials_exception from exc

        user = db.query(User).filter(User.id == api_key.user_id, User.is_active.is_(True)).first()
        if not user:
            raise credentials_exception

        api_key.last_used_at = datetime.now(UTC)
        db.add(api_key)
        db.commit()
        return user

    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
    if not user:
        raise credentials_exception
    return user


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if not credentials:
        return None

    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def require_api_access(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme), db: Session = Depends(get_db)) -> User:
    if not get_settings().openai_api_auth_required:
        if credentials is None:
            return _build_anonymous_api_user()

        try:
            return get_current_user(credentials, db)
        except HTTPException:
            return _build_anonymous_api_user()

    return get_current_user(credentials, db)


def require_models_api_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not get_settings().openai_models_auth_required:
        if credentials is None:
            return _build_anonymous_api_user()

        try:
            return get_current_user(credentials, db)
        except HTTPException:
            return _build_anonymous_api_user()

    return get_current_user(credentials, db)
