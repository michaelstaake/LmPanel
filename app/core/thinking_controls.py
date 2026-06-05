"""Thinking-mode controls for hybrid reasoning models (Qwen, Gemma, etc.)."""

from __future__ import annotations

import json
import re
from typing import Any

from app.models.model_config import ModelConfig

THINKING_CAPABILITY_AUTO = "auto"
THINKING_CAPABILITY_HYBRID = "hybrid"
THINKING_CAPABILITY_ALWAYS = "always"
THINKING_CAPABILITY_NONE = "none"

THINKING_CAPABILITIES = {
    THINKING_CAPABILITY_AUTO,
    THINKING_CAPABILITY_HYBRID,
    THINKING_CAPABILITY_ALWAYS,
    THINKING_CAPABILITY_NONE,
}

# Legacy system-prompt lines injected by older LmPanel versions (strip on reuse).
THINKING_DISABLED_PROMPT = (
    "Thinking mode: off. Do not include reasoning, chain-of-thought, or thought process. "
    "Reply with only the final answer."
)
THINKING_ENABLED_PROMPT = (
    "Thinking mode: on. Include your reasoning before the final answer when the model supports it."
)
KNOWN_THINKING_CONTROL_LINES = {
    THINKING_DISABLED_PROMPT,
    THINKING_ENABLED_PROMPT,
    "/think",
    "/no_think",
}

QWEN_THINK_SUFFIXES = ("/no_think", "/think")
REASONING_DELTA_KEYS = ("reasoning_content", "reasoning", "thought")

_HYBRID_PATTERNS = (
    re.compile(r"qwen[-_]?\d", re.I),
    re.compile(r"qwen3", re.I),
    re.compile(r"gemma[-_]?\d", re.I),
    re.compile(r"gemma3", re.I),
    re.compile(r"granite", re.I),
    re.compile(r"\blfm", re.I),
    re.compile(r"liquid", re.I),
)

# Thinking markup that llama.cpp may leave in message.content when reasoning is disabled
# or when the template does not honor enable_thinking (e.g. LFM2.5).
_THINKING_BLOCK_RE = re.compile(
    r"<\|?(?:think|thinking|redacted_thinking)\|?>.*?</\|?(?:think|thinking|redacted_thinking)\|?>",
    re.DOTALL | re.IGNORECASE,
)
_EMPTY_THINKING_PAIR_RE = re.compile(
    r"<\|?(?:think|thinking|redacted_thinking)\|?>\s*</\|?(?:think|thinking|redacted_thinking)\|?>\n?",
    re.IGNORECASE,
)

_ALWAYS_PATTERNS = (
    re.compile(r"\bqwq\b", re.I),
    re.compile(r"deepseek[-_]?r1", re.I),
    re.compile(r"\br1[-_]", re.I),
    re.compile(r"-thinking", re.I),
    re.compile(r"thinking[-_]", re.I),
    re.compile(r"\breasoning\b", re.I),
)


def _model_identity(model: ModelConfig) -> str:
    return " ".join(
        part.lower()
        for part in (model.alias, model.file_name, model.model_dir_name)
        if part
    )


def _matches_patterns(identity: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(identity) for pattern in patterns)


def detect_thinking_capability(model: ModelConfig) -> str:
    override = getattr(model, "thinking_capability", THINKING_CAPABILITY_AUTO) or THINKING_CAPABILITY_AUTO
    if override != THINKING_CAPABILITY_AUTO:
        return override

    identity = _model_identity(model)
    if _matches_patterns(identity, _ALWAYS_PATTERNS):
        return THINKING_CAPABILITY_ALWAYS
    if _matches_patterns(identity, _HYBRID_PATTERNS):
        return THINKING_CAPABILITY_HYBRID
    return THINKING_CAPABILITY_NONE


def is_thinking_controllable(model: ModelConfig) -> bool:
    if model.discourage_thinking:
        return False
    return detect_thinking_capability(model) == THINKING_CAPABILITY_HYBRID


def resolve_thinking_enabled(model: ModelConfig, payload_enable_thinking: bool | None) -> bool:
    if model.discourage_thinking:
        return False

    capability = detect_thinking_capability(model)
    if capability == THINKING_CAPABILITY_ALWAYS:
        return True
    if capability == THINKING_CAPABILITY_NONE:
        return False
    if payload_enable_thinking is not None:
        return payload_enable_thinking
    return bool(getattr(model, "default_thinking_enabled", True))


def get_thinking_family(model: ModelConfig) -> str:
    identity = _model_identity(model)
    if "qwen" in identity:
        return "qwen"
    if "gemma" in identity:
        return "gemma"
    if "granite" in identity:
        return "granite"
    if "lfm" in identity or "liquid" in identity:
        return "lfm"
    return "generic"


def strip_thinking_markup_from_text(text: str) -> str:
    if not text:
        return text

    cleaned = _EMPTY_THINKING_PAIR_RE.sub("", text)
    return _THINKING_BLOCK_RE.sub("", cleaned)


def strip_legacy_thinking_control_lines(text: str) -> str:
    cleaned_lines = [
        line
        for line in text.splitlines()
        if line.strip() not in KNOWN_THINKING_CONTROL_LINES
    ]
    return "\n".join(cleaned_lines).strip()


def _strip_qwen_think_suffix(text: str) -> str:
    stripped = text.rstrip()
    for suffix in QWEN_THINK_SUFFIXES:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)].rstrip()
        elif stripped.endswith(f" {suffix}"):
            stripped = stripped[: -(len(suffix) + 1)].rstrip()
    return stripped


def _append_suffix_to_content(content: str | list[dict[str, Any]], suffix: str) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        base = _strip_qwen_think_suffix(content)
        return f"{base}{suffix}" if base else suffix.strip()

    updated: list[dict[str, Any]] = list(content)
    for index in range(len(updated) - 1, -1, -1):
        part = updated[index]
        if isinstance(part, dict) and part.get("type") == "text":
            base = _strip_qwen_think_suffix(part.get("text") or "")
            updated[index] = {**part, "text": f"{base}{suffix}" if base else suffix.strip()}
            return updated

    return [*updated, {"type": "text", "text": suffix.strip()}]


def _strip_legacy_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "system":
            cleaned.append(message)
            continue

        content = message.get("content")
        if isinstance(content, str):
            stripped = strip_legacy_thinking_control_lines(content)
            if not stripped:
                continue
            cleaned.append({**message, "content": stripped})
            continue

        if isinstance(content, list):
            new_parts: list[dict[str, Any]] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    stripped = strip_legacy_thinking_control_lines(part.get("text") or "")
                    if stripped:
                        new_parts.append({**part, "text": stripped})
                else:
                    new_parts.append(part)
            if not new_parts:
                continue
            cleaned.append({**message, "content": new_parts})
            continue

        cleaned.append(message)
    return cleaned


def _apply_qwen_user_suffix(messages: list[dict[str, Any]], enabled: bool) -> list[dict[str, Any]]:
    suffix = " /think" if enabled else " /no_think"
    last_user_index: int | None = None
    for index, message in enumerate(messages):
        if message.get("role") == "user":
            last_user_index = index

    if last_user_index is None:
        return messages

    message = messages[last_user_index]
    content = message.get("content")
    if content is None:
        return messages

    updated = list(messages)
    updated[last_user_index] = {**message, "content": _append_suffix_to_content(content, suffix)}
    return updated


def apply_thinking_to_request(request_payload: dict[str, Any], model: ModelConfig, enabled: bool) -> dict[str, Any]:
    messages = list(request_payload.get("messages") or [])
    messages = _strip_legacy_from_messages(messages)

    if get_thinking_family(model) == "qwen" and detect_thinking_capability(model) == THINKING_CAPABILITY_HYBRID:
        messages = _apply_qwen_user_suffix(messages, enabled)

    request_payload = dict(request_payload)
    request_payload["messages"] = messages
    request_payload["enable_thinking"] = enabled

    existing_kwargs = request_payload.get("chat_template_kwargs")
    merged_kwargs: dict[str, Any] = dict(existing_kwargs) if isinstance(existing_kwargs, dict) else {}
    merged_kwargs["enable_thinking"] = enabled
    request_payload["chat_template_kwargs"] = merged_kwargs

    if enabled:
        request_payload.pop("thinking_budget_tokens", None)
    else:
        request_payload["thinking_budget_tokens"] = 0

    return request_payload


def model_thinking_metadata(model: ModelConfig) -> dict[str, Any]:
    capability = detect_thinking_capability(model)
    return {
        "thinking_capability": capability,
        "thinking_controllable": is_thinking_controllable(model),
        "default_thinking_enabled": bool(getattr(model, "default_thinking_enabled", True)),
        "discourage_thinking": model.discourage_thinking,
    }


def filter_thinking_from_sse_chunk(chunk: bytes | str, enabled: bool) -> bytes | str:
    if enabled:
        return chunk

    is_bytes = isinstance(chunk, bytes)
    text = chunk.decode("utf-8", errors="replace") if is_bytes else chunk
    if not text:
        return chunk

    events = text.replace("\r\n", "\n").split("\n\n")
    output_events: list[str] = []
    changed = False

    for event in events:
        if not event.strip():
            output_events.append(event)
            continue

        new_lines: list[str] = []
        skip_event = False
        for line in event.split("\n"):
            if not line.startswith("data:"):
                new_lines.append(line)
                continue

            payload_str = line[5:].strip()
            if not payload_str or payload_str == "[DONE]":
                new_lines.append(line)
                continue

            try:
                payload = json.loads(payload_str)
            except (json.JSONDecodeError, ValueError):
                new_lines.append(line)
                continue

            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                new_lines.append(line)
                continue

            choice = choices[0]
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                new_lines.append(line)
                continue

            filtered_delta = {key: value for key, value in delta.items() if key not in REASONING_DELTA_KEYS}
            content = filtered_delta.get("content")
            if isinstance(content, str):
                stripped_content = strip_thinking_markup_from_text(content)
                if stripped_content != content:
                    changed = True
                    if stripped_content:
                        filtered_delta = {**filtered_delta, "content": stripped_content}
                    elif content.isspace():
                        filtered_delta = {**filtered_delta, "content": content}
                    else:
                        filtered_delta = {key: value for key, value in filtered_delta.items() if key != "content"}

            if filtered_delta == delta:
                new_lines.append(line)
                continue

            changed = True
            if not filtered_delta:
                skip_event = True
                break

            updated_choice = {**choice, "delta": filtered_delta}
            updated_payload = {**payload, "choices": [updated_choice, *choices[1:]]}
            new_lines.append("data: " + json.dumps(updated_payload, ensure_ascii=False))

        if skip_event:
            continue
        if new_lines:
            output_events.append("\n".join(new_lines))

    if not changed:
        return chunk

    result = "\n\n".join(output_events)
    return result.encode("utf-8") if is_bytes else result
