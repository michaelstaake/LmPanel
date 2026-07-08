from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.pool_lifecycle import DeactivateReason, log_pool_event
from app.models.device import Device
from app.models.gpu_pool import GpuPool, GpuPoolDevice
from app.models.model_config import ModelConfig

if TYPE_CHECKING:
    from app.core.inference_manager import InferenceManager


@dataclass
class PoolCleanupResult:
    pool_id: int
    pool_name: str
    member_device_ids: list[int]
    reverted_model_ids: list[int]


@dataclass
class PoolDegradeResult:
    pool_id: int
    pool_name: str
    suspended_model_ids: list[int]
    reason: str


@dataclass
class StalePoolMembershipCleanupResult:
    removed_rows: int
    pool_ids: list[int]
    device_ids: list[int]


def get_pooled_device_ids(db: Session, *, excluding_pool_id: int | None = None) -> set[int]:
    query = db.query(GpuPoolDevice)
    if excluding_pool_id is not None:
        query = query.filter(GpuPoolDevice.pool_id != excluding_pool_id)
    return {row.device_id for row in query.all()}


def ordered_pool_devices(db: Session, pool_id: int, *, require_enabled: bool = False) -> list[Device]:
    """Return pool member devices in the order they were added to the pool."""
    pool_device_rows = db.query(GpuPoolDevice).filter(GpuPoolDevice.pool_id == pool_id).all()
    device_ids = [row.device_id for row in pool_device_rows]
    if not device_ids:
        return []

    query = db.query(Device).filter(Device.id.in_(device_ids))
    if require_enabled:
        query = query.filter(Device.enabled.is_(True))
    devices_by_id = {device.id: device for device in query.all()}
    return [devices_by_id[device_id] for device_id in device_ids if device_id in devices_by_id]


def is_pooled_device(db: Session, device_id: int, *, excluding_pool_id: int | None = None) -> bool:
    return device_id in get_pooled_device_ids(db, excluding_pool_id=excluding_pool_id)


def revert_models_pinned_to_devices(
    db: Session,
    device_ids: list[int],
    inference: "InferenceManager | None" = None,
) -> list[ModelConfig]:
    if not device_ids:
        return []

    models = db.query(ModelConfig).filter(
        ModelConfig.assignment_mode == "pinned",
        ModelConfig.pinned_device_id.in_(device_ids),
    ).all()
    for model in models:
        if model.activated and inference is not None:
            inference.deactivate_model_sync(model.id, reason=DeactivateReason.POOL_CLEANUP)
        if model.activated:
            model.activated = False
        model.assignment_mode = "auto"
        model.pinned_device_id = None
        model.pinned_pool_id = None
        db.add(model)
    return models


def revert_models_assigned_to_pool(
    db: Session,
    pool_id: int,
    inference: "InferenceManager | None" = None,
) -> list[ModelConfig]:
    models = db.query(ModelConfig).filter(
        ModelConfig.assignment_mode == "pool",
        ModelConfig.pinned_pool_id == pool_id,
    ).all()
    for model in models:
        if model.activated and inference is not None:
            inference.deactivate_model_sync(model.id, reason=DeactivateReason.POOL_CLEANUP)
        if model.activated:
            model.activated = False
        model.assignment_mode = "auto"
        model.pinned_pool_id = None
        model.pinned_device_id = None
        db.add(model)
    return models


def suspend_pool_models(
    db: Session,
    pool_id: int,
    inference: "InferenceManager | None" = None,
    *,
    reason: str = "pool_member_unavailable",
) -> list[ModelConfig]:
    """Stop inference for pool-assigned models but preserve pool assignment intent."""
    models = db.query(ModelConfig).filter(
        ModelConfig.assignment_mode == "pool",
        ModelConfig.pinned_pool_id == pool_id,
    ).all()
    for model in models:
        if inference is not None:
            inference.deactivate_model_sync(model.id, reason=DeactivateReason.POOL_SUSPEND)
        db.add(model)
    if models:
        log_pool_event(
            "suspend",
            pool_id=pool_id,
            reason=reason,
            model_ids=",".join(str(model.id) for model in models),
        )
    return models


def delete_pool_and_revert_models(
    db: Session,
    pool: GpuPool,
    inference: "InferenceManager | None" = None,
) -> PoolCleanupResult:
    member_device_ids = _pool_member_device_ids(db, pool.id)
    reverted_models = revert_models_assigned_to_pool(db, pool.id, inference)
    db.query(GpuPoolDevice).filter(GpuPoolDevice.pool_id == pool.id).delete(synchronize_session=False)
    db.delete(pool)
    return PoolCleanupResult(
        pool_id=pool.id,
        pool_name=pool.name,
        member_device_ids=member_device_ids,
        reverted_model_ids=[model.id for model in reverted_models],
    )


def degrade_pools_with_unavailable_devices(
    db: Session,
    available_hardware_ids: set[str],
    inference: "InferenceManager | None" = None,
) -> list[PoolDegradeResult]:
    """Suspend pool models when a member disappears without deleting the pool."""
    results: list[PoolDegradeResult] = []
    for pool in db.query(GpuPool).order_by(GpuPool.id.asc()).all():
        member_devices = _pool_member_devices(db, pool.id)
        if not member_devices:
            continue
        if any(device.hardware_id not in available_hardware_ids for device in member_devices):
            suspended = suspend_pool_models(
                db,
                pool.id,
                inference,
                reason="pool_member_unavailable",
            )
            results.append(
                PoolDegradeResult(
                    pool_id=pool.id,
                    pool_name=pool.name,
                    suspended_model_ids=[model.id for model in suspended],
                    reason="pool_member_unavailable",
                )
            )
    return results


def delete_pools_with_unavailable_devices(
    db: Session,
    available_hardware_ids: set[str],
    inference: "InferenceManager | None" = None,
) -> list[PoolDegradeResult]:
    """Deprecated alias: degrades pools in place instead of deleting them."""
    return degrade_pools_with_unavailable_devices(db, available_hardware_ids, inference)


def mark_unavailable_devices(
    db: Session,
    detected_hardware_ids: set[str],
    *,
    detected_stable_hardware_ids: set[str] | None = None,
    keep_device_ids: set[int] | None = None,
) -> list[int]:
    """Soft-disable DB devices not reported by the latest authoritative detection.

    Unlike :func:`delete_unavailable_devices` this is non-destructive: it only
    flips ``Device.available`` to ``False`` and leaves the row, its pool
    memberships, and any model pins intact so they recover automatically when the
    device reappears. Hard deletion is reserved for explicit user-initiated purge.
    """
    stable_ids = detected_stable_hardware_ids or set()
    keep_ids = keep_device_ids or set()
    changed: list[int] = []
    for row in db.query(Device).all():
        if row.id in keep_ids:
            continue
        if row.hardware_id in detected_hardware_ids:
            continue
        if row.stable_hardware_id and row.stable_hardware_id in stable_ids:
            continue
        if row.available:
            row.available = False
            db.add(row)
            changed.append(row.id)
    return changed


def delete_unavailable_devices(
    db: Session,
    detected_hardware_ids: set[str],
    inference: "'InferenceManager | None'" = None,
    *,
    detected_stable_hardware_ids: set[str] | None = None,
    keep_device_ids: set[int] | None = None,
) -> list[int]:
    """Hard-remove DB devices no longer reported by any runtime (explicit purge only).

    Prefer :func:`mark_unavailable_devices` for routine reconciliation; this
    destructive path cascades to pool membership and reverts pinned models, so it
    must only run on an authoritative, user-initiated purge."""
    from app.models.inference_job import InferenceJob

    stable_ids = detected_stable_hardware_ids or set()
    keep_ids = keep_device_ids or set()
    to_delete = [
        row
        for row in db.query(Device).all()
        if row.id not in keep_ids
        and row.hardware_id not in detected_hardware_ids
        and (not row.stable_hardware_id or row.stable_hardware_id not in stable_ids)
    ]
    if not to_delete:
        return []

    device_ids = [device.id for device in to_delete]
    revert_models_pinned_to_devices(db, device_ids, inference)

    db.query(InferenceJob).filter(InferenceJob.device_id.in_(device_ids)).update(
        {InferenceJob.device_id: None},
        synchronize_session=False,
    )

    for device in to_delete:
        db.delete(device)

    return device_ids


def delete_pools_with_insufficient_members(
    db: Session,
    inference: "InferenceManager | None" = None,
    *,
    min_members: int = 2,
) -> list[PoolCleanupResult]:
    results: list[PoolCleanupResult] = []
    for pool in db.query(GpuPool).order_by(GpuPool.id.asc()).all():
        member_count = db.query(GpuPoolDevice).filter(GpuPoolDevice.pool_id == pool.id).count()
        if member_count < min_members:
            results.append(delete_pool_and_revert_models(db, pool, inference))
    return results


def delete_stale_pool_memberships(db: Session) -> StalePoolMembershipCleanupResult:
    existing_pool_ids = {pool_id for (pool_id,) in db.query(GpuPool.id).all()}
    stale_rows = [row for row in db.query(GpuPoolDevice).all() if row.pool_id not in existing_pool_ids]
    if not stale_rows:
        return StalePoolMembershipCleanupResult(removed_rows=0, pool_ids=[], device_ids=[])

    for row in stale_rows:
        db.delete(row)

    return StalePoolMembershipCleanupResult(
        removed_rows=len(stale_rows),
        pool_ids=sorted({row.pool_id for row in stale_rows}),
        device_ids=sorted({row.device_id for row in stale_rows}),
    )


def deactivate_pool_models(
    db: Session,
    pool_id: int,
    inference: "InferenceManager | None" = None,
) -> list[ModelConfig]:
    """Suspend pool models while preserving pool assignment for automatic recovery."""
    return suspend_pool_models(db, pool_id, inference, reason="pool_deactivated")


def _pool_member_device_ids(db: Session, pool_id: int) -> list[int]:
    return [row.device_id for row in db.query(GpuPoolDevice).filter(GpuPoolDevice.pool_id == pool_id).all()]


def _pool_member_devices(db: Session, pool_id: int) -> list[Device]:
    device_ids = _pool_member_device_ids(db, pool_id)
    if not device_ids:
        return []
    return db.query(Device).filter(Device.id.in_(device_ids)).all()
