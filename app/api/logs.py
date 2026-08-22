import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.core.db import get_db
from app.models.activity_log import ActivityLog
from app.models.user import User

router = APIRouter(prefix="/api/logs", tags=["logs"])

CATEGORY_PREFIXES: dict[str, str] = {
    "auth": "auth.%",
    "models": "model.%",
    "devices": "device.%",
    "chat": "chat.%",
    "admin": "admin.%",
}


def _docker_control_url(path: str) -> str:
    base_url = os.environ.get("DOCKER_CONTROL_URL", "http://docker-control:2375").rstrip("/")
    return f"{base_url}/{path.lstrip('/')}"


def _docker_control_headers() -> dict[str, str]:
    secret = os.environ.get("DOCKER_CONTROL_SECRET", "").strip()
    return {"X-Docker-Control-Secret": secret} if secret else {}


@router.get("")
def list_logs(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    event_category: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> dict:
    query = db.query(ActivityLog)

    if event_category and event_category in CATEGORY_PREFIXES:
        query = query.filter(ActivityLog.event_type.like(CATEGORY_PREFIXES[event_category]))

    if search:
        term = f"%{search}%"
        query = query.filter(
            ActivityLog.username.like(term)
            | ActivityLog.details.like(term)
            | ActivityLog.event_type.like(term)
        )

    total = query.count()
    items = (
        query.order_by(ActivityLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize(item) for item in items],
    }


@router.get("/docker/containers")
def list_docker_containers(
    _: User = Depends(get_admin_user),
) -> dict:
    try:
        response = httpx.get(
            _docker_control_url("/containers"),
            headers=_docker_control_headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


@router.get("/docker/{container_name}")
def get_docker_logs(
    container_name: str,
    _: User = Depends(get_admin_user),
    tail: int = Query(default=200, ge=1, le=1000),
) -> dict:
    if not container_name.startswith("lmpanel-"):
        raise HTTPException(status_code=400, detail="Invalid container name")

    try:
        response = httpx.get(
            _docker_control_url(f"/containers/{container_name}/logs"),
            params={"tail": tail},
            headers=_docker_control_headers(),
            timeout=15.0,
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Container '{container_name}' not found")
        response.raise_for_status()
        return response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


def _serialize(log: ActivityLog) -> dict:
    return {
        "id": log.id,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "event_type": log.event_type,
        "user_id": log.user_id,
        "username": log.username,
        "ip_address": log.ip_address,
        "details": log.details,
    }
