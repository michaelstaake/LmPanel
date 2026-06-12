import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, chat, devices, knowledge_base, logs, models, openai_compat, ssl as ssl_api, status, terms as terms_api, web_search as web_search_api
from app.core.activity_logger import log_event, prune_old_logs, schedule_daily_pruning
from app.core.letsencrypt import schedule_daily_ssl_renewal
from app.core.update_check import schedule_update_check
from app.core.app_settings import get_or_create_app_settings
from app.core.config import get_settings
from app.core.db import SessionLocal
from sqlalchemy.exc import OperationalError
from app.core.device_manager import DeviceManager
from app.core.gpu_pool_manager import (
    delete_pools_with_insufficient_members,
    delete_pools_with_unavailable_devices,
    delete_stale_pool_memberships,
)
from app.core.inference_manager import InferenceManager, PoolActivationTarget
from app.core.logging import configure_logging
from app.core import token_usage as _token_usage
from app.models.model_config import ModelConfig
from app.api import tasks
settings = get_settings()
Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
Path(settings.data_dir, "backgrounds").mkdir(parents=True, exist_ok=True)
device_manager = DeviceManager()
inference_manager = InferenceManager()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.app_log_level)
    Path(settings.models_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.data_dir, "backgrounds").mkdir(parents=True, exist_ok=True)

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
        detected_hardware_ids = {device.hardware_id for device in device_manager.detect_all()}
        removed_pools = delete_pools_with_unavailable_devices(db, detected_hardware_ids, inference_manager)
        removed_pools.extend(delete_pools_with_insufficient_members(db, inference_manager))
        db.commit()
        for removed_pool in removed_pools:
            log_event(
                db,
                "pool.deleted",
                details={
                    "pool_id": removed_pool.pool_id,
                    "pool_name": removed_pool.pool_name,
                    "reason": "device_unavailable_on_startup",
                    "device_ids": removed_pool.member_device_ids,
                    "reverted_model_ids": removed_pool.reverted_model_ids,
                },
            )
        get_or_create_app_settings(db)
        web_search_api.seed_providers(db)
        models.scan_models_dir(db)
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
                logger.exception("Failed to auto-load model %s during startup", model.alias)
                model.activated = False
                db.add(model)
        db.commit()
    finally:
        db.close()

    pruning_task = asyncio.create_task(schedule_daily_pruning())
    ssl_renewal_task = asyncio.create_task(schedule_daily_ssl_renewal())
    update_check_task = asyncio.create_task(schedule_update_check())

    yield

    pruning_task.cancel()
    ssl_renewal_task.cancel()
    update_check_task.cancel()

    for model_id in list(inference_manager._running.keys()):
        await inference_manager.deactivate_model(model_id)


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
