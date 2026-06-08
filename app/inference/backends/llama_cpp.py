from __future__ import annotations

import logging
import os
from pathlib import Path

from app.core.config import Settings
from app.inference.backends.base import LaunchPlan
from app.inference.llama_launch import (
    apply_rocm_runtime_env,
    effective_pool_split_mode,
    format_gpu_layers_for_cli,
    llama_offload_extra_args,
    resolve_flash_attn_for_launch,
    rocm_pool_stability_args,
)
from app.inference.types import ActivateModelRequest

logger = logging.getLogger(__name__)


class LlamaCppBackend:
    def build_launch(self, payload: ActivateModelRequest, port: int, settings: Settings) -> LaunchPlan:
        flash_attn_enabled = resolve_flash_attn_for_launch(
            payload.vendor,
            payload.flash_attention_enabled,
            payload.split_mode,
        )
        if payload.vendor == "rocm_pool" and payload.flash_attention_enabled and not flash_attn_enabled:
            logger.warning("ROCm pool forcing --flash-attn off for stability")

        command = [
            self._resolve_llama_server_path(settings),
            "-m",
            payload.file_path,
            "--host",
            settings.llama_host,
            "--port",
            str(port),
            "-c",
            str(payload.context_length),
            "--threads",
            str(payload.threads),
            "--n-gpu-layers",
            format_gpu_layers_for_cli(payload.gpu_layers),
            "--flash-attn",
            "on" if flash_attn_enabled else "off",
        ]
        command.extend(
            llama_offload_extra_args(
                payload.vendor,
                payload.gpu_layers,
                fit_to_vram=settings.llama_fit_to_vram,
            )
        )
        if not payload.memory_mapping_enabled:
            command.append("--no-mmap")
        if payload.mmproj_path:
            command.extend(["--mmproj", payload.mmproj_path])
        command.extend(
            self._build_vendor_args(
                payload.vendor,
                payload.vram_ratios,
                payload.split_mode,
                flash_attn_enabled=flash_attn_enabled,
                settings=settings,
            )
        )
        command.append("--jinja")
        if payload.discourage_thinking:
            command.extend(["--reasoning", "off", "--reasoning-budget", "0"])

        env = self._build_env(payload.vendor, payload.hardware_id, payload.threads, payload.hardware_ids, settings)
        health_url = f"http://{settings.llama_host}:{port}/health"
        return LaunchPlan(
            command=command,
            env=env,
            health_url=health_url,
            log_prefix="llama",
            post_launch_validate=True,
        )

    @staticmethod
    def _resolve_llama_server_path(settings: Settings) -> str:
        configured_path = Path(settings.llama_server_path)
        candidates = [configured_path]
        if os.name == "nt" and configured_path.suffix.lower() != ".exe":
            candidates.insert(0, configured_path.with_suffix(".exe"))

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return str(configured_path)

    @staticmethod
    def _build_env(
        vendor: str,
        hardware_id: str,
        threads: int,
        hardware_ids: list[str] | None,
        settings: Settings,
    ) -> dict[str, str]:
        env = os.environ.copy()
        if vendor == "nvidia_pool":
            ids = hardware_ids if hardware_ids else [hardware_id]
            indices = [hid.split(":")[-1] for hid in ids]
            env["CUDA_VISIBLE_DEVICES"] = ",".join(indices)
        elif vendor == "vulkan_pool":
            ids = hardware_ids if hardware_ids else [hardware_id]
            indices = [hid.split(":")[-1] for hid in ids]
            env["GGML_VK_VISIBLE_DEVICES"] = ",".join(indices)
        elif vendor == "rocm_pool":
            ids = hardware_ids if hardware_ids else [hardware_id]
            indices = [hid.split(":")[-1] for hid in ids]
            env["HIP_VISIBLE_DEVICES"] = ",".join(indices)
            apply_rocm_runtime_env(env)
        elif vendor == "rocm":
            env["HIP_VISIBLE_DEVICES"] = hardware_id.split(":")[-1]
            apply_rocm_runtime_env(env)
        elif vendor == "nvidia":
            env["CUDA_VISIBLE_DEVICES"] = hardware_id.split(":")[-1]
        elif vendor == "vulkan":
            env["GGML_VK_VISIBLE_DEVICES"] = hardware_id.split(":")[-1]
        elif vendor == "cpu":
            env["OMP_NUM_THREADS"] = str(max(1, threads))
        elif vendor == "anpu":
            env["FLM_MODEL_PATH"] = settings.flm_model_path
        else:
            raise RuntimeError(f"Unknown device vendor: {vendor}")
        return env

    @staticmethod
    def _build_vendor_args(
        vendor: str,
        vram_ratios: list[int] | None,
        split_mode: str,
        *,
        flash_attn_enabled: bool,
        settings: Settings,
    ) -> list[str]:
        if not vendor.endswith("_pool"):
            return []

        args: list[str] = []
        effective_split_mode = split_mode
        if vendor == "rocm_pool":
            args.extend(rocm_pool_stability_args())
            effective_split_mode = effective_pool_split_mode(
                vendor,
                split_mode,
                flash_attn_enabled=flash_attn_enabled,
            )

        if effective_split_mode == "tensor" and vram_ratios and len(vram_ratios) >= 2:
            args.extend(["--tensor-split", ",".join(str(r) for r in vram_ratios)])
        args.extend(["--split-mode", effective_split_mode])
        return args
