from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

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
class StalePoolMembershipCleanupResult:
    removed_rows: int
    pool_ids: list[int]
    device_ids: list[int]


def get_pooled_device_ids(db: Session, *, excluding_pool_id: int | None = None) -> set[int]:
    query = db.query(GpuPoolDevice)
    if excluding_pool_id is not None:
        query = query.filter(GpuPoolDevice.pool_id != excluding_pool_id)
    return {row.device_id for row in query.all()}


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
            inference.deactivate_model(model.id)
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
            inference.deactivate_model(model.id)
        if model.activated:
            model.activated = False
        model.assignment_mode = "auto"
        model.pinned_pool_id = None
        model.pinned_device_id = None
        db.add(model)
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


def delete_pools_with_unavailable_devices(
    db: Session,
    available_hardware_ids: set[str],
    inference: "InferenceManager | None" = None,
) -> list[PoolCleanupResult]:
    results: list[PoolCleanupResult] = []
    for pool in db.query(GpuPool).order_by(GpuPool.id.asc()).all():
        member_devices = _pool_member_devices(db, pool.id)
        if any(device.hardware_id not in available_hardware_ids for device in member_devices):
            results.append(delete_pool_and_revert_models(db, pool, inference))
    return results


def delete_unavailable_devices(db: Session, detected_hardware_ids: set[str]) -> list[int]:
    """Remove DB devices that are no longer reported by any active inference runtime."""
    from app.models.inference_job import InferenceJob

    to_delete = [row for row in db.query(Device).all() if row.hardware_id not in detected_hardware_ids]
    if not to_delete:
        return []

    device_ids = [device.id for device in to_delete]
    revert_models_pinned_to_devices(db, device_ids, inference=None)

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


def _pool_member_device_ids(db: Session, pool_id: int) -> list[int]:
    return [row.device_id for row in db.query(GpuPoolDevice).filter(GpuPoolDevice.pool_id == pool_id).all()]


def _pool_member_devices(db: Session, pool_id: int) -> list[Device]:
    device_ids = _pool_member_device_ids(db, pool_id)
    if not device_ids:
        return []
    return db.query(Device).filter(Device.id.in_(device_ids)).all()