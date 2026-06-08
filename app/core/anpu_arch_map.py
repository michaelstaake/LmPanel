"""Map GGUF architectures to FLM converter families and template models."""

from __future__ import annotations

# GGUF general.architecture -> FLM_Q4NX_Converter -f value
GGUF_ARCH_TO_CONVERTER_FAMILY: dict[str, str] = {
    "llama": "llama",
    "llama2": "llama",
    "llama3": "llama",
    "llama4": "llama",
    "qwen2": "qwen2",
    "qwen2moe": "qwen2",
    "qwen3": "qwen3",
    "qwen3moe": "qwen3",
    "gemma": "gemma3",
    "gemma2": "gemma3",
    "gemma3": "gemma3",
    "phi2": "phi4",
    "phi3": "phi4",
    "phi4": "phi4",
    "gptoss": "gpt-oss",
    "lfm2": "lfm2",
}

# Converter family -> FLM template tag (must exist under FLM_TEMPLATE_MODELS)
CONVERTER_FAMILY_TO_FLM_TEMPLATE: dict[str, str] = {
    "llama": "llama3.2:3b",
    "qwen2": "qwen3:4b",
    "qwen3": "qwen3:4b",
    "qwen3.5-9B": "qwen3:4b",
    "gemma3": "llama3.2:3b",
    "phi4": "llama3.2:3b",
    "gpt-oss": "llama3.2:3b",
    "lfm2": "llama3.2:3b",
}

SUPPORTED_GGUF_ARCHITECTURES = frozenset(GGUF_ARCH_TO_CONVERTER_FAMILY.keys())


def normalize_gguf_architecture(architecture: str | None) -> str | None:
    if not architecture:
        return None
    return architecture.strip().lower()


def converter_family_for_architecture(architecture: str | None) -> str | None:
    normalized = normalize_gguf_architecture(architecture)
    if not normalized:
        return None
    return GGUF_ARCH_TO_CONVERTER_FAMILY.get(normalized)


def flm_template_for_converter_family(converter_family: str) -> str:
    return CONVERTER_FAMILY_TO_FLM_TEMPLATE.get(converter_family, "llama3.2:3b")


def is_anpu_compatible_architecture(architecture: str | None) -> bool:
    normalized = normalize_gguf_architecture(architecture)
    return normalized in SUPPORTED_GGUF_ARCHITECTURES
