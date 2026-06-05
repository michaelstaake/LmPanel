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
        import docker  # type: ignore

        client = docker.from_env()
        containers = client.containers.list(all=True)
        names = sorted(
            c.name for c in containers if c.name.startswith("lmpanel-")
        )
        return {"containers": names}
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
        import docker  # type: ignore
        import docker.errors  # type: ignore

        client = docker.from_env()
        try:
            container = client.containers.get(container_name)
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Container '{container_name}' not found")

        raw: bytes = container.logs(tail=tail, timestamps=True)
        lines = raw.decode("utf-8", errors="replace").splitlines()
        return {"container": container_name, "lines": lines}
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
