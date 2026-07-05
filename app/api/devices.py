from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.core.activity_logger import log_event
from app.core.config import get_settings
from app.core.db import get_db
from app.core.device_manager import DeviceManager, build_device_display_suffix, get_supported_vendors
from app.core.gpu_chip_vendor import chip_vendor_key, chip_vendor_label
from app.core.gpu_pool_manager import (
    deactivate_pool_models,
    delete_pool_and_revert_models,
    ordered_pool_devices,
    revert_models_pinned_to_devices,
)
from app.models.device import Device
from app.models.gpu_pool import GpuPool, GpuPoolDevice, VALID_SPLIT_MODES
from app.models.model_config import ModelConfig
from app.models.user import User
from app.utils.schemas import DeviceReorderRequest, DeviceUpdateRequest, GpuPoolCreateRequest, GpuPoolUpdateRequest, PoolReorderRequest

router = APIRouter(prefix="/api/devices", tags=["devices"])
device_manager = DeviceManager()


@router.get("")
def list_devices(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[dict]:
    inference = router.inference_manager  # type: ignore[attr-defined]
    rows = device_manager.sync_detected_devices(db, inference=inference)
    pool_device_rows = db.query(GpuPoolDevice).all()
    pooled_device_ids = {row.device_id for row in pool_device_rows}
    result = []
    for d in rows:
        # Devices soft-disabled by reconciliation (physically gone/undetected) are
        # kept in the DB so a pool/pin can auto-recover if the GPU reappears, but
        # they must not be shown as live GPUs in the panel.
        if not d.available and d.id not in pooled_device_ids:
            continue
        serialized = _serialize_device(d, device_manager.default_name_for_device(d))
        serialized["in_pool"] = d.id in pooled_device_ids
        result.append(serialized)
    return result


@router.post("/reorder")
def reorder_devices(payload: DeviceReorderRequest, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    for item in payload.devices:
        device = db.query(Device).filter(Device.id == item.id).first()
        if device:
            memberships = db.query(GpuPoolDevice).filter(GpuPoolDevice.device_id == item.id).all()
            if memberships:
                continue
            device.priority = item.priority
            db.add(device)
    db.commit()
    return {"status": "ok"}


@router.post("/pools/reorder")
def reorder_pools(payload: PoolReorderRequest, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    for item in payload.pools:
        pool = db.query(GpuPool).filter(GpuPool.id == item.id).first()
        if pool:
            pool.pool_order = item.pool_order
            db.add(pool)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# GPU Pool endpoints
# ---------------------------------------------------------------------------


@router.get("/pools")
def list_pools(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[dict]:
    pools = db.query(GpuPool).order_by(GpuPool.vendor.asc(), GpuPool.name.asc(), GpuPool.id.asc()).all()
    return [_serialize_pool(pool, db) for pool in pools]


@router.get("/pools/{pool_id}")
def get_pool(pool_id: int, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    pool = db.query(GpuPool).filter(GpuPool.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail="GPU pool not found")
    return _serialize_pool(pool, db)


@router.post("/pools")
def create_pool(payload: GpuPoolCreateRequest, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    vendor = _validate_pool_vendor(payload.vendor)
    split_mode = _validate_split_mode(payload.split_mode)
    devices = _validate_pool_devices(payload.device_ids, vendor, db)
    _validate_pool_membership(devices, db)
    inference = router.inference_manager  # type: ignore[attr-defined]

    pool = GpuPool(name=payload.name.strip(), vendor=vendor, split_mode=split_mode, max_slots=payload.max_slots)
    db.add(pool)
    db.flush()

    reverted_models = revert_models_pinned_to_devices(db, [device.id for device in devices], inference)

    for device in devices:
        db.add(GpuPoolDevice(pool_id=pool.id, device_id=device.id))
        device.max_slots = payload.max_slots
        db.add(device)

    db.commit()
    db.refresh(pool)

    log_event(db, "pool.created", details={"pool_id": pool.id, "pool_name": pool.name, "vendor": pool.vendor, "device_ids": payload.device_ids})
    for model in reverted_models:
        log_event(db, "model.assignment_reset", details={"model_id": model.id, "alias": model.alias, "reason": "device_joined_pool", "pool_id": pool.id})
    return {"status": "ok", "pool": _serialize_pool(pool, db)}


@router.patch("/pools/{pool_id}")
def update_pool(pool_id: int, payload: GpuPoolUpdateRequest, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    pool = db.query(GpuPool).filter(GpuPool.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail="GPU pool not found")
    inference = router.inference_manager  # type: ignore[attr-defined]

    vendor = pool.vendor
    if payload.vendor is not None:
        vendor = _validate_pool_vendor(payload.vendor)

    devices = _validate_pool_devices(payload.device_ids, vendor, db)
    _validate_pool_membership(devices, db, current_pool_id=pool.id)
    previous_device_ids = {row.device_id for row in db.query(GpuPoolDevice).filter(GpuPoolDevice.pool_id == pool.id).all()}
    next_device_ids = {device.id for device in devices}
    added_device_ids = sorted(next_device_ids - previous_device_ids)

    if payload.name is not None:
        pool.name = payload.name.strip()
    pool.vendor = vendor
    if payload.split_mode is not None:
        pool.split_mode = _validate_split_mode(payload.split_mode)
    if payload.max_slots is not None:
        pool.max_slots = payload.max_slots
    db.add(pool)

    reverted_models = revert_models_pinned_to_devices(db, added_device_ids, inference)

    removed_device_ids = sorted(previous_device_ids - next_device_ids)
    for device_id in removed_device_ids:
        device = db.query(Device).filter(Device.id == device_id).first()
        if device:
            device.priority = 0
            db.add(device)

    db.query(GpuPoolDevice).filter(GpuPoolDevice.pool_id == pool.id).delete()
    for device in devices:
        db.add(GpuPoolDevice(pool_id=pool.id, device_id=device.id))
        device.max_slots = pool.max_slots
        db.add(device)

    db.commit()
    db.refresh(pool)

    log_event(db, "pool.updated", details={"pool_id": pool.id, "pool_name": pool.name, "vendor": pool.vendor, "device_ids": payload.device_ids})
    for model in reverted_models:
        log_event(db, "model.assignment_reset", details={"model_id": model.id, "alias": model.alias, "reason": "device_joined_pool", "pool_id": pool.id})
    return {"status": "ok", "pool": _serialize_pool(pool, db)}


@router.delete("/pools/{pool_id}")
def delete_pool(pool_id: int, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    pool = db.query(GpuPool).filter(GpuPool.id == pool_id).first()
    if not pool:
        raise HTTPException(status_code=404, detail="GPU pool not found")

    from app.core.inference_manager import InferenceManager
    inference: InferenceManager = router.inference_manager  # type: ignore[attr-defined]
    cleanup = delete_pool_and_revert_models(db, pool, inference)
    db.commit()

    log_event(db, "pool.deleted", details={"pool_id": cleanup.pool_id, "pool_name": cleanup.pool_name, "vendor": pool.vendor})
    return {"status": "ok"}


@router.patch("/{device_id}")
def update_device(device_id: int, payload: DeviceUpdateRequest, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    enabled_before = device.enabled

    pool_memberships = db.query(GpuPoolDevice).filter(GpuPoolDevice.device_id == device_id).all()
    for field in ["name", "enabled", "priority", "max_threads", "max_slots"]:
        value = getattr(payload, field)
        if value is not None:
            if field == "priority" and pool_memberships and value != device.priority:
                raise HTTPException(status_code=400, detail="Cannot change priority of a device that is a member of a GPU pool")
            if field == "name":
                stripped = value.strip()
                value = device_manager.default_name_for_device(device) if not stripped else stripped
            setattr(device, field, value)

    if payload.enabled is not None and not device.enabled and enabled_before:
        inference = router.inference_manager  # type: ignore[attr-defined]
        deactivated_models: list[ModelConfig] = []
        for membership in pool_memberships:
            deactivated_models.extend(deactivate_pool_models(db, membership.pool_id, inference))
        pinned_models = db.query(ModelConfig).filter(
            ModelConfig.assignment_mode == "pinned",
            ModelConfig.pinned_device_id == device_id,
        ).all()
        for model in pinned_models:
            if model.activated and inference is not None:
                inference.deactivate_model(model.id)
            if model.activated:
                model.activated = False
            model.assignment_mode = "auto"
            model.pinned_device_id = None
            model.pinned_pool_id = None
            db.add(model)
            deactivated_models.append(model)
        if deactivated_models:
            db.commit()
            for model in deactivated_models:
                log_event(db, "model.assignment_reset", details={"model_id": model.id, "alias": model.alias, "reason": "device_disabled", "device_id": device_id})

    db.add(device)
    db.commit()
    db.refresh(device)

    if payload.enabled is not None and payload.enabled != enabled_before:
        event_type = "device.enabled" if device.enabled else "device.disabled"
        log_event(db, event_type, details={"device_name": device.name, "hardware_id": device.hardware_id})
    elif payload.enabled is None:
        log_event(db, "device.updated", details={"device_name": device.name, "hardware_id": device.hardware_id})

    device_serialized = _serialize_device(device, device_manager.default_name_for_device(device))
    device_serialized["in_pool"] = len(pool_memberships) > 0
    return {"status": "ok", "device": device_serialized}


def _validate_pool_vendor(vendor: str) -> str:
    normalized = vendor.strip().lower()
    if normalized != "vulkan":
        raise HTTPException(status_code=400, detail="GPU pools only support the vulkan vendor")
    return normalized


def _validate_split_mode(split_mode: str) -> str:
    normalized = split_mode.strip().lower()
    if normalized == "row":
        raise HTTPException(status_code=400, detail="Split mode 'row' is no longer supported. Use 'layer' or 'tensor'.")
    if normalized not in VALID_SPLIT_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid split mode. Must be one of: {', '.join(sorted(VALID_SPLIT_MODES))}")
    return normalized


def _validate_pool_devices(device_ids: list[int], vendor: str, db: Session) -> list[Device]:
    if len(device_ids) < 2:
        raise HTTPException(status_code=400, detail="A GPU pool requires at least two devices")

    devices: list[Device] = []
    seen_ids: set[int] = set()
    chip_vendor_id: int | None = None
    for device_id in device_ids:
        if device_id in seen_ids:
            raise HTTPException(status_code=400, detail="GPU pool device list contains duplicates")
        seen_ids.add(device_id)

        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
        if device.vendor != vendor:
            raise HTTPException(
                status_code=400,
                detail=f"Device {device.name} is a {device.vendor} device and cannot be added to a {vendor} pool",
            )
        if device.device_type != "gpu":
            raise HTTPException(status_code=400, detail=f"Device {device.name} is not a GPU")
        if device.pci_vendor_id is None:
            raise HTTPException(
                status_code=400,
                detail=f"Device {device.name} has no GPU chip vendor id; restart inference and refresh devices",
            )
        if chip_vendor_id is None:
            chip_vendor_id = device.pci_vendor_id
        elif device.pci_vendor_id != chip_vendor_id:
            left = chip_vendor_label(chip_vendor_id) or "unknown"
            right = chip_vendor_label(device.pci_vendor_id) or "unknown"
            raise HTTPException(
                status_code=400,
                detail=f"GPU pool members must share the same chip vendor ({left} and {right} cannot be pooled together)",
            )
        devices.append(device)

    return devices


def _validate_pool_membership(devices: list[Device], db: Session, current_pool_id: int | None = None) -> None:
    device_ids = [device.id for device in devices]
    existing_rows = db.query(GpuPoolDevice).filter(GpuPoolDevice.device_id.in_(device_ids)).all()
    conflicts = [row.device_id for row in existing_rows if row.pool_id != current_pool_id]
    if conflicts:
        joined = ", ".join(str(device_id) for device_id in sorted(conflicts))
        raise HTTPException(status_code=409, detail=f"Devices already belong to another pool: {joined}")


def _serialize_pool(pool: GpuPool, db: Session) -> dict:
    devices = ordered_pool_devices(db, pool.id)
    pool_enabled = len(devices) > 0 and all(device.enabled for device in devices)
    return {
        "id": pool.id,
        "name": pool.name,
        "vendor": pool.vendor,
        "split_mode": "layer" if pool.split_mode == "row" else pool.split_mode,
        "max_slots": pool.max_slots,
        "pool_order": pool.pool_order,
        "enabled": pool_enabled,
        "devices": [_serialize_device(device, in_pool=True) for device in devices],
    }


def _serialize_device(device: Device, default_name: str | None = None, *, in_pool: bool = False) -> dict:
    resolved_default_name = default_name or device_manager.default_name_for_device(device)
    return {
        "id": device.id,
        "hardware_id": device.hardware_id,
        "stable_hardware_id": device.stable_hardware_id,
        "stable_hardware_id_source": device.stable_hardware_id_source,
        "display_suffix": build_device_display_suffix(device.stable_hardware_id, device.hardware_id),
        "name": device.name,
        "default_name": resolved_default_name,
        "vendor": device.vendor,
        "device_type": device.device_type,
        "memory_mb": device.memory_mb,
        "enabled": device.enabled,
        "available": device.available,
        "priority": device.priority,
        "max_threads": device.max_threads,
        "max_slots": device.max_slots,
        "in_pool": in_pool,
        "pci_vendor_id": device.pci_vendor_id,
        "chip_vendor": chip_vendor_key(device.pci_vendor_id),
        "chip_vendor_label": chip_vendor_label(device.pci_vendor_id),
    }
