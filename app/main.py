import asyncio
import time
from contextlib import asynccontextmanager
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, chat, devices, knowledge_base, logs, models, openai_compat, ssl as ssl_api, status, terms as terms_api, web_search as web_search_api
from app.core.activity_logger import log_event, prune_old_logs, schedule_daily_pruning
from app.core.letsencrypt import schedule_daily_ssl_renewal
from app.core.app_settings import get_or_create_app_settings
from app.core.config import get_settings
from app.core.db import SessionLocal
from sqlalchemy.exc import OperationalError
from app.core.device_manager import DeviceManager
from app.core.gpu_pool_manager import (
    degrade_pools_with_unavailable_devices,
    delete_pools_with_insufficient_members,
    delete_stale_pool_memberships,
)
from app.core.inference_manager import InferenceManager, PoolActivationTarget
from app.core.model_activation import InsufficientHostRamError
from app.core.pool_lifecycle import DeactivateReason, LivenessKind, RuntimeStateKind, log_pool_event
from app.core.logging import configure_logging
from app.core import token_usage as _token_usage
from app.models.device import Device
from app.models.model_config import ModelConfig
from app.api import tasks
settings = get_settings()
Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
Path(settings.data_dir, "backgrounds").mkdir(parents=True, exist_ok=True)
device_manager = DeviceManager()
inference_manager = InferenceManager()
logger = logging.getLogger(__name__)


async def _runtime_gpu_count() -> tuple[int, bool]:
    """Return (gpu_count, reachable) by polling the inference runtime device list."""
    runtime_map = settings.inference_runtime_url_map()
    if not settings.inference_runtime_urls.strip():
        # No separate runtime configured; nothing to wait for.
        return 0, True
    seen_urls: set[str] = set()
    reachable = False
    gpu_count = 0
    async with httpx.AsyncClient(timeout=settings.inference_service_timeout_seconds) as client:
        for base_url in runtime_map.values():
            if base_url in seen_urls:
                continue
            seen_urls.add(base_url)
            try:
                response = await client.get(f"{base_url}/runtime/devices")
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue
            reachable = True
            rows = payload.get("devices", []) if isinstance(payload, dict) else []
            gpu_count += sum(
                1
                for row in rows
                if isinstance(row, dict)
                and row.get("device_type") == "gpu"
                and row.get("vendor") != "cpu"
            )
    return gpu_count, reachable


async def _wait_for_gpu_ready() -> None:
    """Wait for the inference runtime to enumerate at least one GPU before syncing.

    Prevents the classic boot race where the runtime answers but amdgpu/Vulkan has
    not finished initializing, which would otherwise soft-disable every GPU. Bounded
    so genuinely CPU-only hosts still start promptly.
    """
    deadline = time.monotonic() + max(0, settings.gpu_ready_timeout_seconds)
    first_reachable_at: float | None = None
    while time.monotonic() < deadline:
        gpu_count, reachable = await _runtime_gpu_count()
        if reachable:
            if gpu_count > 0:
                logger.info("Inference runtime reports %d GPU(s); proceeding with startup", gpu_count)
                return
            now = time.monotonic()
            if first_reachable_at is None:
                first_reachable_at = now
            elif now - first_reachable_at >= max(0, settings.gpu_ready_grace_seconds):
                logger.info("Inference runtime reachable with no GPU after grace period; assuming CPU-only host")
                return
        await asyncio.sleep(2)
    logger.warning("Timed out waiting for inference runtime GPUs; proceeding with startup anyway")


async def _watchdog_tick() -> None:
    # 1. Detect and clear crashed model processes so they can be re-activated.
    for model_id in list(inference_manager._running.keys()):
        liveness = await inference_manager.classify_model_liveness(model_id)
        if liveness.kind == LivenessKind.PROCESS_DEAD:
            logger.warning(
                "Model %s process is not alive (%s); clearing for recovery",
                model_id,
                liveness.detail,
            )
            log_pool_event(
                "watchdog.recovery",
                model_id=model_id,
                action="deactivate",
                reason="process_dead",
            )
            await inference_manager.deactivate_model(model_id, reason=DeactivateReason.WATCHDOG_LIVENESS)

    db = SessionLocal()
    try:
        # 2. Re-sync devices (non-destructive); returning GPUs flip back to available.
        device_manager.sync_detected_devices(db, auto_enable_defaults=True, inference=inference_manager)
        available_hardware_ids = {
            device.hardware_id
            for device in db.query(Device).filter(Device.available.is_(True)).all()
        }
        degraded_pools = degrade_pools_with_unavailable_devices(db, available_hardware_ids, inference_manager)
        for degraded in degraded_pools:
            log_pool_event(
                "degrade",
                pool_id=degraded.pool_id,
                pool_name=degraded.pool_name,
                reason=degraded.reason,
                model_ids=",".join(str(model_id) for model_id in degraded.suspended_model_ids),
            )

        # 3. (Re)activate any model that should be running but isn't.
        # Only one activation per tick to avoid retry storms and concurrent loads.
        now = time.monotonic()
        activated_models = (
            db.query(ModelConfig)
            .filter(ModelConfig.activated.is_(True))
            .order_by(ModelConfig.priority.asc(), ModelConfig.id.asc())
            .all()
        )
        activations_this_tick = 0
        max_activations = max(1, settings.watchdog_max_activations_per_tick)
        for model in activated_models:
            if inference_manager.is_active(model.id):
                inference_manager.clear_recovery_state(model.id)
                continue
            state = inference_manager.get_recovery_state(model.id)
            if state is not None:
                if state.attempts >= settings.model_recovery_max_attempts:
                    continue
                if now < state.next_attempt:
                    continue
            if activations_this_tick >= max_activations:
                break
            try:
                resolution = await models._resolve_device_for_model(db, model, inference_manager)
                if resolution is None:
                    raise RuntimeError("No available device for model")
                if isinstance(resolution, PoolActivationTarget):
                    await inference_manager.activate_model_on_pool(model, resolution)
                else:
                    await inference_manager.activate_model(model, resolution)
                inference_manager.clear_recovery_state(model.id)
                log_pool_event("watchdog.recovery", model_id=model.id, action="activate", alias=model.alias)
                logger.info("Watchdog recovered model %s", model.alias)
            except InsufficientHostRamError as exc:
                activations_this_tick += 1
                inference_manager.note_recovery_error(model.id, str(exc))
                logger.warning(
                    "Watchdog deferring activation of %s until more host RAM is free: %s",
                    model.alias,
                    exc,
                )
            except Exception as exc:
                attempts = (state.attempts if state else 0) + 1
                backoff = min(
                    settings.device_watchdog_interval_seconds * (2 ** (attempts - 1)),
                    3600,
                )
                failure_kind = (
                    RuntimeStateKind.BACKOFF_LIMITED
                    if attempts >= settings.model_recovery_max_attempts
                    else None
                )
                inference_manager.record_recovery_failure(
                    model.id,
                    str(exc),
                    attempts=attempts,
                    next_attempt=now + backoff,
                    failure_kind=failure_kind,
                )
                activations_this_tick += 1
                if attempts >= settings.model_recovery_max_attempts:
                    logger.error(
                        "Watchdog giving up on model %s after %d attempts: %s",
                        model.alias,
                        attempts,
                        exc,
                    )
                else:
                    logger.warning(
                        "Watchdog recovery attempt %d for model %s failed (retry in %ds): %s",
                        attempts,
                        model.alias,
                        backoff,
                        exc,
                    )
            else:
                activations_this_tick += 1
            if activations_this_tick >= max_activations:
                break
        db.commit()
    finally:
        db.close()


async def schedule_device_watchdog() -> None:
    """Periodically reconcile GPUs and auto-restart crashed models."""
    interval = max(5, settings.device_watchdog_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            await _watchdog_tick()
        except Exception:
            logger.exception("Device watchdog tick failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.app_log_level)
    Path(settings.models_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.data_dir, "backgrounds").mkdir(parents=True, exist_ok=True)

    await _wait_for_gpu_ready()

    db = SessionLocal()
    try:
        prune_old_logs(db)
        device_manager.sync_detected_devices(db, auto_enable_defaults=True, inference=inference_manager)
        stale_memberships = delete_stale_pool_memberships(db)
        if stale_memberships.removed_rows:
            log_event(
                db,
                "pool.memberships_repaired",
                details={
                    "removed_rows": stale_memberships.removed_rows,
                    "pool_ids": stale_memberships.pool_ids,
                    "device_ids": stale_memberships.device_ids,
                    "reason": "stale_pool_memberships_on_startup",
                },
            )
        # NOTE: pools/devices are no longer deleted when a GPU is merely missing on
        # startup — devices are soft-disabled (Device.available=False) and the
        # watchdog re-activates everything once the GPU reappears. Only genuinely
        # under-membered pools (a user removed members) are pruned here.
        removed_pools = delete_pools_with_insufficient_members(db, inference_manager)
        db.commit()
        for removed_pool in removed_pools:
            log_event(
                db,
                "pool.deleted",
                details={
                    "pool_id": removed_pool.pool_id,
                    "pool_name": removed_pool.pool_name,
                    "reason": "insufficient_members_on_startup",
                    "device_ids": removed_pool.member_device_ids,
                    "reverted_model_ids": removed_pool.reverted_model_ids,
                },
            )
        get_or_create_app_settings(db)
        web_search_api.seed_providers(db)
        models.scan_models_dir(db)
        if settings.auto_load_activated_models_on_startup:
            activated_models = (
                db.query(ModelConfig)
                .filter(ModelConfig.activated.is_(True))
                .order_by(ModelConfig.priority.asc(), ModelConfig.id.asc())
                .all()
            )
            for model in activated_models:
                try:
                    resolution = await models._resolve_device_for_model(db, model, inference_manager)
                    if resolution is None:
                        raise RuntimeError("No enabled device available for model")
                    if isinstance(resolution, PoolActivationTarget):
                        await inference_manager.activate_model_on_pool(model, resolution)
                    else:
                        await inference_manager.activate_model(model, resolution)
                except Exception:
                    # Keep activated=True so the watchdog keeps retrying (e.g. the GPU
                    # is still initializing). Do not flip it off on a transient failure.
                    logger.exception(
                        "Failed to auto-load model %s during startup; watchdog will retry", model.alias
                    )
            db.commit()
    finally:
        db.close()

    pruning_task = asyncio.create_task(schedule_daily_pruning())
    ssl_renewal_task = asyncio.create_task(schedule_daily_ssl_renewal())
    watchdog_task = (
        asyncio.create_task(schedule_device_watchdog()) if settings.device_watchdog_enabled else None
    )

    yield

    pruning_task.cancel()
    ssl_renewal_task.cancel()
    if watchdog_task is not None:
        watchdog_task.cancel()

    for model_id in list(inference_manager._running.keys()):
        await inference_manager.deactivate_model(model_id, reason=DeactivateReason.SHUTDOWN)


app = FastAPI(title=settings.app_name, lifespan=lifespan)


def _cors_allowed_origins() -> list[str]:
    origins = [settings.frontend_origin]
    db = SessionLocal()
    try:
        app_settings = get_or_create_app_settings(db)
        public_url = (app_settings.public_url or "").strip()
        if public_url and public_url not in origins:
            origins.append(public_url)
    except OperationalError:
        logger.warning("Could not read app settings for CORS origins; using frontend_origin only")
    finally:
        db.close()
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=Path(settings.data_dir)), name="static")

models.router.inference_manager = inference_manager  # type: ignore[attr-defined]
openai_compat.router.inference_manager = inference_manager  # type: ignore[attr-defined]
status.router.inference_manager = inference_manager  # type: ignore[attr-defined]
devices.router.inference_manager = inference_manager  # type: ignore[attr-defined]

app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(terms_api.router)
app.include_router(ssl_api.router)
app.include_router(web_search_api.router)
app.include_router(knowledge_base.router)
app.include_router(logs.router)
app.include_router(openai_compat.router)
app.include_router(status.router)
app.include_router(tasks.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
    return {"name": settings.app_name, "status": "running"}
