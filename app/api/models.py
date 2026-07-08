import asyncio
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.core.activity_logger import log_event
from app.core.config import get_settings
from app.core.db import SessionLocal, get_db
from app.core.device_manager import is_supported_vendor
from app.core.gguf import read_gguf_max_context_length
from app.core.gguf_shards import (
    collect_shard_files,
    iter_model_gguf_files,
    parse_gguf_shard_name,
    resolve_primary_shard,
    strip_shard_suffix,
    validate_shard_set,
    validate_upload_shard_set,
)
from app.core.gpu_pool_manager import get_pooled_device_ids, is_pooled_device, ordered_pool_devices
from app.core.inference_manager import InferenceManager, PoolActivationTarget
from app.core.model_activation import InsufficientVramError
from app.core.model_device_resolution import (
    best_fitting_pool_member,
    pick_best_pool_candidate,
    resolve_fitting_gpu,
)
from app.core.pool_lifecycle import log_pool_event
from app.core.vram_preflight import (
    assert_pool_members_vram_available,
    estimate_model_vram_need_mb,
)
from app.models.device import Device
from app.models.gpu_pool import GpuPool, GpuPoolDevice
from app.models.model_config import ModelConfig
from app.models.user import User
from app.core.model_upload_stream import stream_model_upload
from app.core.task_manager import task_manager
from app.core.v1_models_cache import invalidate_v1_models_cache
from app.utils.schemas import ModelReorderRequest, ModelUpdateRequest

router = APIRouter(prefix="/api/models", tags=["models"])

ALLOWED_ASSIGNMENT_MODES = {"auto", "pinned", "pool"}
UPLOAD_CHUNK_BYTES = 1024 * 1024
ALLOWED_MODEL_ASSET_SUFFIXES = {".gguf", ".json", ".txt", ".yaml", ".yml", ".bin", ".safetensors"}
FETCH_JOB_TTL_SECONDS = 30 * 60  # 30 minutes

# In-memory store for fetch job progress: job_id -> progress dict
_fetch_jobs: dict[str, dict] = {}

class FetchModelRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)


class FetchJobProgress(BaseModel):
    job_id: str
    status: str  # "downloading" | "processing" | "completed" | "error"
    downloaded: int
    total: int | None
    percent: int
    file_name: str | None = None
    model: dict | None = None
    error: str | None = None


def _set_fetch_job_error(job_id: str, error: str) -> None:
    job = _fetch_jobs.get(job_id)
    if not job:
        return
    job["status"] = "error"
    job["error"] = error
    task_manager.fail_task(job_id, error)


def _set_fetch_job_cancelled(job_id: str) -> None:
    job = _fetch_jobs.get(job_id)
    if not job:
        return
    job["status"] = "cancelled"
    job["error"] = None
    task_manager.mark_cancelled(job_id)


def _set_upload_job_error(task_id: str, error: str) -> None:
    task_manager.fail_task(task_id, error)


def _parse_content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _upload_progress(written: int, total: int | None) -> float:
    if not total:
        return 0.0
    return min(1.0, written / total)


def _register_uploaded_model(
    db: Session,
    primary_file_name: str,
    model_dir_name: str,
    model_dir: Path,
    uploaded_file_names: list[str],
) -> ModelConfig:
    settings = get_settings()
    primary_destination = model_dir / primary_file_name
    model = ModelConfig(
        priority=_next_model_priority(db),
        file_name=primary_file_name,
        model_dir_name=model_dir_name,
        file_path=str(primary_destination.resolve()),
        alias=_build_unique_alias(db, strip_shard_suffix(primary_file_name)),
        context_length=settings.default_context_length,
        gpu_layers=settings.default_gpu_layers,
        threads=settings.default_threads,
        temperature=settings.default_temperature,
        top_p=settings.default_top_p,
        min_p=settings.default_min_p,
        top_k=settings.default_top_k,
        presence_penalty=settings.default_presence_penalty,
        repetition_penalty=settings.default_repetition_penalty,
        mmproj_file_name=_detect_mmproj_file_name(model_dir, primary_file_name),
    )
    try:
        db.add(model)
        db.commit()
        db.refresh(model)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Uploaded model could not be registered") from exc

    log_event(
        db,
        "model.uploaded",
        details={"file_name": primary_file_name, "alias": model.alias, "files": uploaded_file_names},
    )
    return model


async def _run_fetch_job(
    job_id: str,
    url: str,
    file_name: str,
    model_dir_name: str,
    model_dir: Path,
    destination: Path,
    max_bytes: int,
) -> None:
    db = SessionLocal()
    settings = get_settings()
    written = 0

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=3600.0) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    error = f"Server returned status {response.status_code}"
                    _set_fetch_job_error(job_id, error)
                    return

                total = int(response.headers.get("content-length", 0))
                _fetch_jobs[job_id]["total"] = total

                try:
                    model_dir.mkdir(parents=True, exist_ok=False)
                except FileExistsError:
                    _set_fetch_job_error(job_id, "Model directory already exists")
                    return

                with destination.open("wb") as output_file:
                    async for chunk in response.aiter_bytes(chunk_size=UPLOAD_CHUNK_BYTES):
                        if not chunk:
                            break

                        output_file.write(chunk)
                        written += len(chunk)
                        _fetch_jobs[job_id]["downloaded"] = written
                        _fetch_jobs[job_id]["percent"] = min(100, int((written / total) * 100)) if total > 0 else 0
                        task_manager.update_task(job_id, progress=min(1.0, written / total) if total > 0 else 0.0)

                        if written > max_bytes:
                            _remove_model_dir(model_dir)
                            error = f"Downloaded file exceeds the {settings.max_upload_size_mb} MB limit"
                            _set_fetch_job_error(job_id, error)
                            return

        _fetch_jobs[job_id]["downloaded"] = written
        _fetch_jobs[job_id]["percent"] = min(100, int((written / _fetch_jobs[job_id]["total"]) * 100)) if _fetch_jobs[job_id]["total"] and _fetch_jobs[job_id]["total"] > 0 else 100
        _fetch_jobs[job_id]["status"] = "processing"

        existing_model = db.query(ModelConfig).filter(ModelConfig.file_name == file_name).first()
        if existing_model:
            _remove_model_dir(model_dir)
            _set_fetch_job_error(job_id, "A model with that file name already exists")
            return

        model = ModelConfig(
            priority=_next_model_priority(db),
            file_name=file_name,
            model_dir_name=model_dir_name,
            file_path=str(destination.resolve()),
            alias=_build_unique_alias(db, Path(file_name).stem),
            context_length=settings.default_context_length,
            gpu_layers=settings.default_gpu_layers,
            threads=settings.default_threads,
            temperature=settings.default_temperature,
            top_p=settings.default_top_p,
        min_p=settings.default_min_p,
            repetition_penalty=settings.default_repetition_penalty,
            mmproj_file_name=_detect_mmproj_file_name(model_dir, file_name),
        )
        try:
            db.add(model)
            db.commit()
            db.refresh(model)
        except SQLAlchemyError:
            db.rollback()
            _remove_model_dir(model_dir)
            _set_fetch_job_error(job_id, "Fetched model could not be registered")
            return

        _fetch_jobs[job_id]["status"] = "completed"
        _fetch_jobs[job_id]["model"] = _serialize_model(model)
        _fetch_jobs[job_id]["model_id"] = model.id
        task_manager.complete_task(job_id)

        log_event(db, "model.fetched", details={"file_name": file_name, "alias": model.alias, "url": url})
    except asyncio.CancelledError:
        _remove_model_dir(model_dir)
        _set_fetch_job_cancelled(job_id)
        raise
    except Exception as exc:
        _remove_model_dir(model_dir)
        _set_fetch_job_error(job_id, f"Failed to download file: {exc}")
    finally:
        db.close()


def scan_models_dir(db: Session) -> tuple[int, int]:
    settings = get_settings()
    models_dir = Path(settings.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    existing_by_file = {m.file_name: m for m in db.query(ModelConfig).all()}
    added = 0
    discovered_files = list(_iter_model_files(models_dir))
    for model_dir_name, file_name, file_path in discovered_files:
        if file_name in existing_by_file:
            continue
        model = ModelConfig(
            priority=_next_model_priority(db),
            file_name=file_name,
            model_dir_name=model_dir_name,
            file_path=str(file_path.resolve()),
            alias=_build_unique_alias(db, strip_shard_suffix(file_name)),
            context_length=settings.default_context_length,
            gpu_layers=settings.default_gpu_layers,
            threads=settings.default_threads,
            temperature=settings.default_temperature,
            top_p=settings.default_top_p,
            top_k=settings.default_top_k,
            presence_penalty=settings.default_presence_penalty,
            repetition_penalty=settings.default_repetition_penalty,
            mmproj_file_name=_detect_mmproj_file_name(file_path.parent, file_name),
        )
        db.add(model)
        existing_by_file[file_name] = model
        added += 1

    db.commit()
    return len(discovered_files), added


@router.get("")
async def list_models(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[dict]:
    inference: InferenceManager = router.inference_manager  # type: ignore[attr-defined]
    rows = db.query(ModelConfig).order_by(ModelConfig.priority.asc(), ModelConfig.id.asc()).all()
    result: list[dict] = []
    for model in rows:
        serialized = _serialize_model(model)
        runtime = await inference.resolve_runtime_state(model.id, activated=model.activated)
        serialized.update(runtime)
        result.append(serialized)
    return result


@router.post("/reorder")
def reorder_models(payload: ModelReorderRequest, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    for item in payload.models:
        model = db.query(ModelConfig).filter(ModelConfig.id == item.id).first()
        if model:
            model.priority = item.priority
            db.add(model)
    db.commit()
    return {"status": "ok"}


@router.post("/upload")
async def upload_model(
    request: Request,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    from starlette.formparsers import MultiPartException

    settings = get_settings()
    models_dir = Path(settings.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = max(1, settings.max_upload_size_mb) * 1024 * 1024
    upload_task_id = str(uuid.uuid4())
    staging_dir = models_dir / f".upload-{upload_task_id}"
    total_bytes = _parse_content_length(request)

    task_manager.add_task(
        task_id=upload_task_id,
        task_type="model_upload",
        description="Uploading model",
        metadata={},
    )

    def on_progress(written: int) -> None:
        task_manager.update_task(
            upload_task_id,
            progress=_upload_progress(written, total_bytes),
        )

    try:
        result = await stream_model_upload(
            request,
            model_dir=staging_dir,
            max_bytes=max_bytes,
            on_progress=on_progress,
        )
    except MultiPartException as exc:
        _remove_model_dir(staging_dir)
        detail = exc.message
        _set_upload_job_error(upload_task_id, detail)
        status_code = 413 if "size limit" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except OSError as exc:
        _remove_model_dir(staging_dir)
        error = f"Failed to store uploaded model: {exc}"
        _set_upload_job_error(upload_task_id, error)
        raise HTTPException(status_code=500, detail=error) from exc

    upload_names = [streamed.filename for streamed in result.files]
    if any(not name for name in upload_names):
        _remove_model_dir(staging_dir)
        _set_upload_job_error(upload_task_id, "Missing file name")
        raise HTTPException(status_code=400, detail="Missing file name")

    try:
        primary_file_name, normalized_names = validate_upload_shard_set(upload_names)
    except ValueError as exc:
        _remove_model_dir(staging_dir)
        _set_upload_job_error(upload_task_id, str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    model_dir_name = _build_unique_model_dir_name(db, strip_shard_suffix(primary_file_name))
    model_dir = models_dir / model_dir_name

    for upload_name in normalized_names:
        existing_model = db.query(ModelConfig).filter(ModelConfig.file_name == upload_name).first()
        if existing_model or (model_dir / upload_name).exists():
            _remove_model_dir(staging_dir)
            _set_upload_job_error(upload_task_id, f"A model file named {upload_name} already exists")
            raise HTTPException(status_code=409, detail=f"A model file named {upload_name} already exists")

    try:
        staging_dir.rename(model_dir)
    except OSError as exc:
        _remove_model_dir(staging_dir)
        error = f"Failed to store uploaded model: {exc}"
        _set_upload_job_error(upload_task_id, error)
        raise HTTPException(status_code=500, detail=error) from exc

    task_manager.update_task(
        upload_task_id,
        description=(
            f"Uploading model: {primary_file_name}"
            if len(normalized_names) == 1
            else f"Uploading sharded model: {primary_file_name} ({len(normalized_names)} files)"
        ),
        metadata={"file_name": primary_file_name, "files": normalized_names},
    )

    try:
        _register_uploaded_model(
            db,
            primary_file_name,
            model_dir_name,
            model_dir,
            normalized_names,
        )
    except HTTPException as exc:
        _remove_model_dir(model_dir)
        _set_upload_job_error(upload_task_id, str(exc.detail))
        raise
    except SQLAlchemyError:
        db.rollback()
        _remove_model_dir(model_dir)
        _set_upload_job_error(upload_task_id, "Uploaded model could not be registered")
        raise HTTPException(status_code=500, detail="Uploaded model could not be registered")

    task_manager.complete_task(upload_task_id)
    return {"status": "ok", "task_id": upload_task_id}


@router.post("/scan")
def scan_models(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    discovered, added = scan_models_dir(db)
    log_event(db, "model.scanned", details={"discovered": discovered, "added": added})
    return {"status": "ok", "discovered": discovered, "added": added}


def _normalize_fetch_url(url: str) -> str:
    return url.split("?", 1)[0]


@router.post("/fetch")
async def fetch_model(
    payload: FetchModelRequest,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    fetch_url = _normalize_fetch_url(payload.url.strip())

    # Validate URL
    try:
        parsed = urlparse(fetch_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https")
        if not parsed.netloc:
            raise ValueError("Invalid URL")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Validate .gguf extension
    url_path = parsed.path.lower()
    if not url_path.endswith(".gguf"):
        raise HTTPException(status_code=400, detail="URL must point to a .gguf file")

    job_id = str(uuid.uuid4())

    settings = get_settings()
    models_dir = Path(settings.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    file_name = Path(url_path).name
    model_dir_name = _build_unique_model_dir_name(db, Path(file_name).stem)
    model_dir = models_dir / model_dir_name
    destination = model_dir / file_name

    max_bytes = max(1, settings.max_upload_size_mb) * 1024 * 1024

    _fetch_jobs[job_id] = {
        "job_id": job_id,
        "status": "downloading",
        "downloaded": 0,
        "total": None,
        "percent": 0,
        "file_name": file_name,
        "model": None,
        "error": None,
        "created_at": datetime.now(timezone.utc),
        "model_dir_name": model_dir_name,
    }

    fetch_task = asyncio.create_task(_run_fetch_job(job_id, fetch_url, file_name, model_dir_name, model_dir, destination, max_bytes))
    task_manager.add_task(
        task_id=job_id,
        task_type="model_fetch",
        description=f"Fetching model: {file_name}",
        async_task=fetch_task,
        metadata={"file_name": file_name, "url": fetch_url},
    )
    return {"status": "ok", "job_id": job_id}


@router.get("/fetch/{job_id}")
def get_fetch_progress(job_id: str, _: User = Depends(get_admin_user)) -> dict:
    job = _fetch_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Fetch job not found")

    # TTL cleanup: remove jobs older than 30 minutes
    if job.get("created_at"):
        age = (datetime.now(timezone.utc) - job["created_at"]).total_seconds()
        if age > FETCH_JOB_TTL_SECONDS:
            # Clean up partial model directory if job failed
            if job.get("status") in ("error", "downloading") and job.get("model_dir_name"):
                settings = get_settings()
                model_dir = Path(settings.models_dir) / job["model_dir_name"]
                if model_dir.exists():
                    shutil.rmtree(model_dir)
            del _fetch_jobs[job_id]
            raise HTTPException(status_code=404, detail="Fetch job expired")

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "downloaded": job["downloaded"],
        "total": job["total"],
        "percent": job["percent"],
        "file_name": job.get("file_name"),
        "model": job.get("model"),
        "error": job.get("error"),
    }


@router.delete("/fetch/{job_id}")
def delete_fetch_job(job_id: str, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    job = _fetch_jobs.pop(job_id, None)
    if not job:
        raise HTTPException(status_code=404, detail="Fetch job not found")

    # Clean up partial model directory if job failed or was downloading
    if job.get("status") in ("error", "downloading") and job.get("model_dir_name"):
        settings = get_settings()
        model_dir = Path(settings.models_dir) / job["model_dir_name"]
        if model_dir.exists():
            shutil.rmtree(model_dir)

    return {"status": "ok"}


@router.post("/{model_id}/files")
def upload_model_files(
    model_id: int,
    files: list[UploadFile] = File(...),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="No files were provided")

    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    model_dir = _model_directory_path(model)
    model_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = max(1, get_settings().max_upload_size_mb) * 1024 * 1024
    uploaded_files: list[str] = []

    try:
        for upload in files:
            asset_name = Path(upload.filename or "").name
            if not asset_name:
                raise HTTPException(status_code=400, detail="Missing file name")
            if asset_name == model.file_name:
                raise HTTPException(status_code=409, detail="Add Files cannot replace the primary model file")
            if not _is_allowed_asset_file(asset_name):
                raise HTTPException(status_code=400, detail=f"Unsupported model asset file: {asset_name}")

            destination = model_dir / asset_name
            written = 0
            try:
                with destination.open("wb") as output:
                    while True:
                        chunk = upload.file.read(UPLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_bytes:
                            output.close()
                            destination.unlink(missing_ok=True)
                            raise HTTPException(
                                status_code=413,
                                detail=f"Uploaded file exceeds the {get_settings().max_upload_size_mb} MB limit",
                            )
                        output.write(chunk)
            except OSError as exc:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=500, detail=f"Failed to store model asset: {asset_name}") from exc
            finally:
                upload.file.close()

            uploaded_files.append(asset_name)

        model.mmproj_file_name = _detect_mmproj_file_name(model_dir, model.file_name)
        db.add(model)
        db.commit()
        db.refresh(model)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Uploaded model files could not be registered") from exc

    log_event(db, "model.files_uploaded", details={"alias": model.alias, "files": uploaded_files, "model_id": model.id})
    return {"status": "ok", "uploaded": uploaded_files, "model": _serialize_model(model)}


@router.delete("/{model_id}/files/{file_name}")
def delete_model_file(
    model_id: int,
    file_name: str,
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if model.activated:
        raise HTTPException(status_code=409, detail="Disable this model before deleting files from it")

    model_dir = _model_directory_path(model)
    destination = _resolve_model_asset_path(model_dir, file_name)
    if not destination.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    if _is_protected_model_file(model, destination.name):
        raise HTTPException(status_code=409, detail="Cannot delete the primary model file or its shards")

    if model.vision_enabled and model.mmproj_file_name == destination.name:
        raise HTTPException(
            status_code=409,
            detail="Disable vision capability or upload a replacement mmproj file before deleting this one",
        )

    deleted_name = destination.name
    try:
        destination.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete model asset: {deleted_name}") from exc

    model.mmproj_file_name = _detect_mmproj_file_name(model_dir, model.file_name)
    db.add(model)
    db.commit()
    db.refresh(model)

    log_event(db, "model.file_deleted", details={"alias": model.alias, "file": deleted_name, "model_id": model.id})
    return {"status": "ok", "deleted": deleted_name, "model": _serialize_model(model)}


@router.patch("/{model_id}")
async def update_model(model_id: int, payload: ModelUpdateRequest, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    inference: InferenceManager = router.inference_manager  # type: ignore[attr-defined]
    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    normalized_alias = None
    if payload.alias is not None:
        normalized_alias = payload.alias.strip() or _default_model_alias(model)

    was_activated = model.activated
    next_assignment_mode = payload.assignment_mode or model.assignment_mode
    next_pinned_device_id = model.pinned_device_id
    next_pinned_pool_id = model.pinned_pool_id

    if payload.assignment_mode is not None and payload.assignment_mode not in ALLOWED_ASSIGNMENT_MODES:
        raise HTTPException(status_code=400, detail="Invalid assignment mode")

    if next_assignment_mode == "auto":
        next_pinned_device_id = None
        next_pinned_pool_id = None
    elif next_assignment_mode == "pinned":
        if payload.pinned_device_id is not None:
            next_pinned_device_id = payload.pinned_device_id
        next_pinned_pool_id = None
    elif next_assignment_mode == "pool":
        if payload.pinned_pool_id is not None:
            next_pinned_pool_id = payload.pinned_pool_id
        next_pinned_device_id = None

    if next_assignment_mode == "pinned":
        if next_pinned_device_id is None:
            raise HTTPException(status_code=400, detail="Pinned assignment requires a device")
        pinned_device = db.query(Device).filter(Device.id == next_pinned_device_id).first()
        if not pinned_device:
            raise HTTPException(status_code=404, detail="Pinned device not found")
        if is_pooled_device(db, next_pinned_device_id):
            raise HTTPException(status_code=409, detail="Models cannot be pinned directly to a GPU that belongs to a pool")

    if next_assignment_mode == "pool":
        if next_pinned_pool_id is None:
            raise HTTPException(status_code=400, detail="Pool assignment requires a GPU pool")
        pinned_pool = db.query(GpuPool).filter(GpuPool.id == next_pinned_pool_id).first()
        if not pinned_pool:
            raise HTTPException(status_code=404, detail="GPU pool not found")

    if normalized_alias is not None:
        alias_conflict = (
            db.query(ModelConfig)
            .filter(ModelConfig.alias == normalized_alias, ModelConfig.id != model_id)
            .first()
        )
        if alias_conflict:
            raise HTTPException(status_code=409, detail="A model with that alias already exists")

    for field in [
        "alias",
        "description",
        "system_prompt",
        "chat_template",
        "context_length",
        "gpu_layers",
        "threads",
        "temperature",
        "top_p",
        "min_p",
        "top_k",
        "presence_penalty",
        "repetition_penalty",
        "tool_calling_enabled",
        "discourage_thinking",
        "default_thinking_enabled",
        "thinking_capability",
        "vision_enabled",
        "web_search_enabled",
        "rag_enabled",
        "flash_attention_enabled",
        "memory_mapping_enabled",
    ]:
        value = normalized_alias if field == "alias" else getattr(payload, field)
        if value is not None:
            setattr(model, field, value)

    for nullable_field in ("batch_size", "ubatch_size", "cache_type_k", "cache_type_v"):
        if nullable_field in payload.model_fields_set:
            setattr(model, nullable_field, getattr(payload, nullable_field))

    model.assignment_mode = next_assignment_mode
    model.pinned_device_id = next_pinned_device_id
    model.pinned_pool_id = next_pinned_pool_id

    db.add(model)
    db.commit()
    db.refresh(model)

    if was_activated:
        await inference.deactivate_model(model.id)
        model.activated = False
        db.add(model)
        db.commit()
        invalidate_v1_models_cache()

        _ensure_model_vision_assets(model)
        _ensure_model_shard_assets(model)

        resolution = await _resolve_device_for_model(db, model, inference)
        if resolution is None:
            raise HTTPException(status_code=409, detail="No enabled device available for model")

        try:
            if isinstance(resolution, PoolActivationTarget):
                await inference.activate_model_on_pool(model, resolution)
            else:
                await inference.activate_model(model, resolution)
        except RuntimeError as exc:
            log_event(db, "model.activation_failed", details={"alias": model.alias, "error": str(exc)})
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        model.activated = True
        db.add(model)
        db.commit()
        db.refresh(model)
        invalidate_v1_models_cache()

    log_event(db, "model.updated", details={"alias": model.alias, "model_id": model_id})
    return {"status": "ok", "model": _serialize_model(model)}


@router.post("/{model_id}/activate")
async def activate_model(model_id: int, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    inference: InferenceManager = router.inference_manager  # type: ignore[attr-defined]
    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    _ensure_model_vision_assets(model)
    _ensure_model_shard_assets(model)

    resolution = await _resolve_device_for_model(db, model, inference)
    if resolution is None:
        raise HTTPException(status_code=409, detail="No enabled device available for model")

    activation_started_at = time.perf_counter()

    try:
        if isinstance(resolution, PoolActivationTarget):
            await inference.activate_model_on_pool(model, resolution)
            model.activated = True
            db.add(model)
            db.commit()
            invalidate_v1_models_cache()
            log_event(db, "model.activated", details={"alias": model.alias, "pool_id": resolution.pool_id, "pool_name": resolution.pool_name})
            return {
                "status": "ok",
                "model_id": model.id,
                "pool_id": resolution.pool_id,
                "elapsed_seconds": round(time.perf_counter() - activation_started_at, 2),
            }
        else:
            await inference.activate_model(model, resolution)
            model.activated = True
            db.add(model)
            db.commit()
            invalidate_v1_models_cache()
            log_event(db, "model.activated", details={"alias": model.alias, "device_id": resolution.id, "device_name": resolution.name})
            return {
                "status": "ok",
                "model_id": model.id,
                "device_id": resolution.id,
                "elapsed_seconds": round(time.perf_counter() - activation_started_at, 2),
            }
    except RuntimeError as exc:
        log_event(db, "model.activation_failed", details={"alias": model.alias, "error": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{model_id}/deactivate")
def deactivate_model(model_id: int, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    inference: InferenceManager = router.inference_manager  # type: ignore[attr-defined]
    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    inference.deactivate_model_sync(model.id)
    inference.clear_recovery_state(model.id)
    model.activated = False
    db.add(model)
    db.commit()
    invalidate_v1_models_cache()
    log_event(db, "model.deactivated", details={"alias": model.alias})
    return {"status": "ok"}


@router.delete("/{model_id}")
def delete_model(model_id: int, _: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> dict:
    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.activated:
        raise HTTPException(status_code=409, detail="Disable this model before deleting it")

    model_alias = model.alias
    model_dir = _model_directory_path(model)

    try:
        if model_dir.exists():
            shutil.rmtree(model_dir)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Failed to delete model file") from exc

    db.delete(model)
    db.commit()
    log_event(db, "model.deleted", details={"alias": model_alias, "model_id": model_id})
    return {"status": "ok"}


async def _resolve_device_for_model(db: Session, model: ModelConfig, inference: InferenceManager) -> Device | PoolActivationTarget | None:
    supported_vendors = [vendor for vendor in ["cpu", "vulkan"] if is_supported_vendor(vendor)]
    model_size_mb = _estimate_model_size_mb(model)
    settings = get_settings()
    vram_need_mb = estimate_model_vram_need_mb(model, settings)
    memory_metrics = await inference.get_device_memory_mb()

    # POOL mode — model is pinned to the GPU pool
    if model.assignment_mode == "pool" and model.pinned_pool_id:
        pool = db.query(GpuPool).filter(GpuPool.id == model.pinned_pool_id).first()
        if not pool:
            raise HTTPException(status_code=409, detail="Assigned GPU pool no longer exists")
        target = _build_pool_target(db, pool, require_enabled=True)
        if len(target.devices) < 2:
            raise HTTPException(status_code=409, detail="GPU pool has fewer than two devices")
        _validate_pool_stable_ids(target)
        if not inference.has_runtime_for_vendor(target.runtime_vendor):
            raise HTTPException(status_code=409, detail=f"No inference runtime configured for {pool.vendor} (required for GPU pool)")

        if model.gpu_layers > 0 and vram_need_mb > 0:
            try:
                assert_pool_members_vram_available(
                    model=model,
                    target=target,
                    memory_metrics=memory_metrics,
                    settings=settings,
                )
            except InsufficientVramError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        elif model_size_mb > 0:
            combined_total, combined_available, totals_verified = _pool_combined_memory_mb(target, memory_metrics)
            if not totals_verified:
                raise HTTPException(
                    status_code=409,
                    detail="GPU pool capacity could not be verified from runtime metrics",
                )
            if model_size_mb > combined_available:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Model requires ~{model_size_mb} MB but the GPU pool only has "
                        f"{combined_available} MB combined available"
                    ),
                )
        # Prefer one GPU when the model fits to avoid unnecessary pool overhead.
        if get_settings().pool_prefer_single_gpu_when_fit and model_size_mb > 0:
            single_gpu = best_fitting_pool_member(target, model_size_mb, memory_metrics)
            if single_gpu is not None:
                log_pool_event(
                    "single_gpu_fallback",
                    pool_id=pool.id,
                    model_id=model.id,
                    device_id=single_gpu.id,
                    split_mode=pool.split_mode,
                )
                return single_gpu
        return target

    if model.assignment_mode == "pinned" and model.pinned_device_id:
        device = (
            db.query(Device)
            .filter(
                Device.id == model.pinned_device_id,
                Device.enabled.is_(True),
                Device.available.is_(True),
                Device.vendor.in_(supported_vendors),
            )
            .first()
        )
        if device and not inference.has_runtime_for_vendor(device.vendor):
            raise HTTPException(
                status_code=409,
                detail=f"No inference runtime configured for pinned device vendor: {device.vendor}",
            )
        if device and model_size_mb > 0:
            metrics = memory_metrics.get(device.hardware_id, {})
            total_mb = metrics.get("total_mb", 0)
            available_mb = metrics.get("available_mb", 0)
            # Only reject if we have valid total metrics (total=0 means metrics unavailable)
            if total_mb > 0 and model_size_mb > available_mb:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Model requires ~{model_size_mb} MB but {device.name} only has "
                        f"{available_mb} MB available"
                    ),
                )
        return device

    # AUTO mode — prefer a single GPU when the model fits, then pool, then CPU
    candidates = (
        db.query(Device)
        .filter(Device.enabled.is_(True), Device.available.is_(True), Device.vendor.in_(supported_vendors))
        .all()
    )
    pooled_device_ids = get_pooled_device_ids(db)

    gpu_candidates = [
        c for c in candidates
        if c.vendor != "cpu" and c.id not in pooled_device_ids and inference.has_runtime_for_vendor(c.vendor)
    ]
    cpu_candidates = [c for c in candidates if c.vendor == "cpu" and inference.has_runtime_for_vendor(c.vendor)]

    fitting_gpu = resolve_fitting_gpu(gpu_candidates, model_size_mb, memory_metrics)
    if fitting_gpu is not None:
        return fitting_gpu

    # Pool members are excluded from gpu_candidates, but layer-split decode is much
    # slower — use one pool GPU when the model fits on a single card.
    if model_size_mb > 0:
        best_pool_member: tuple[Device, int] | None = None
        for pool in db.query(GpuPool).order_by(GpuPool.id.asc()).all():
            if pool.split_mode != "layer":
                continue
            target = _build_pool_target(db, pool, require_enabled=True)
            if len(target.devices) < 2:
                continue
            single_gpu = best_fitting_pool_member(target, model_size_mb, memory_metrics)
            if single_gpu is None:
                continue
            available_mb = memory_metrics.get(single_gpu.hardware_id, {}).get("available_mb", 0)
            if best_pool_member is None or available_mb > best_pool_member[1]:
                best_pool_member = (single_gpu, available_mb)
        if best_pool_member is not None:
            return best_pool_member[0]

    pool_candidates: list[tuple[PoolActivationTarget, int]] = []
    for pool in db.query(GpuPool).order_by(GpuPool.id.asc()).all():
        target = _build_pool_target(db, pool, require_enabled=True)
        if len(target.devices) < 2 or not inference.has_runtime_for_vendor(target.runtime_vendor):
            continue

        _, combined_available, totals_verified = _pool_combined_memory_mb(target, memory_metrics)
        pool_fits = vram_need_mb == 0 or (totals_verified and combined_available >= vram_need_mb)
        if pool_fits:
            pool_candidates.append((target, combined_available))

    pool_target = pick_best_pool_candidate(pool_candidates)
    if pool_target is not None:
        _validate_pool_stable_ids(pool_target)
        return pool_target

    if not gpu_candidates and not cpu_candidates:
        if candidates:
            raise HTTPException(status_code=409, detail="No inference runtime configured for any enabled device")
        return None

    # CPU fallback
    if cpu_candidates:
        cpu = sorted(cpu_candidates, key=lambda c: (c.priority, c.id))[0]
        if model_size_mb > 0 and memory_metrics:
            metrics = memory_metrics.get(cpu.hardware_id, {})
            total_mb = metrics.get("total_mb", 0)
            available_mb = metrics.get("available_mb", 0)
            if total_mb > 0 and model_size_mb > available_mb:
                if gpu_candidates:
                    best_gpu_avail = max(
                        memory_metrics.get(g.hardware_id, {}).get("available_mb", 0)
                        for g in gpu_candidates
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Model requires ~{model_size_mb} MB. "
                            f"Best GPU has {best_gpu_avail} MB available and "
                            f"CPU has {available_mb} MB available — no device can fit this model"
                        ),
                    )
                raise HTTPException(
                    status_code=409,
                    detail=f"Model requires ~{model_size_mb} MB but CPU only has {available_mb} MB available",
                )
        return cpu

    # GPUs exist but none fit and there is no CPU to fall back to
    if gpu_candidates:
        best_gpu_avail = max(
            memory_metrics.get(g.hardware_id, {}).get("available_mb", 0)
            for g in gpu_candidates
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Model requires ~{model_size_mb} MB but no GPU has sufficient free VRAM "
                f"(best available: {best_gpu_avail} MB) and no CPU device is enabled"
            ),
        )

    return None


def _pool_combined_available_mb(target: PoolActivationTarget, memory_metrics: dict) -> int:
    return _pool_combined_memory_mb(target, memory_metrics)[1]


def _pool_combined_memory_mb(target: PoolActivationTarget, memory_metrics: dict) -> tuple[int, int, bool]:
    combined_total = 0
    total = 0
    for device in target.devices:
        metrics = memory_metrics.get(device.hardware_id, {})
        total_mb = metrics.get("total_mb", 0)
        available_mb = metrics.get("available_mb", 0)
        if total_mb <= 0:
            return 0, 0, False
        combined_total += total_mb
        total += available_mb
    return combined_total, total, True


def _validate_pool_stable_ids(target: PoolActivationTarget) -> None:
    if len(target.devices) < 2:
        return
    missing = [
        device.hardware_id
        for device in target.devices
        if not device.stable_hardware_id or not device.stable_hardware_id.strip()
    ]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "GPU pool launch requires a stable PCI BDF for every member; "
                f"missing for: {', '.join(missing)}"
            ),
        )


def _build_pool_target(db: Session, pool: GpuPool, require_enabled: bool) -> PoolActivationTarget:
    pool_devices = ordered_pool_devices(db, pool.id, require_enabled=require_enabled)
    return PoolActivationTarget(pool_id=pool.id, pool_name=pool.name, vendor=pool.vendor, devices=pool_devices, split_mode=pool.split_mode)


def _estimate_model_size_mb(model: ModelConfig) -> int:
    model_dir = _model_directory_path(model)
    shard_paths = collect_shard_files(model_dir, model.file_name)
    if len(shard_paths) > 1 or parse_gguf_shard_name(model.file_name) is not None:
        total_bytes = 0
        for path in shard_paths:
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
        if total_bytes > 0:
            return int(total_bytes / (1024 * 1024))

    try:
        return int(os.path.getsize(model.file_path) / (1024 * 1024))
    except OSError:
        return 0


def _list_model_directory_files(model: ModelConfig) -> tuple[list[dict[str, int | str]], int]:
    model_dir = _model_directory_path(model)
    files: list[dict[str, int | str]] = []
    total_size = 0
    if not model_dir.exists():
        return files, total_size

    for entry in sorted(model_dir.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            size = 0
        files.append({"name": entry.name, "size": size})
        total_size += size
    return files, total_size


def _serialize_model(model: ModelConfig) -> dict:
    try:
        file_size = os.path.getsize(model.file_path)
    except OSError:
        file_size = None
    max_context_length = read_gguf_max_context_length(model.file_path)
    directory_files, directory_size = _list_model_directory_files(model)
    shard_validation = validate_shard_set(_model_directory_path(model), model.file_name)
    return {
        "id": model.id,
        "priority": model.priority,
        "file_name": model.file_name,
        "model_dir_name": model.model_dir_name,
        "file_path": model.file_path,
        "file_size": file_size,
        "alias": model.alias,
        "description": model.description,
        "system_prompt": model.system_prompt,
        "chat_template": model.chat_template,
        "max_context_length": max_context_length,
        "context_length": model.context_length,
        "gpu_layers": model.gpu_layers,
        "threads": model.threads,
        "batch_size": model.batch_size,
        "ubatch_size": model.ubatch_size,
        "temperature": model.temperature,
        "top_p": model.top_p,
        "top_k": model.top_k,
        "presence_penalty": model.presence_penalty,
        "repetition_penalty": model.repetition_penalty,
        "tool_calling_enabled": model.tool_calling_enabled,
        "discourage_thinking": model.discourage_thinking,
        "default_thinking_enabled": model.default_thinking_enabled,
        "thinking_capability": model.thinking_capability,
        "vision_enabled": model.vision_enabled,
        "web_search_enabled": model.web_search_enabled,
        "rag_enabled": model.rag_enabled,
        "flash_attention_enabled": model.flash_attention_enabled,
        "cache_type_k": model.cache_type_k,
        "cache_type_v": model.cache_type_v,
        "memory_mapping_enabled": model.memory_mapping_enabled,
        "mmproj_file_name": model.mmproj_file_name,
        "shard_count": shard_validation.total_shards,
        "shards_complete": shard_validation.is_complete,
        "missing_shards": shard_validation.missing_names,
        "directory_files": directory_files,
        "directory_size": directory_size,
        "assignment_mode": model.assignment_mode,
        "pinned_device_id": model.pinned_device_id,
        "pinned_pool_id": model.pinned_pool_id,
        "activated": model.activated,
    }


def _iter_model_files(models_dir: Path) -> list[tuple[str, str, Path]]:
    discovered: list[tuple[str, str, Path]] = []
    for child in sorted(models_dir.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        gguf_files = iter_model_gguf_files(child)
        if not gguf_files:
            continue
        primary = resolve_primary_shard(gguf_files)
        if primary is None:
            continue
        discovered.append((child.name, primary.name, primary))
    return discovered


def _detect_mmproj_file_name(model_dir: Path, model_file_name: str) -> str | None:
    normalized_model_name = model_file_name.lower()
    for entry in sorted(model_dir.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_file():
            continue
        if entry.name.lower() == normalized_model_name:
            continue
        if "mmproj" in entry.name.lower():
            return entry.name
    return None


def _build_unique_model_dir_name(db: Session, base_name: str) -> str:
    candidate = _sanitize_model_dir_name(base_name)
    suffix = 1
    while db.query(ModelConfig.id).filter(ModelConfig.model_dir_name == candidate).first():
        candidate = f"{_sanitize_model_dir_name(base_name)}-{suffix}"
        suffix += 1
    return candidate


def _sanitize_model_dir_name(base_name: str) -> str:
    sanitized = "".join(char if char not in '<>:"/\\|?*' else "-" for char in base_name).strip().strip(".")
    return sanitized or "model"


def _model_directory_path(model: ModelConfig) -> Path:
    return Path(get_settings().models_dir) / model.model_dir_name


def _remove_model_dir(model_dir: Path) -> None:
    if model_dir.exists():
        shutil.rmtree(model_dir)


def _is_allowed_asset_file(file_name: str) -> bool:
    lower_name = file_name.lower()
    suffix = Path(lower_name).suffix
    return suffix in ALLOWED_MODEL_ASSET_SUFFIXES or "mmproj" in lower_name


def _resolve_model_asset_path(model_dir: Path, file_name: str) -> Path:
    asset_name = Path(file_name).name
    if not asset_name or asset_name != file_name:
        raise HTTPException(status_code=400, detail="Invalid file name")
    try:
        destination = (model_dir / asset_name).resolve()
        model_dir_resolved = model_dir.resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Invalid file name") from exc
    if destination.parent != model_dir_resolved:
        raise HTTPException(status_code=400, detail="Invalid file name")
    return destination


def _is_protected_model_file(model: ModelConfig, file_name: str) -> bool:
    if file_name == model.file_name:
        return True
    model_dir = _model_directory_path(model)
    return any(path.name == file_name for path in collect_shard_files(model_dir, model.file_name))


def _ensure_model_vision_assets(model: ModelConfig) -> None:
    if model.vision_enabled and not model.mmproj_file_name:
        raise HTTPException(status_code=409, detail="Vision-enabled models require an mmproj file in the model directory")


def _ensure_model_shard_assets(model: ModelConfig) -> None:
    validation = validate_shard_set(_model_directory_path(model), model.file_name)
    if validation.total_shards and not validation.is_complete:
        missing = ", ".join(validation.missing_names)
        raise HTTPException(status_code=409, detail=f"Incomplete sharded model; missing: {missing}")


def _build_unique_alias(db: Session, base_alias: str) -> str:
    alias = base_alias.strip() or "model"
    base = alias
    suffix = 1
    while db.query(ModelConfig.id).filter(ModelConfig.alias == alias).first():
        alias = f"{base}-{suffix}"
        suffix += 1
    return alias


def _default_model_alias(model: ModelConfig) -> str:
    return Path(model.file_name).stem or "model"


def _next_model_priority(db: Session) -> int:
    last_model = db.query(ModelConfig).order_by(ModelConfig.priority.desc(), ModelConfig.id.desc()).first()
    return 0 if not last_model else last_model.priority + 1
