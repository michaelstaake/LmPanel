from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.package import Package
from app.models.token_usage import TokenUsage
from app.models.user import User

USAGE_PERIOD_SPECS: tuple[tuple[str, str, timedelta], ...] = (
    ("60_minutes", "usage_limit_tokens_60_minutes", timedelta(minutes=60)),
    ("24_hours", "usage_limit_tokens_24_hours", timedelta(hours=24)),
    ("7_days", "usage_limit_tokens_7_days", timedelta(days=7)),
    ("30_days", "usage_limit_tokens_30_days", timedelta(days=30)),
)

TOOL_USAGE_PERIOD_SPECS: tuple[tuple[str, str, timedelta], ...] = (
    ("60_minutes", "usage_limit_tools_60_minutes", timedelta(minutes=60)),
    ("24_hours", "usage_limit_tools_24_hours", timedelta(hours=24)),
    ("7_days", "usage_limit_tools_7_days", timedelta(days=7)),
    ("30_days", "usage_limit_tools_30_days", timedelta(days=30)),
)


def _as_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class UsageLimitCheckResult:
    allowed: bool
    at_limit: bool
    detail: str | None = None


def get_usage_limit_values(app_settings: AppSettings) -> dict[str, int]:
    return {
        period_id: max(0, int(getattr(app_settings, limit_attr, 0) or 0))
        for period_id, limit_attr, _ in USAGE_PERIOD_SPECS
    }


def get_tool_usage_limit_values(app_settings: AppSettings) -> dict[str, int]:
    return {
        period_id: max(0, int(getattr(app_settings, limit_attr, 0) or 0))
        for period_id, limit_attr, _ in TOOL_USAGE_PERIOD_SPECS
    }


def get_package_usage_limit_values(package: Package) -> dict[str, int]:
    return {
        period_id: max(0, int(getattr(package, limit_attr, 0) or 0))
        for period_id, limit_attr, _ in USAGE_PERIOD_SPECS
    }


def get_package_tool_usage_limit_values(package: Package) -> dict[str, int]:
    return {
        period_id: max(0, int(getattr(package, limit_attr, 0) or 0))
        for period_id, limit_attr, _ in TOOL_USAGE_PERIOD_SPECS
    }


def are_usage_limits_enabled(app_settings: AppSettings) -> bool:
    return any(value > 0 for value in get_usage_limit_values(app_settings).values())


def are_tool_usage_limits_enabled(app_settings: AppSettings) -> bool:
    return any(value > 0 for value in get_tool_usage_limit_values(app_settings).values())


def are_package_usage_limits_enabled(package: Package) -> bool:
    return any(value > 0 for value in get_package_usage_limit_values(package).values())


def are_package_tool_usage_limits_enabled(package: Package) -> bool:
    return any(value > 0 for value in get_package_tool_usage_limit_values(package).values())


def validate_usage_limit_values(
    *,
    usage_limit_tokens_60_minutes: int,
    usage_limit_tokens_24_hours: int,
    usage_limit_tokens_7_days: int,
    usage_limit_tokens_30_days: int,
) -> None:
    values = {
        "60_minutes": usage_limit_tokens_60_minutes,
        "24_hours": usage_limit_tokens_24_hours,
        "7_days": usage_limit_tokens_7_days,
        "30_days": usage_limit_tokens_30_days,
    }

    for period_id, value in values.items():
        if value < 0:
            raise ValueError(f"Usage limit for {period_id.replace('_', ' ')} must be zero or greater")

    enabled_periods = [(period_id, limit_attr, window) for period_id, limit_attr, window in USAGE_PERIOD_SPECS if values[period_id] > 0]
    for shorter_index in range(len(enabled_periods)):
        shorter_id, _, _ = enabled_periods[shorter_index]
        shorter_limit = values[shorter_id]
        for longer_index in range(shorter_index + 1, len(enabled_periods)):
            longer_id, _, _ = enabled_periods[longer_index]
            longer_limit = values[longer_id]
            if longer_limit < shorter_limit:
                shorter_label = shorter_id.replace("_", " ")
                longer_label = longer_id.replace("_", " ")
                raise ValueError(
                    f"The {longer_label} token limit cannot be lower than the {shorter_label} limit when both are enabled"
                )


def validate_tool_usage_limit_values(
    *,
    usage_limit_tools_60_minutes: int,
    usage_limit_tools_24_hours: int,
    usage_limit_tools_7_days: int,
    usage_limit_tools_30_days: int,
) -> None:
    values = {
        "60_minutes": usage_limit_tools_60_minutes,
        "24_hours": usage_limit_tools_24_hours,
        "7_days": usage_limit_tools_7_days,
        "30_days": usage_limit_tools_30_days,
    }

    for period_id, value in values.items():
        if value < 0:
            raise ValueError(f"Tool usage limit for {period_id.replace('_', ' ')} must be zero or greater")

    enabled_periods = [(period_id, limit_attr, window) for period_id, limit_attr, window in TOOL_USAGE_PERIOD_SPECS if values[period_id] > 0]
    for shorter_index in range(len(enabled_periods)):
        shorter_id, _, _ = enabled_periods[shorter_index]
        shorter_limit = values[shorter_id]
        for longer_index in range(shorter_index + 1, len(enabled_periods)):
            longer_id, _, _ = enabled_periods[longer_index]
            longer_limit = values[longer_id]
            if longer_limit < shorter_limit:
                shorter_label = shorter_id.replace("_", " ")
                longer_label = longer_id.replace("_", " ")
                raise ValueError(
                    f"The {longer_label} tool usage limit cannot be lower than the {shorter_label} limit when both are enabled"
                )


def get_user_token_usage_by_period(db: Session, *, user_id: int) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    usage: dict[str, int] = {}
    for period_id, _, window in USAGE_PERIOD_SPECS:
        since = now - window
        total_tokens, _, _ = (
            db.query(
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0),
            )
            .filter(TokenUsage.user_id == user_id, TokenUsage.created_at >= since)
            .one()
        )
        usage[period_id] = int(total_tokens or 0)
    return usage


def get_user_tool_usage_by_period(db: Session, *, user_id: int) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    usage: dict[str, int] = {}
    for period_id, _, window in TOOL_USAGE_PERIOD_SPECS:
        since = now - window
        total_tool_calls, _, _ = (
            db.query(
                func.coalesce(func.sum(TokenUsage.tool_calls), 0),
                func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                func.coalesce(func.sum(TokenUsage.output_tokens), 0),
            )
            .filter(TokenUsage.user_id == user_id, TokenUsage.created_at >= since)
            .one()
        )
        usage[period_id] = int(total_tool_calls or 0)
    return usage


def get_user_oldest_token_timestamp_by_period(db: Session, *, user_id: int) -> dict[str, datetime | None]:
    now = datetime.now(timezone.utc)
    oldest: dict[str, datetime | None] = {}
    for period_id, _, window in USAGE_PERIOD_SPECS:
        since = now - window
        result = (
            db.query(func.min(TokenUsage.created_at))
            .filter(TokenUsage.user_id == user_id, TokenUsage.created_at >= since)
            .scalar()
        )
        oldest[period_id] = result
    return oldest


def get_user_oldest_tool_timestamp_by_period(db: Session, *, user_id: int) -> dict[str, datetime | None]:
    now = datetime.now(timezone.utc)
    oldest: dict[str, datetime | None] = {}
    for period_id, _, window in TOOL_USAGE_PERIOD_SPECS:
        since = now - window
        result = (
            db.query(func.min(TokenUsage.created_at))
            .filter(
                TokenUsage.user_id == user_id,
                TokenUsage.created_at >= since,
                TokenUsage.tool_calls > 0,
            )
            .scalar()
        )
        oldest[period_id] = result
    return oldest


def is_user_over_usage_limit(db: Session, *, user: User, app_settings: AppSettings) -> bool:
    if user.is_admin:
        return False

    if user.package_id is not None:
        package = db.query(Package).filter(Package.id == user.package_id).first()
        if package:
            limits = get_package_usage_limit_values(package)
            if any(limit > 0 for limit in limits.values()):
                user_id = getattr(user, "id", None)
                if not user_id or user_id <= 0:
                    return False
                usage = get_user_token_usage_by_period(db, user_id=user_id)
                for period_id, limit in limits.items():
                    if limit > 0 and usage[period_id] >= limit:
                        return True
            return False

    limits = get_usage_limit_values(app_settings)
    if not any(limit > 0 for limit in limits.values()):
        return False

    user_id = getattr(user, "id", None)
    if not user_id or user_id <= 0:
        return False

    usage = get_user_token_usage_by_period(db, user_id=user_id)
    for period_id, limit in limits.items():
        if limit > 0 and usage[period_id] >= limit:
            return True
    return False


def is_user_over_tool_usage_limit(db: Session, *, user: User, app_settings: AppSettings) -> bool:
    if user.is_admin:
        return False

    if user.package_id is not None:
        package = db.query(Package).filter(Package.id == user.package_id).first()
        if package:
            limits = get_package_tool_usage_limit_values(package)
            if any(limit > 0 for limit in limits.values()):
                user_id = getattr(user, "id", None)
                if not user_id or user_id <= 0:
                    return False
                usage = get_user_tool_usage_by_period(db, user_id=user_id)
                for period_id, limit in limits.items():
                    if limit > 0 and usage[period_id] >= limit:
                        return True
            return False

    limits = get_tool_usage_limit_values(app_settings)
    if not any(limit > 0 for limit in limits.values()):
        return False

    user_id = getattr(user, "id", None)
    if not user_id or user_id <= 0:
        return False

    usage = get_user_tool_usage_by_period(db, user_id=user_id)
    for period_id, limit in limits.items():
        if limit > 0 and usage[period_id] >= limit:
            return True
    return False


def check_usage_limit_for_request(
    db: Session,
    *,
    user: User,
    app_settings: AppSettings,
) -> UsageLimitCheckResult:
    if user.is_admin:
        return UsageLimitCheckResult(allowed=True, at_limit=False)

    user_id = getattr(user, "id", None)
    if not user_id or user_id <= 0:
        return UsageLimitCheckResult(allowed=True, at_limit=False)

    if user.package_id is not None:
        package = db.query(Package).filter(Package.id == user.package_id).first()
        if package:
            limits = get_package_usage_limit_values(package)
            if any(limit > 0 for limit in limits.values()):
                usage = get_user_token_usage_by_period(db, user_id=user_id)
                exceeded_periods = [period_id for period_id, limit in limits.items() if limit > 0 and usage[period_id] >= limit]
                if exceeded_periods:
                    return UsageLimitCheckResult(
                        allowed=False,
                        at_limit=True,
                        detail="Token usage limit reached. Try again after your usage resets.",
                    )
            return UsageLimitCheckResult(allowed=True, at_limit=False)

    limits = get_usage_limit_values(app_settings)
    if not any(limit > 0 for limit in limits.values()):
        return UsageLimitCheckResult(allowed=True, at_limit=False)

    usage = get_user_token_usage_by_period(db, user_id=user_id)
    exceeded_periods = [period_id for period_id, limit in limits.items() if limit > 0 and usage[period_id] >= limit]
    if not exceeded_periods:
        return UsageLimitCheckResult(allowed=True, at_limit=False)

    return UsageLimitCheckResult(
        allowed=False,
        at_limit=True,
        detail="Token usage limit reached. Try again after your usage resets.",
    )


def check_tool_usage_limit_for_request(
    db: Session,
    *,
    user: User,
    app_settings: AppSettings,
) -> UsageLimitCheckResult:
    if user.is_admin:
        return UsageLimitCheckResult(allowed=True, at_limit=False)

    user_id = getattr(user, "id", None)
    if not user_id or user_id <= 0:
        return UsageLimitCheckResult(allowed=True, at_limit=False)

    if user.package_id is not None:
        package = db.query(Package).filter(Package.id == user.package_id).first()
        if package:
            limits = get_package_tool_usage_limit_values(package)
            if any(limit > 0 for limit in limits.values()):
                usage = get_user_tool_usage_by_period(db, user_id=user_id)
                exceeded_periods = [period_id for period_id, limit in limits.items() if limit > 0 and usage[period_id] >= limit]
                if exceeded_periods:
                    return UsageLimitCheckResult(
                        allowed=False,
                        at_limit=True,
                        detail="Tool usage limit reached. Try again after your usage resets.",
                    )
            return UsageLimitCheckResult(allowed=True, at_limit=False)

    limits = get_tool_usage_limit_values(app_settings)
    if not any(limit > 0 for limit in limits.values()):
        return UsageLimitCheckResult(allowed=True, at_limit=False)

    usage = get_user_tool_usage_by_period(db, user_id=user_id)
    exceeded_periods = [period_id for period_id, limit in limits.items() if limit > 0 and usage[period_id] >= limit]
    if not exceeded_periods:
        return UsageLimitCheckResult(allowed=True, at_limit=False)

    return UsageLimitCheckResult(
        allowed=False,
        at_limit=True,
        detail="Tool usage limit reached. Try again after your usage resets.",
    )


def build_account_usage_status(db: Session, *, user: User, app_settings: AppSettings) -> dict | None:
    user_id = getattr(user, "id", None)
    if not user_id or user_id <= 0:
        return None

    now = datetime.now(timezone.utc)
    usage = get_user_token_usage_by_period(db, user_id=user_id)
    oldest = get_user_oldest_token_timestamp_by_period(db, user_id=user_id)
    period_labels = {
        "60_minutes": "60 Minutes",
        "24_hours": "24 Hours",
        "7_days": "7 Days",
        "30_days": "30 Days",
    }

    if user.package_id is not None:
        package = db.query(Package).filter(Package.id == user.package_id).first()
        if package:
            limits = get_package_usage_limit_values(package)
            periods = []
            for period_id, limit in limits.items():
                used = usage[period_id]
                effective_limit = 0 if user.is_admin else limit
                percent = min(100.0, (used / effective_limit) * 100) if effective_limit > 0 else 0.0
                _, _, window = next(s for s in USAGE_PERIOD_SPECS if s[0] == period_id)
                oldest_ts = _as_utc_aware(oldest[period_id])
                if oldest_ts is not None:
                    resets_in = int((oldest_ts + window - now).total_seconds())
                    resets_in = max(0, resets_in)
                else:
                    resets_in = None
                periods.append(
                    {
                        "id": period_id,
                        "label": period_labels[period_id],
                        "limit_tokens": effective_limit,
                        "used_tokens": used,
                        "percent": round(percent, 1),
                        "resets_in_seconds": resets_in,
                    }
                )

            return {
                "enabled": True,
                "is_admin": user.is_admin,
                "at_limit": is_user_over_usage_limit(db, user=user, app_settings=app_settings),
                "periods": periods,
            }

    limits = get_usage_limit_values(app_settings)
    periods = []
    for period_id, limit in limits.items():
        used = usage[period_id]
        effective_limit = 0 if user.is_admin else limit
        percent = min(100.0, (used / effective_limit) * 100) if effective_limit > 0 else 0.0
        _, _, window = next(s for s in USAGE_PERIOD_SPECS if s[0] == period_id)
        oldest_ts = _as_utc_aware(oldest[period_id])
        if oldest_ts is not None:
            resets_in = int((oldest_ts + window - now).total_seconds())
            resets_in = max(0, resets_in)
        else:
            resets_in = None
        periods.append(
            {
                "id": period_id,
                "label": period_labels[period_id],
                "limit_tokens": effective_limit,
                "used_tokens": used,
                "percent": round(percent, 1),
                "resets_in_seconds": resets_in,
            }
        )

    return {
        "enabled": True,
        "is_admin": user.is_admin,
        "at_limit": is_user_over_usage_limit(db, user=user, app_settings=app_settings),
        "periods": periods,
    }


def build_account_tool_usage_status(db: Session, *, user: User, app_settings: AppSettings) -> dict | None:
    user_id = getattr(user, "id", None)
    if not user_id or user_id <= 0:
        return None

    now = datetime.now(timezone.utc)
    usage = get_user_tool_usage_by_period(db, user_id=user_id)
    oldest = get_user_oldest_tool_timestamp_by_period(db, user_id=user_id)
    period_labels = {
        "60_minutes": "60 Minutes",
        "24_hours": "24 Hours",
        "7_days": "7 Days",
        "30_days": "30 Days",
    }

    if user.package_id is not None:
        package = db.query(Package).filter(Package.id == user.package_id).first()
        if package:
            limits = get_package_tool_usage_limit_values(package)
            periods = []
            for period_id, limit in limits.items():
                used = usage[period_id]
                effective_limit = 0 if user.is_admin else limit
                percent = min(100.0, (used / effective_limit) * 100) if effective_limit > 0 else 0.0
                _, _, window = next(s for s in TOOL_USAGE_PERIOD_SPECS if s[0] == period_id)
                oldest_ts = _as_utc_aware(oldest[period_id])
                if oldest_ts is not None:
                    resets_in = int((oldest_ts + window - now).total_seconds())
                    resets_in = max(0, resets_in)
                else:
                    resets_in = None
                periods.append(
                    {
                        "id": period_id,
                        "label": period_labels[period_id],
                        "limit_tokens": effective_limit,
                        "used_tokens": used,
                        "percent": round(percent, 1),
                        "resets_in_seconds": resets_in,
                    }
                )

            return {
                "enabled": True,
                "is_admin": user.is_admin,
                "at_limit": is_user_over_tool_usage_limit(db, user=user, app_settings=app_settings),
                "periods": periods,
            }

    limits = get_tool_usage_limit_values(app_settings)
    periods = []
    for period_id, limit in limits.items():
        used = usage[period_id]
        effective_limit = 0 if user.is_admin else limit
        percent = min(100.0, (used / effective_limit) * 100) if effective_limit > 0 else 0.0
        _, _, window = next(s for s in TOOL_USAGE_PERIOD_SPECS if s[0] == period_id)
        oldest_ts = _as_utc_aware(oldest[period_id])
        if oldest_ts is not None:
            resets_in = int((oldest_ts + window - now).total_seconds())
            resets_in = max(0, resets_in)
        else:
            resets_in = None
        periods.append(
            {
                "id": period_id,
                "label": period_labels[period_id],
                "limit_tokens": effective_limit,
                "used_tokens": used,
                "percent": round(percent, 1),
                "resets_in_seconds": resets_in,
            }
        )

    return {
        "enabled": True,
        "is_admin": user.is_admin,
        "at_limit": is_user_over_tool_usage_limit(db, user=user, app_settings=app_settings),
        "periods": periods,
    }
