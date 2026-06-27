from datetime import datetime, timezone

import httpx
import psutil
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_optional_current_user
from app.core.app_settings import get_or_create_app_settings
from app.core.config import get_settings
from app.core.usage_limits import build_account_tool_usage_status, build_account_usage_status
from app.models.package import Package
from app.models.user import User
from app.core.device_manager import build_device_display_suffix
from app.core.db import get_db
from app.core.inference_manager import InferenceManager
from app.core.token_usage import build_token_usage_summary
from app.models.device import Device
from app.models.model_config import ModelConfig

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("")
async def get_status(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
) -> dict:
    inference: InferenceManager = router.inference_manager  # type: ignore[attr-defined]
    settings = get_settings()
    token_usage = build_token_usage_summary(db)
    since_startup = token_usage["since_startup"]
    devices = db.query(Device).order_by(Device.priority.asc(), Device.id.asc()).all()
    models_by_id = {model.id: model for model in db.query(ModelConfig).all()}
    runtime_devices, runtime_by_stable_id, runtime_errors = await _fetch_runtime_devices(settings)
    system_cpu_usage_percent = _coalesce_float(runtime_devices.get("cpu:0", {}).get("usage_percent"))
    fallback_models_by_device_id: dict[int, list[dict]] = {}
    # pool_model_device_ids maps model_id -> set of device IDs it spans (for pool models)
    pool_model_device_ids: dict[int, set[int]] = {}

    for running in inference._running.values():
        model = models_by_id.get(running.model_id)
        entry = {
            "model_id": running.model_id,
            "alias": model.alias if model else f"Model {running.model_id}",
            "memory_used_mb": 0,
            "pid": None,
        }
        if running.pool_device_ids:
            pool_model_device_ids[running.model_id] = set(running.pool_device_ids)
            for device_id in running.pool_device_ids:
                fallback_models_by_device_id.setdefault(device_id, []).append(entry)
        elif running.device_id is not None:
            fallback_models_by_device_id.setdefault(running.device_id, []).append(entry)

    serialized_devices: list[dict] = []
    for device in devices:
        # Match runtime stats by the stable PCI address first. The runtime keys its
        # payload by the *live* Vulkan index, which can diverge from this DB row's
        # stored index after an enumeration change — matching by stable id prevents
        # one card's stats/models from showing up on another card.
        runtime_device = {}
        if device.stable_hardware_id:
            runtime_device = runtime_by_stable_id.get(device.stable_hardware_id, {})
        if not runtime_device:
            runtime_device = runtime_devices.get(device.hardware_id, {})
        runtime_models = runtime_device.get("models")
        raw_models = list(runtime_models) if isinstance(runtime_models, list) and runtime_models else list(fallback_models_by_device_id.get(device.id, []))

        # For pool models that the runtime only reports on the primary GPU,
        # inject them into all other pool member devices as well.
        raw_model_ids = {row.get("model_id") for row in raw_models if isinstance(row, dict)}
        for model_id, device_ids in pool_model_device_ids.items():
            if device.id in device_ids and model_id not in raw_model_ids:
                model = models_by_id.get(model_id)
                raw_models.append({
                    "model_id": model_id,
                    "alias": model.alias if model else f"Model {model_id}",
                    "memory_used_mb": 0,
                    "pid": None,
                })

        models = [_serialize_status_model(row, models_by_id) for row in raw_models]
        models.sort(key=lambda row: row["model_id"])

        memory_used_mb = _coalesce_int(runtime_device.get("memory_used_mb"))
        if memory_used_mb is None:
            memory_used_mb = sum(model["memory_used_mb"] for model in models)
        _attribute_display_memory(models, memory_used_mb)

        usage_percent = _coalesce_float(runtime_device.get("usage_percent"))
        usage_source = runtime_device.get("usage_source") if usage_percent is not None else None

        gpu_usage_percent = _coalesce_float(runtime_device.get("gpu_usage_percent"))
        gpu_usage_source = runtime_device.get("gpu_usage_source") if gpu_usage_percent is not None else None

        serialized_devices.append(
            {
                "id": device.id,
                "hardware_id": device.hardware_id,
                "stable_hardware_id": device.stable_hardware_id,
                "stable_hardware_id_source": device.stable_hardware_id_source,
                "display_suffix": build_device_display_suffix(device.stable_hardware_id, device.hardware_id),
                "name": device.name,
                "vendor": device.vendor,
                "device_type": device.device_type,
                "enabled": device.enabled,
                "available": device.available,
                "priority": device.priority,
                "max_slots": device.max_slots,
                "max_threads": device.max_threads,
                "memory_total_mb": _coalesce_int(runtime_device.get("memory_total_mb")) or device.memory_mb,
                "memory_used_mb": memory_used_mb,
                "gpu_usage_percent": gpu_usage_percent,
                "gpu_usage_source": gpu_usage_source or "unavailable",
                "usage_percent": usage_percent,
                "usage_source": usage_source or "unavailable",
                "memory_source": runtime_device.get("memory_source") or "processes",
                "models": models,
            }
        )

    disk = psutil.disk_usage("/")
    account_usage = None
    account_tool_usage = None
    package_name = None
    if current_user is not None:
        app_settings = get_or_create_app_settings(db)
        account_usage = build_account_usage_status(db, user=current_user, app_settings=app_settings)
        account_tool_usage = build_account_tool_usage_status(db, user=current_user, app_settings=app_settings)
        if current_user.package_id is not None:
            package = db.query(Package).filter(Package.id == current_user.package_id).first()
            if package:
                package_name = package.name

    return {
        "status": "ok",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "system_cpu_usage_percent": system_cpu_usage_percent,
        "system_disk_free_bytes": disk.free,
        "input_tokens_processed": since_startup["input_tokens"],
        "output_tokens_processed": since_startup["output_tokens"],
        "tokens_processed": since_startup["total_tokens"],
        "token_usage": token_usage,
        "account_usage": account_usage,
        "account_tool_usage": account_tool_usage,
        "devices": serialized_devices,
        "runtime_errors": runtime_errors,
        "package_name": package_name,
    }


async def _fetch_runtime_devices(settings) -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    runtime_map = settings.inference_runtime_url_map()
    devices: dict[str, dict] = {}
    by_stable_id: dict[str, dict] = {}
    errors: list[dict] = []

    async with httpx.AsyncClient(timeout=settings.inference_service_timeout_seconds) as client:
        for vendor_key, base_url in runtime_map.items():
            try:
                response = await client.get(f"{base_url}/runtime/status")
                response.raise_for_status()
            except Exception as exc:
                errors.append({"vendor": vendor_key, "base_url": base_url, "detail": str(exc)})
                continue

            payload = response.json()
            rows = payload.get("devices", []) if isinstance(payload, dict) else []
            for row in rows:
                hardware_id = row.get("hardware_id") if isinstance(row, dict) else None
                if not hardware_id:
                    continue
                devices[str(hardware_id)] = row
                stable_id = row.get("stable_hardware_id")
                if stable_id:
                    by_stable_id[str(stable_id)] = row

    return devices, by_stable_id, errors


def _serialize_status_model(row: dict, models_by_id: dict[int, ModelConfig]) -> dict:
    model_id = _coalesce_int(row.get("model_id")) or 0
    model = models_by_id.get(model_id)
    memory_used_mb = _coalesce_int(row.get("memory_used_mb")) or 0
    return {
        "model_id": model_id,
        "alias": row.get("alias") or (model.alias if model else f"Model {model_id}"),
        "file_name": model.file_name if model else "",
        "memory_used_mb": memory_used_mb,
        "display_memory_used_mb": memory_used_mb,
        "pid": _coalesce_int(row.get("pid")),
    }


def _attribute_display_memory(models: list[dict], total_memory_mb: int) -> None:
    if not models:
        return

    if total_memory_mb <= 0:
        for model in models:
            model["display_memory_used_mb"] = max(0, int(model.get("memory_used_mb") or 0))
        return

    raw_allocations = [max(0, int(model.get("memory_used_mb") or 0)) for model in models]
    reported_total = sum(raw_allocations)
    if reported_total >= total_memory_mb:
        for model, raw_memory_mb in zip(models, raw_allocations):
            model["display_memory_used_mb"] = raw_memory_mb
        return

    missing_memory_mb = total_memory_mb - reported_total
    weights = raw_allocations if reported_total > 0 else [1] * len(models)
    attributed_missing_memory = _allocate_memory_by_weight(weights, missing_memory_mb)

    for model, raw_memory_mb, missing_memory_share in zip(models, raw_allocations, attributed_missing_memory):
        model["display_memory_used_mb"] = raw_memory_mb + missing_memory_share


def _allocate_memory_by_weight(weights: list[int], total_memory_mb: int) -> list[int]:
    if not weights or total_memory_mb <= 0:
        return [0] * len(weights)

    safe_weights = [max(0, int(weight)) for weight in weights]
    if sum(safe_weights) <= 0:
        safe_weights = [1] * len(safe_weights)

    weight_total = sum(safe_weights)
    allocations = [int(total_memory_mb * weight / weight_total) for weight in safe_weights]
    remainder = total_memory_mb - sum(allocations)
    indices = sorted(range(len(safe_weights)), key=lambda index: safe_weights[index], reverse=True)
    for offset in range(remainder):
        allocations[indices[offset % len(indices)]] += 1

    return allocations


def _coalesce_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coalesce_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None