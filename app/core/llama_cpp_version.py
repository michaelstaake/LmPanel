from __future__ import annotations

from functools import lru_cache
from pathlib import Path

LLAMA_CPP_ROOT = Path("/opt/llama.cpp")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def format_llama_cpp_release(tag: str | None, commit: str | None) -> str | None:
    tag = (tag or "").strip()
    commit = (commit or "").strip()
    short = commit[:7] if commit else ""
    if tag and short and short.lower() not in tag.lower():
        return f"{tag} ({short})"
    return tag or short or None


def read_llama_cpp_version(root: Path | None = None) -> dict[str, str | None]:
    llama_root = root or LLAMA_CPP_ROOT
    tag = _read_text(llama_root / "BUILD_TAG")
    commit = _read_text(llama_root / "BUILD_COMMIT")
    return {
        "llama_cpp_tag": tag or None,
        "llama_cpp_commit": commit or None,
        "llama_cpp_release": format_llama_cpp_release(tag, commit),
    }


@lru_cache(maxsize=1)
def get_llama_cpp_version() -> dict[str, str | None]:
    return read_llama_cpp_version()
