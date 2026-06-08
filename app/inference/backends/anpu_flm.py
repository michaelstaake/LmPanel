from __future__ import annotations

import logging
import os
from pathlib import Path

from app.core.anpu_conversion import ensure_anpu_artifacts
from app.core.config import Settings
from app.inference.backends.base import LaunchPlan
from app.inference.types import ActivateModelRequest

logger = logging.getLogger(__name__)


class AnpuFlmBackend:
    def build_launch(self, payload: ActivateModelRequest, port: int, settings: Settings) -> LaunchPlan:
        model_dir_name = payload.model_dir_name or Path(payload.file_path).parent.name
        architecture = payload.anpu_architecture
        log_path = Path(settings.logs_dir) / f"anpu-{payload.model_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        flm_tag = ensure_anpu_artifacts(
            model_id=payload.model_id,
            gguf_path=payload.file_path,
            model_dir_name=model_dir_name,
            architecture=architecture or payload.anpu_architecture,
            context_length=payload.context_length,
            mmproj_path=payload.mmproj_path,
            log_path=log_path,
            settings=settings,
        )

        flm_bin = settings.flm_bin
        if not Path(flm_bin).exists():
            flm_bin = "flm"

        command = [
            flm_bin,
            "serve",
            flm_tag,
            "--ctx-len",
            str(payload.context_length),
            "--port",
            str(port),
            "--quiet",
        ]

        env = os.environ.copy()
        env["FLM_MODEL_PATH"] = settings.flm_model_path
        if settings.flm_template_models:
            env.setdefault("FLM_TEMPLATE_MODELS", settings.flm_template_models)

        health_url = f"http://{settings.llama_host}:{port}/v1/models"
        return LaunchPlan(
            command=command,
            env=env,
            health_url=health_url,
            log_prefix="anpu",
            post_launch_validate=False,
        )
