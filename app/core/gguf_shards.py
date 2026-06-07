from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GGUF_SHARD_PATTERN = re.compile(r"^(.+)-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)


@dataclass(frozen=True)
class ShardInfo:
    prefix: str
    index: int
    total: int
    file_name: str


@dataclass(frozen=True)
class ShardValidation:
    total_shards: int | None
    present_shards: int
    missing_names: list[str]
    is_complete: bool


def is_mmproj_file_name(file_name: str) -> bool:
    return "mmproj" in file_name.lower()


def is_model_gguf_file_name(file_name: str) -> bool:
    return Path(file_name).suffix.lower() == ".gguf" and not is_mmproj_file_name(file_name)


def parse_gguf_shard_name(file_name: str) -> ShardInfo | None:
    match = GGUF_SHARD_PATTERN.match(file_name)
    if not match:
        return None
    prefix, index_text, total_text = match.groups()
    index = int(index_text)
    total = int(total_text)
    if index < 1 or total < 1 or index > total:
        return None
    return ShardInfo(prefix=prefix, index=index, total=total, file_name=file_name)


def strip_shard_suffix(name: str) -> str:
    stem = Path(name).stem
    shard = parse_gguf_shard_name(f"{stem}.gguf")
    if shard is None:
        return stem
    return shard.prefix


def build_shard_file_name(prefix: str, index: int, total: int) -> str:
    return f"{prefix}-{index:05d}-of-{total:05d}.gguf"


def iter_model_gguf_files(model_dir: Path) -> list[Path]:
    if not model_dir.exists():
        return []
    return sorted(
        (
            entry
            for entry in model_dir.iterdir()
            if entry.is_file() and is_model_gguf_file_name(entry.name)
        ),
        key=lambda item: item.name.lower(),
    )


def resolve_primary_shard(files: list[Path]) -> Path | None:
    if not files:
        return None

    shard_files = [path for path in files if parse_gguf_shard_name(path.name) is not None]
    if not shard_files:
        return sorted(files, key=lambda item: item.name.lower())[0]

    shard_infos = [parse_gguf_shard_name(path.name) for path in shard_files]
    if any(info is None for info in shard_infos):
        return None

    totals = {info.total for info in shard_infos if info is not None}
    prefixes = {info.prefix.lower() for info in shard_infos if info is not None}
    if len(totals) != 1 or len(prefixes) != 1:
        return None

    primary = next((path for path in shard_files if parse_gguf_shard_name(path.name) and parse_gguf_shard_name(path.name).index == 1), None)
    return primary


def collect_shard_files(model_dir: Path, primary_name: str) -> list[Path]:
    shard = parse_gguf_shard_name(primary_name)
    if shard is None:
        primary_path = model_dir / primary_name
        return [primary_path] if primary_path.is_file() else []

    files: list[Path] = []
    for index in range(1, shard.total + 1):
        candidate = model_dir / build_shard_file_name(shard.prefix, index, shard.total)
        if candidate.is_file():
            files.append(candidate)
    return files


def validate_shard_set(model_dir: Path, primary_name: str) -> ShardValidation:
    shard = parse_gguf_shard_name(primary_name)
    if shard is None:
        primary_path = model_dir / primary_name
        return ShardValidation(
            total_shards=None,
            present_shards=1 if primary_path.is_file() else 0,
            missing_names=[] if primary_path.is_file() else [primary_name],
            is_complete=primary_path.is_file(),
        )

    present_names: list[str] = []
    missing_names: list[str] = []
    for index in range(1, shard.total + 1):
        file_name = build_shard_file_name(shard.prefix, index, shard.total)
        if (model_dir / file_name).is_file():
            present_names.append(file_name)
        else:
            missing_names.append(file_name)

    return ShardValidation(
        total_shards=shard.total,
        present_shards=len(present_names),
        missing_names=missing_names,
        is_complete=not missing_names,
    )


def validate_upload_shard_set(file_names: list[str]) -> tuple[str, list[str]]:
    if not file_names:
        raise ValueError("No files were provided")

    normalized = [Path(name).name for name in file_names]
    if len(normalized) == 1:
        file_name = normalized[0]
        if not is_model_gguf_file_name(file_name):
            raise ValueError("Only .gguf model files are supported")
        return file_name, normalized

    shard_infos = [parse_gguf_shard_name(name) for name in normalized]
    if any(info is None for info in shard_infos):
        raise ValueError("Multiple uploads must all be sharded GGUF files with matching names")

    prefixes = {info.prefix.lower() for info in shard_infos if info is not None}
    totals = {info.total for info in shard_infos if info is not None}
    if len(prefixes) != 1 or len(totals) != 1:
        raise ValueError("All shard files must share the same model prefix and shard count")

    total = totals.pop()
    if len(normalized) != total:
        raise ValueError(f"Expected {total} shard files but received {len(normalized)}")

    indices = sorted(info.index for info in shard_infos if info is not None)
    expected_indices = list(range(1, total + 1))
    if indices != expected_indices:
        raise ValueError("Shard upload must include every shard from 00001 through the final part")

    reference = next(info for info in shard_infos if info is not None)
    primary_name = build_shard_file_name(reference.prefix, 1, total)
    for name in normalized:
        parsed = parse_gguf_shard_name(name)
        if parsed and parsed.index == 1:
            primary_name = name
            break
    return primary_name, normalized
