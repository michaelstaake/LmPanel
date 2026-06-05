import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.activity_log import ActivityLog

logger = logging.getLogger(__name__)


def log_event(
    db: Session,
    event_type: str,
    user_id: int | None = None,
    username: str | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    try:
        entry = ActivityLog(
            event_type=event_type,
            user_id=user_id,
            username=username,
            ip_address=ip_address,
            details=json.dumps(details) if details else None,
        )
        db.add(entry)
        db.commit()
    except Exception:
        logger.exception("Failed to write activity log entry (event_type=%s)", event_type)
        try:
            db.rollback()
        except Exception:
            pass


def prune_old_logs(db: Session) -> int:
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        deleted = db.query(ActivityLog).filter(ActivityLog.created_at < cutoff).delete()
        db.commit()
        return deleted
    except Exception:
        logger.warning("Log pruning skipped — activity_logs table may not exist yet")
        try:
            db.rollback()
        except Exception:
            pass
        return 0


async def schedule_daily_pruning() -> None:
    while True:
        await asyncio.sleep(86400)
        db = SessionLocal()
        try:
            deleted = prune_old_logs(db)
            logger.info("Daily log pruning: removed %d entries older than 30 days", deleted)
        except Exception:
            logger.exception("Daily log pruning failed")
        finally:
            db.close()
