"""GGUF to FLM Q4NX conversion and model registration for AMD NPU inference."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.anpu_arch_map import (
    converter_family_for_architecture,
    flm_template_for_converter_family,
)
from app.core.config import Settings, get_settings
from app.core.gguf import read_gguf_architecture

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1


@dataclass(frozen=True)
class AnpuManifest:
    flm_tag: str
    converter_family: str
    template_tag: str
    template_folder_name: str
    gguf_mtime: float
    converted_at: str
    files: list[str]

    def to_dict(self) -> dict:
        return {
            "version": MANIFEST_VERSION,
            "flm_tag": self.flm_tag,
            "converter_family": self.converter_family,
            "template_tag": self.template_tag,
            "template_folder_name": self.template_folder_name,
            "gguf_mtime": self.gguf_mtime,
            "converted_at": self.converted_at,
            "files": self.files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AnpuManifest:
        return cls(
            flm_tag=str(data["flm_tag"]),
            converter_family=str(data["converter_family"]),
            template_tag=str(data["template_tag"]),
            template_folder_name=str(data["template_folder_name"]),
            gguf_mtime=float(data["gguf_mtime"]),
            converted_at=str(data["converted_at"]),
            files=[str(item) for item in data.get("files", [])],
        )


def anpu_cache_dir(model_dir: Path) -> Path:
    return model_dir / ".anpu"


def manifest_path(model_dir: Path) -> Path:
    return anpu_cache_dir(model_dir) / "manifest.json"


def q4nx_output_dir(model_dir: Path) -> Path:
    return anpu_cache_dir(model_dir) / "q4nx"


def flm_model_dir(model_dir: Path) -> Path:
    return anpu_cache_dir(model_dir) / "flm-model"


def flm_tag_for_model(model_id: int) -> str:
    return f"lmpanel:{model_id}"


def custom_model_list_path(settings: Settings) -> Path:
    return Path(settings.flm_model_path) / "model_list.custom.json"


def _gguf_mtime(gguf_path: Path) -> float:
    return gguf_path.stat().st_mtime


def load_manifest(model_dir: Path) -> AnpuManifest | None:
    path = manifest_path(model_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AnpuManifest.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def manifest_is_current(model_dir: Path, gguf_path: Path) -> bool:
    manifest = load_manifest(model_dir)
    if manifest is None:
        return False
    try:
        return manifest.gguf_mtime == _gguf_mtime(gguf_path)
    except OSError:
        return False


def _template_folder_name(settings: Settings, template_tag: str) -> str | None:
    template_root = Path(settings.flm_template_models)
    if not template_root.exists():
        return None

    # FLM stores models in folders named after the model display name; scan for a match.
    tag_key = template_tag.replace(":", "-").lower()
    for entry in template_root.iterdir():
        if not entry.is_dir():
            continue
        normalized = entry.name.lower().replace(" ", "-")
        if tag_key in normalized or normalized in tag_key:
            return entry.name
    folders = sorted(path for path in template_root.iterdir() if path.is_dir())
    return folders[0].name if folders else None


def _flm_share_dir() -> Path:
    candidates = [
        Path("/opt/fastflowlm/share/flm"),
        Path("/usr/share/flm"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _converter_python(settings: Settings) -> Path:
    venv_python = Path(settings.flm_converter_root) / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return Path("python3")


def _run_converter(
    settings: Settings,
    gguf_path: Path,
    output_dir: Path,
    converter_family: str,
    log_path: Path | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(_converter_python(settings)),
        str(Path(settings.flm_converter_root) / "convert.py"),
        "-i",
        str(gguf_path),
        "-o",
        str(output_dir),
        "-f",
        converter_family,
    ]
    logger.info("Running FLM Q4NX converter: %s", " ".join(command))
    if log_path is not None:
        with log_path.open("ab") as log_handle:
            subprocess.run(command, check=True, stdout=log_handle, stderr=log_handle, env=os.environ.copy())
    else:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=os.environ.copy())


def _copy_template_model(
    settings: Settings,
    template_folder_name: str,
    destination: Path,
) -> None:
    source = Path(settings.flm_template_models) / template_folder_name
    if not source.exists():
        raise RuntimeError(f"FLM template model folder not found: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _replace_q4nx_weights(q4nx_dir: Path, flm_dir: Path) -> list[str]:
    copied: list[str] = []
    for item in q4nx_dir.iterdir():
        if not item.is_file() or not item.name.endswith(".q4nx"):
            continue
        target = flm_dir / item.name
        shutil.copy2(item, target)
        copied.append(item.name)
    if not copied:
        model_q4nx = q4nx_dir / "model.q4nx"
        if model_q4nx.exists():
            shutil.copy2(model_q4nx, flm_dir / "model.q4nx")
            copied.append("model.q4nx")
    if not copied:
        raise RuntimeError("FLM converter produced no .q4nx files")
    return copied


def _register_custom_model(
    settings: Settings,
    *,
    flm_tag: str,
    model_folder_name: str,
    template_tag: str,
    converter_family: str,
    files: list[str],
    default_context_length: int,
) -> None:
    flm_models_root = Path(settings.flm_model_path)
    flm_models_root.mkdir(parents=True, exist_ok=True)

    deployed_dir = flm_models_root / model_folder_name
    if not deployed_dir.exists():
        raise RuntimeError(f"Deployed FLM model directory missing: {deployed_dir}")

    custom_path = custom_model_list_path(settings)
    payload: dict = {}
    if custom_path.exists():
        try:
            payload = json.loads(custom_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

    models = payload.setdefault("models", {})
    family_key, _, size_key = flm_tag.partition(":")
    if not size_key:
        family_key = flm_tag
        size_key = "custom"

    entry = {
        "name": model_folder_name,
        "url": "local://lmpanel",
        "file_url": "local://lmpanel",
        "size": 0,
        "files": sorted({*files, "config.json", "tokenizer.json", "tokenizer_config.json"}),
        "default_context_length": default_context_length,
        "details": {
            "format": "NPU2",
            "family": converter_family,
            "parameter_size": size_key,
            "quantization_level": "Q4NX",
        },
        "footprint": 0,
    }

    family = models.setdefault(family_key, {})
    family[size_key] = entry
    custom_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    share_dir = _flm_share_dir()
    template_name = _template_folder_name(settings, template_tag)
    xclbin_source = share_dir / "xclbins" / template_name if template_name else Path()
    if template_name and xclbin_source.exists():
        xclbin_target = share_dir / "xclbins" / model_folder_name
        if xclbin_target.exists():
            shutil.rmtree(xclbin_target)
        shutil.copytree(xclbin_source, xclbin_target)


def ensure_anpu_artifacts(
    *,
    model_id: int,
    gguf_path: str,
    model_dir_name: str,
    architecture: str | None,
    context_length: int,
    mmproj_path: str | None = None,
    log_path: Path | None = None,
    settings: Settings | None = None,
) -> str:
    """Convert GGUF to Q4NX if needed and register the FLM model. Returns flm_tag."""
    settings = settings or get_settings()
    gguf = Path(gguf_path)
    if not gguf.exists():
        raise RuntimeError(f"GGUF model file not found: {gguf}")

    model_dir = Path(settings.models_dir) / model_dir_name
    converter_family = converter_family_for_architecture(architecture)
    if not converter_family:
        raise RuntimeError(f"GGUF architecture is not supported on AMD NPU: {architecture or 'unknown'}")

    flm_tag = flm_tag_for_model(model_id)
    if manifest_is_current(model_dir, gguf):
        return flm_tag

    template_tag = flm_template_for_converter_family(converter_family)
    template_folder_name = _template_folder_name(settings, template_tag)
    if not template_folder_name:
        raise RuntimeError(
            f"No FLM template model found for {template_tag}. "
            "Rebuild inference-anpu with template models or run flm pull in the container."
        )

    q4nx_dir = q4nx_output_dir(model_dir)
    flm_dir = flm_model_dir(model_dir)
    _run_converter(settings, gguf, q4nx_dir, converter_family, log_path=log_path)

    if mmproj_path:
        mmproj = Path(mmproj_path)
        if mmproj.exists():
            vision_dir = anpu_cache_dir(model_dir) / "q4nx-vision"
            _run_converter(settings, mmproj, vision_dir, converter_family, log_path=log_path)
            for item in vision_dir.glob("*.q4nx"):
                shutil.copy2(item, q4nx_dir / item.name)

    _copy_template_model(settings, template_folder_name, flm_dir)
    copied_files = _replace_q4nx_weights(q4nx_dir, flm_dir)

    deployed_name = f"LmPanel-{model_id}"
    deployed_path = Path(settings.flm_model_path) / deployed_name
    if deployed_path.exists():
        shutil.rmtree(deployed_path)
    shutil.copytree(flm_dir, deployed_path)

    _register_custom_model(
        settings,
        flm_tag=flm_tag,
        model_folder_name=deployed_name,
        template_tag=template_tag,
        converter_family=converter_family,
        files=copied_files,
        default_context_length=context_length,
    )

    manifest = AnpuManifest(
        flm_tag=flm_tag,
        converter_family=converter_family,
        template_tag=template_tag,
        template_folder_name=template_folder_name,
        gguf_mtime=_gguf_mtime(gguf),
        converted_at=datetime.now(timezone.utc).isoformat(),
        files=copied_files,
    )
    anpu_cache_dir(model_dir).mkdir(parents=True, exist_ok=True)
    manifest_path(model_dir).write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return flm_tag


def refresh_anpu_metadata(model) -> None:
    """Update model row fields from GGUF metadata."""
    architecture = read_gguf_architecture(model.file_path)
    model.anpu_architecture = architecture
    model.anpu_compatible = converter_family_for_architecture(architecture) is not None
    if model.anpu_compatible and model.id:
        model.anpu_flm_tag = flm_tag_for_model(model.id)
    else:
        model.anpu_flm_tag = None
        model.anpu_conversion_status = "none"
        model.anpu_conversion_error = ""
