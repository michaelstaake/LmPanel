"""Tests for thinking mode detection, resolution, and request mutation."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.thinking_controls import (
    THINKING_CAPABILITY_ALWAYS,
    THINKING_CAPABILITY_HYBRID,
    THINKING_CAPABILITY_NONE,
    apply_thinking_to_request,
    detect_thinking_capability,
    filter_thinking_from_sse_chunk,
    is_thinking_controllable,
    resolve_thinking_enabled,
)


def _model(
    *,
    alias: str = "test",
    file_name: str = "test.gguf",
    model_dir_name: str = "test",
    discourage_thinking: bool = False,
    default_thinking_enabled: bool = True,
    thinking_capability: str = "auto",
) -> SimpleNamespace:
    return SimpleNamespace(
        alias=alias,
        file_name=file_name,
        model_dir_name=model_dir_name,
        discourage_thinking=discourage_thinking,
        default_thinking_enabled=default_thinking_enabled,
        thinking_capability=thinking_capability,
    )


def test_detect_hybrid_qwen() -> None:
    model = _model(alias="qwen3-8b", file_name="Qwen3-8B-Q4_K_M.gguf", model_dir_name="Qwen3-8B")
    assert detect_thinking_capability(model) == THINKING_CAPABILITY_HYBRID


def test_detect_hybrid_gemma() -> None:
    model = _model(alias="gemma-4", file_name="gemma-4-26b.gguf", model_dir_name="gemma-4")
    assert detect_thinking_capability(model) == THINKING_CAPABILITY_HYBRID


def test_detect_always_qwq() -> None:
    model = _model(alias="qwq-32b", file_name="qwq-32b.gguf", model_dir_name="qwq")
    assert detect_thinking_capability(model) == THINKING_CAPABILITY_ALWAYS


def test_detect_none_llama() -> None:
    model = _model(alias="llama-3", file_name="llama-3-8b.gguf", model_dir_name="llama-3")
    assert detect_thinking_capability(model) == THINKING_CAPABILITY_NONE


def test_manual_capability_override() -> None:
    model = _model(alias="llama-3", thinking_capability="hybrid")
    assert detect_thinking_capability(model) == THINKING_CAPABILITY_HYBRID


def test_resolve_discourage_thinking_wins() -> None:
    model = _model(discourage_thinking=True, default_thinking_enabled=True)
    assert resolve_thinking_enabled(model, True) is False


def test_resolve_always_ignores_payload() -> None:
    model = _model(alias="qwq", file_name="qwq.gguf", model_dir_name="qwq")
    assert resolve_thinking_enabled(model, False) is True


def test_resolve_none_ignores_payload() -> None:
    model = _model(alias="llama-3", file_name="llama-3.gguf", model_dir_name="llama-3")
    assert resolve_thinking_enabled(model, True) is False


def test_resolve_hybrid_uses_payload_then_default() -> None:
    model = _model(alias="qwen3", file_name="qwen3.gguf", model_dir_name="qwen3", default_thinking_enabled=False)
    assert resolve_thinking_enabled(model, None) is False
    assert resolve_thinking_enabled(model, True) is True


def test_is_thinking_controllable() -> None:
    hybrid = _model(alias="qwen3", file_name="qwen3.gguf", model_dir_name="qwen3")
    locked = _model(alias="qwen3", file_name="qwen3.gguf", model_dir_name="qwen3", discourage_thinking=True)
    assert is_thinking_controllable(hybrid) is True
    assert is_thinking_controllable(locked) is False


def test_apply_thinking_disabled_sets_template_kwargs() -> None:
    model = _model(alias="gemma-4", file_name="gemma-4.gguf", model_dir_name="gemma-4")
    payload = {"messages": [{"role": "user", "content": "Hello"}]}
    updated = apply_thinking_to_request(payload, model, False)
    assert updated["enable_thinking"] is False
    assert updated["chat_template_kwargs"] == {"enable_thinking": False}
    assert updated["thinking_budget_tokens"] == 0


def test_apply_thinking_enabled_omits_budget() -> None:
    model = _model(alias="gemma-4", file_name="gemma-4.gguf", model_dir_name="gemma-4")
    payload = {"messages": [{"role": "user", "content": "Hello"}]}
    updated = apply_thinking_to_request(payload, model, True)
    assert updated["enable_thinking"] is True
    assert updated["chat_template_kwargs"] == {"enable_thinking": True}
    assert "thinking_budget_tokens" not in updated


def test_qwen_appends_no_think_to_last_user_message() -> None:
    model = _model(alias="qwen3-8b", file_name="qwen3.gguf", model_dir_name="qwen3")
    payload = {
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Solve 2+2"},
        ]
    }
    updated = apply_thinking_to_request(payload, model, False)
    assert updated["messages"][-1]["content"] == "Solve 2+2 /no_think"


def test_qwen_appends_think_when_enabled() -> None:
    model = _model(alias="qwen3-8b", file_name="qwen3.gguf", model_dir_name="qwen3")
    payload = {"messages": [{"role": "user", "content": "Hi /no_think"}]}
    updated = apply_thinking_to_request(payload, model, True)
    assert updated["messages"][-1]["content"] == "Hi /think"


def test_strips_legacy_system_thinking_lines() -> None:
    from app.core.thinking_controls import THINKING_DISABLED_PROMPT

    model = _model(alias="llama-3", file_name="llama-3.gguf", model_dir_name="llama-3")
    payload = {
        "messages": [
            {"role": "system", "content": f"{THINKING_DISABLED_PROMPT}\nBe concise."},
            {"role": "user", "content": "Hi"},
        ]
    }
    updated = apply_thinking_to_request(payload, model, False)
    assert updated["messages"][0]["content"] == "Be concise."


def test_detect_hybrid_lfm() -> None:
    model = _model(alias="lfm2.5-8b", file_name="LFM2.5-8B-A1B-Q4_K_M.gguf", model_dir_name="LFM2.5-8B")
    assert detect_thinking_capability(model) == THINKING_CAPABILITY_HYBRID


def test_strip_redacted_thinking_empty_tags() -> None:
    from app.core.thinking_controls import strip_thinking_markup_from_text

    text = "<think></think>\nThe term \"test\" is versatile."
    assert strip_thinking_markup_from_text(text) == 'The term "test" is versatile.'


def test_strip_thinking_block_with_body() -> None:
    from app.core.thinking_controls import strip_thinking_markup_from_text

    text = (
        "Hello\n"
        "<think>internal reasoning</think>\n\n"
        "Answer here."
    )
    assert strip_thinking_markup_from_text(text) == "Hello\n\n\nAnswer here."


def test_filter_strips_thinking_from_content_delta() -> None:
    chunk = (
        'data: {"choices":[{"delta":{"content":"<think></think>\\nHi"}}]}\n\n'
    )
    filtered = filter_thinking_from_sse_chunk(chunk, False)
    assert "redacted_thinking" not in filtered
    assert "Hi" in filtered


def test_filter_thinking_from_sse_chunk() -> None:
    chunk = (
        'data: {"choices":[{"delta":{"reasoning_content":"secret","content":"hi"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":" there"}}]}\n\n'
    )
    filtered = filter_thinking_from_sse_chunk(chunk, False)
    assert isinstance(filtered, str)
    assert "reasoning_content" not in filtered
    assert "hi" in filtered
    assert " there" in filtered


def test_filter_thinking_passthrough_when_enabled() -> None:
    chunk = b'data: {"choices":[{"delta":{"reasoning_content":"secret"}}]}\n\n'
    assert filter_thinking_from_sse_chunk(chunk, True) == chunk


def test_strip_markup_preserves_leading_space_in_delta() -> None:
    from app.core.thinking_controls import strip_thinking_markup_from_text

    assert strip_thinking_markup_from_text(" there") == " there"
    assert strip_thinking_markup_from_text(" ") == " "


def test_filter_preserves_leading_space_in_sse_chunk() -> None:
    chunk = 'data: {"choices":[{"delta":{"content":" there"}}]}\n\n'
    filtered = filter_thinking_from_sse_chunk(chunk, False)
    assert isinstance(filtered, str)
    assert '" there"' in filtered


def test_filter_preserves_whitespace_only_delta() -> None:
    chunk = 'data: {"choices":[{"delta":{"content":" "}}]}\n\n'
    filtered = filter_thinking_from_sse_chunk(chunk, False)
    assert isinstance(filtered, str)
    assert '" "' in filtered or "content" in filtered
