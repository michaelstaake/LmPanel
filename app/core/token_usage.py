from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.token_usage import TokenUsage
from app.models.user import User


PROCESS_STARTED_AT = datetime.now(timezone.utc)


def _coalesce_token_count(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None

    return value


def normalize_token_usage(
    total_tokens: int | None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> tuple[int, int, int] | None:
    normalized_input_tokens = _coalesce_token_count(input_tokens) or 0
    normalized_output_tokens = _coalesce_token_count(output_tokens) or 0
    normalized_total_tokens = _coalesce_token_count(total_tokens)

    if normalized_total_tokens is None:
        normalized_total_tokens = normalized_input_tokens + normalized_output_tokens

    if normalized_total_tokens <= 0 and normalized_input_tokens <= 0 and normalized_output_tokens <= 0:
        return None

    return normalized_total_tokens, normalized_input_tokens, normalized_output_tokens


def record_token_usage(
    db: Session,
    *,
    user_id: int | None,
    total_tokens: int | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    tool_calls: int = 0,
) -> bool:
    normalized_usage = normalize_token_usage(
        total_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    normalized_tool_calls = max(0, int(tool_calls or 0))
    if normalized_usage is None:
        if normalized_tool_calls <= 0:
            return False
        normalized_total_tokens, normalized_input_tokens, normalized_output_tokens = 0, 0, 0
    else:
        normalized_total_tokens, normalized_input_tokens, normalized_output_tokens = normalized_usage
    db.add(
        TokenUsage(
            user_id=user_id if user_id and user_id > 0 else None,
            total_tokens=normalized_total_tokens,
            input_tokens=normalized_input_tokens,
            output_tokens=normalized_output_tokens,
            tool_calls=normalized_tool_calls,
        )
    )
    db.commit()
    return True


def build_token_usage_summary(db: Session) -> dict:
    now = datetime.now(timezone.utc)

    return {
        "since_startup": _aggregate_token_usage(db, since=PROCESS_STARTED_AT),
        "last_1_hour": _aggregate_token_usage(db, since=now - timedelta(hours=1)),
        "last_24_hours": _aggregate_token_usage(db, since=now - timedelta(hours=24)),
        "last_7_days": _aggregate_token_usage(db, since=now - timedelta(days=7)),
        "last_30_days": _aggregate_token_usage(db, since=now - timedelta(days=30)),
        "forever": _aggregate_token_usage(db),
        "top_user_last_24_hours": _aggregate_top_user(db, since=now - timedelta(hours=24)),
        "top_user_forever": _aggregate_top_user(db),
    }


def _aggregate_token_usage(db: Session, *, since: datetime | None = None) -> dict:
    query = db.query(
        func.coalesce(func.sum(TokenUsage.total_tokens), 0),
        func.coalesce(func.sum(TokenUsage.input_tokens), 0),
        func.coalesce(func.sum(TokenUsage.output_tokens), 0),
    )
    if since is not None:
        query = query.filter(TokenUsage.created_at >= since)

    total_tokens, input_tokens, output_tokens = query.one()
    return {
        "total_tokens": int(total_tokens or 0),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
    }


def _aggregate_top_user(db: Session, *, since: datetime | None = None) -> dict | None:
    query = (
        db.query(
            User.username.label("username"),
            func.coalesce(func.sum(TokenUsage.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(TokenUsage.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(TokenUsage.output_tokens), 0).label("output_tokens"),
        )
        .join(User, User.id == TokenUsage.user_id)
        .filter(TokenUsage.user_id.is_not(None))
        .group_by(User.id, User.username)
        .order_by(desc("total_tokens"), User.username.asc())
    )
    if since is not None:
        query = query.filter(TokenUsage.created_at >= since)

    row = query.first()
    if row is None or int(row.total_tokens or 0) <= 0:
        return None

    return {
        "username": row.username,
        "total_tokens": int(row.total_tokens or 0),
        "input_tokens": int(row.input_tokens or 0),
        "output_tokens": int(row.output_tokens or 0),
    }


def get_user_token_usage(db: Session, *, user_ids: list[int], input_price_per_1m: float = 0.0, output_price_per_1m: float = 0.0) -> list[dict]:
    now = datetime.now(timezone.utc)
    periods = {
        "last_60_minutes": now - timedelta(hours=1),
        "last_24_hours": now - timedelta(hours=24),
        "last_7_days": now - timedelta(days=7),
        "last_30_days": now - timedelta(days=30),
        "forever": None,
    }

    users = db.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u for u in users}

    user_ids_with_usage = [uid for uid in user_ids if uid in user_map]

    if not user_ids_with_usage:
        return []

    result = []
    for uid in user_ids:
        user = user_map.get(uid)
        if not user:
            continue

        user_data = {
            "user_id": uid,
            "username": user.username,
            "last_60_minutes": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0},
            "last_24_hours": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0},
            "last_7_days": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0},
            "last_30_days": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0},
            "forever": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0},
        }

        for period_name, since in periods.items():
            query = (
                db.query(
                    func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                    func.coalesce(func.sum(TokenUsage.output_tokens), 0),
                )
                .filter(TokenUsage.user_id == uid)
            )
            if since is not None:
                query = query.filter(TokenUsage.created_at >= since)

            total, input_tokens, output_tokens = query.one()
            user_data[period_name] = {
                "total_tokens": int(total or 0),
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
            }

        total_input = user_data["forever"]["input_tokens"]
        total_output = user_data["forever"]["output_tokens"]
        user_data["estimated_cost"] = round((total_input / 1_000_000) * input_price_per_1m + (total_output / 1_000_000) * output_price_per_1m, 6)

        result.append(user_data)

    return result


def get_user_tool_usage(db: Session, *, user_ids: list[int]) -> list[dict]:
    now = datetime.now(timezone.utc)
    periods = {
        "last_60_minutes": now - timedelta(hours=1),
        "last_24_hours": now - timedelta(hours=24),
        "last_7_days": now - timedelta(days=7),
        "last_30_days": now - timedelta(days=30),
        "forever": None,
    }

    users = db.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u for u in users}

    user_ids_with_usage = [uid for uid in user_ids if uid in user_map]

    if not user_ids_with_usage:
        return []

    result = []
    for uid in user_ids:
        user = user_map.get(uid)
        if not user:
            continue

        user_data = {
            "user_id": uid,
            "username": user.username,
            "last_60_minutes": {"web_searches": 0},
            "last_24_hours": {"web_searches": 0},
            "last_7_days": {"web_searches": 0},
            "last_30_days": {"web_searches": 0},
            "forever": {"web_searches": 0},
        }

        for period_name, since in periods.items():
            query = (
                db.query(
                    func.coalesce(func.sum(TokenUsage.tool_calls), 0),
                )
                .filter(TokenUsage.user_id == uid)
            )
            if since is not None:
                query = query.filter(TokenUsage.created_at >= since)

            tool_calls = query.one()
            user_data[period_name] = {
                "web_searches": int(tool_calls[0] or 0),
            }

        result.append(user_data)

    return result