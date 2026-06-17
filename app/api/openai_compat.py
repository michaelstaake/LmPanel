import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import require_api_access, require_models_api_access
from app.core.activity_logger import log_event
from app.core.db import SessionLocal, get_db
from app.core.v1_models_cache import get_cached_v1_models
from app.core.inference_manager import InferenceManager
from app.core.knowledge_base import build_rag_context, retrieve_relevant_documents
from app.core.app_settings import get_or_create_app_settings
from app.core.token_usage import record_token_usage
from app.core.usage_limits import check_tool_usage_limit_for_request, check_usage_limit_for_request
from app.core.task_manager import task_manager
from app.core.web_search import WEB_SEARCH_TOOL_DEFINITION, get_search_provider, parse_sse_chunks
from app.models.app_settings import AppSettings
from app.models.knowledge_base import KnowledgeBaseDocument
from app.models.model_config import ModelConfig
from app.models.user import User
from app.models.web_search_provider import WebSearchProvider as WebSearchProviderModel
from app.core.thinking_controls import (
    apply_thinking_to_request,
    filter_thinking_from_sse_chunk,
    model_thinking_metadata,
    resolve_thinking_enabled,
)
from app.utils.schemas import OpenAIChatRequest

logger = logging.getLogger(__name__)

_WEB_SEARCH_MAX_ITERATIONS = 5

router = APIRouter(prefix="/v1", tags=["openai"])


def _coerce_usage_count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None

    if isinstance(value, int):
        return value if value > 0 else None

    if isinstance(value, float):
        coerced = int(value)
        return coerced if coerced > 0 else None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            coerced = int(text)
        except ValueError:
            return None
        return coerced if coerced > 0 else None

    return None


def _record_usage(usage: Any, *, user_id: int | None, tool_calls: int = 0) -> bool:
    if not isinstance(usage, dict):
        return False

    total_tokens = _coerce_usage_count(usage.get("total_tokens"))
    if total_tokens is None:
        total_tokens = _coerce_usage_count(usage.get("totalTokens"))
    input_tokens = _coerce_usage_count(usage.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _coerce_usage_count(usage.get("promptTokens"))
    output_tokens = _coerce_usage_count(usage.get("completion_tokens"))
    if output_tokens is None:
        output_tokens = _coerce_usage_count(usage.get("completionTokens"))

    if total_tokens is None and input_tokens is None and output_tokens is None and tool_calls <= 0:
        return False

    db = SessionLocal()
    try:
        return record_token_usage(
            db,
            user_id=user_id,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_calls=tool_calls,
        )
    finally:
        db.close()


def _usage_counts_from_raw(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None

    total_tokens = _coerce_usage_count(usage.get("total_tokens"))
    if total_tokens is None:
        total_tokens = _coerce_usage_count(usage.get("totalTokens"))
    input_tokens = _coerce_usage_count(usage.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _coerce_usage_count(usage.get("promptTokens"))
    output_tokens = _coerce_usage_count(usage.get("completion_tokens"))
    if output_tokens is None:
        output_tokens = _coerce_usage_count(usage.get("completionTokens"))

    if total_tokens is None and input_tokens is None and output_tokens is None:
        return None

    return {
        "total_tokens": total_tokens or 0,
        "prompt_tokens": input_tokens or 0,
        "completion_tokens": output_tokens or 0,
    }


def _merge_usage_counts(base: dict[str, int] | None, addition: dict[str, int]) -> dict[str, int]:
    if base is None:
        return dict(addition)

    return {
        "total_tokens": base.get("total_tokens", 0) + addition.get("total_tokens", 0),
        "prompt_tokens": base.get("prompt_tokens", 0) + addition.get("prompt_tokens", 0),
        "completion_tokens": base.get("completion_tokens", 0) + addition.get("completion_tokens", 0),
    }


def _extract_usage_from_sse_chunk(chunk: bytes | str) -> dict[str, int] | None:
    if isinstance(chunk, bytes):
        chunk = chunk.decode("utf-8", errors="replace")

    accumulated: dict[str, int] | None = None
    for event in chunk.replace("\r\n", "\n").split("\n\n"):
        if not event.strip():
            continue

        for line in event.split("\n"):
            if not line.startswith("data:"):
                continue

            payload_str = line[5:].strip()
            if not payload_str or payload_str == "[DONE]":
                continue

            try:
                payload = json.loads(payload_str)
            except (json.JSONDecodeError, ValueError):
                continue

            usage_counts = _usage_counts_from_raw(payload.get("usage"))
            if usage_counts is not None:
                accumulated = _merge_usage_counts(accumulated, usage_counts)

    return accumulated


def _record_usage_from_sse_chunk(chunk: bytes | str, *, user_id: int | None, tool_calls: int = 0) -> bool:
    usage_counts = _extract_usage_from_sse_chunk(chunk)
    if usage_counts is None:
        return False

    return _record_usage(usage_counts, user_id=user_id, tool_calls=tool_calls)


def _prepend_rag_context(messages: list[dict], rag_context: str) -> list[dict]:
    """Prepend RAG context as a system message at the beginning of the messages list."""
    if not rag_context:
        return messages

    if messages and messages[0].get("role") == "system":
        existing = messages[0].get("content") or ""
        combined = f"{rag_context}\n\n{existing}"
        return [{**messages[0], "content": combined}, *messages[1:]]

    return [{"role": "system", "content": rag_context}, *messages]


def _get_active_web_search_provider(db: Session) -> Any | None:
    """Return an active, configured WebSearchProvider instance, or None."""
    settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if not settings or settings.active_web_search_provider_id is None:
        return None
    provider_row = (
        db.query(WebSearchProviderModel)
        .filter(
            WebSearchProviderModel.id == settings.active_web_search_provider_id,
            WebSearchProviderModel.enabled.is_(True),
        )
        .first()
    )
    if not provider_row or not provider_row.api_key:
        return None
    return get_search_provider(provider_row.provider_type, provider_row.api_key, provider_row.result_count)


async def _execute_web_searches(
    tool_calls: list[dict[str, Any]],
    provider: Any,
) -> list[dict[str, Any]]:
    """Execute web_search tool calls and return tool result messages."""
    result_messages: list[dict[str, Any]] = []
    for tc in tool_calls:
        if tc.get("function", {}).get("name") != "web_search":
            continue
        try:
            args = json.loads(tc.get("function", {}).get("arguments", "{}"))
            query = args.get("query", "")
            search_results = await provider.search(query)
            content = json.dumps(search_results, ensure_ascii=False)
        except Exception:
            logger.exception("Web search failed for tool call %s", tc.get("id"))
            content = json.dumps([{"error": "Search failed. Please try a different query."}])
        result_messages.append({
            "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "content": content,
        })
    return result_messages


async def _run_web_search_non_streaming(
    inference: InferenceManager,
    model_id: int,
    request_payload: dict[str, Any],
    provider: Any,
    *,
    request_timeout: int | None = None,
) -> tuple[dict[str, Any], int]:
    """Run the agentic web search loop for non-streaming requests.

    Executes up to _WEB_SEARCH_MAX_ITERATIONS tool call turns, then returns
    the final text response.

    Returns a tuple of (result, total_web_search_tool_calls).
    """
    messages = list(request_payload["messages"])
    tools = list(request_payload.get("tools") or [])
    total_tool_calls = 0

    for _ in range(_WEB_SEARCH_MAX_ITERATIONS):
        result = await inference.chat_completion(model_id, {**request_payload, "messages": messages, "tools": tools}, request_timeout=request_timeout)
        choices = result.get("choices", [])
        if not choices:
            return result, total_tool_calls

        choice = choices[0]
        if choice.get("finish_reason") != "tool_calls":
            return result, total_tool_calls

        message = choice.get("message", {})
        tool_calls = message.get("tool_calls", [])
        web_search_calls = [tc for tc in tool_calls if tc.get("function", {}).get("name") == "web_search"]
        if not web_search_calls:
            # Non-web-search tool calls — return as-is so the client can handle them
            return result, total_tool_calls

        total_tool_calls += len(web_search_calls)
        messages = messages + [message]
        tool_results = await _execute_web_searches(web_search_calls, provider)
        messages = messages + tool_results

    # Exhausted iterations — request a final text answer without tools
    final_result = await inference.chat_completion(model_id, {**request_payload, "messages": messages, "tools": []}, request_timeout=request_timeout)
    return final_result, total_tool_calls


async def _stream_with_web_search(
    inference: InferenceManager,
    model_id: int,
    request_payload: dict[str, Any],
    provider: Any,
    *,
    thinking_enabled: bool = True,
    request_timeout: int | None = None,
    _tool_calls_container: dict[str, int] | None = None,
):
    """Async generator for streaming responses with web search support.

    Runs tool call turns as non-streaming internally, then streams the final answer.

    If _tool_calls_container is provided, the total web_search tool call count is
    stored in it under the "total" key.
    """
    messages = list(request_payload["messages"])
    tools = list(request_payload.get("tools") or [])
    stream_options = dict(request_payload.get("stream_options") or {})
    stream_options.setdefault("include_usage", True)

    for iteration in range(_WEB_SEARCH_MAX_ITERATIONS):
        # For the last iteration, strip tools to force a text response
        current_tools = [] if iteration == _WEB_SEARCH_MAX_ITERATIONS - 1 else tools

        # Preserve usage in the buffered stream so the UI can compute token stats
        # even when web search is enabled but no tool call is actually made.
        buffered: list[bytes] = []
        intermediate_payload = dict(request_payload)
        intermediate_payload["stream"] = True
        intermediate_payload["messages"] = messages
        intermediate_payload["tools"] = current_tools
        intermediate_payload["stream_options"] = stream_options
        async for chunk in inference.stream_chat_completion(model_id, intermediate_payload, request_timeout=request_timeout):
            buffered.append(chunk)
            yield filter_thinking_from_sse_chunk(chunk, thinking_enabled)

        message, finish_reason = parse_sse_chunks(buffered)
        tool_calls = message.get("tool_calls", [])
        web_search_calls = [tc for tc in tool_calls if tc.get("function", {}).get("name") == "web_search"]

        if finish_reason != "tool_calls" or not web_search_calls:
            # Final answer — already streamed above, just return
            return

        # Count this iteration's web search tool calls
        if _tool_calls_container is not None:
            _tool_calls_container["total"] = _tool_calls_container.get("total", 0) + len(web_search_calls)

        # Execute searches and continue loop
        messages = messages + [message]
        tool_results = await _execute_web_searches(web_search_calls, provider)
        messages = messages + tool_results

    # Exhausted iterations — stream the final answer without tools
    final_payload = dict(request_payload)
    final_payload["stream"] = True
    final_payload["messages"] = messages
    final_payload["tools"] = []
    final_payload["stream_options"] = stream_options
    async for chunk in inference.stream_chat_completion(model_id, final_payload, request_timeout=request_timeout):
        yield filter_thinking_from_sse_chunk(chunk, thinking_enabled)


def _build_v1_models_payload(db: Session) -> dict:
    active_web_search_provider = _get_active_web_search_provider(db)
    app_settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
    models = (
        db.query(ModelConfig)
        .filter(ModelConfig.activated.is_(True))
        .order_by(ModelConfig.priority.asc(), ModelConfig.id.asc())
        .all()
    )
    return {
        "object": "list",
        "data": [
            {
                "id": m.alias,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "lmpanel",
                "description": m.description,
                "context_length": m.context_length,
                "tool_calling_enabled": m.tool_calling_enabled,
                **model_thinking_metadata(m),
                "vision_enabled": m.vision_enabled,
                "web_search_enabled": m.web_search_enabled,
                "web_search_available": m.web_search_enabled and m.tool_calling_enabled and active_web_search_provider is not None,
                "rag_enabled": m.rag_enabled,
                "rag_available": m.rag_enabled and m.tool_calling_enabled and app_settings and app_settings.knowledge_base_enabled,
            }
            for m in models
        ],
    }


@router.get("/models")
def v1_models(_: User = Depends(require_models_api_access), db: Session = Depends(get_db)) -> dict:
    return get_cached_v1_models(lambda: _build_v1_models_payload(db))


@router.post("/chat/completions")
async def v1_chat_completions(payload: OpenAIChatRequest, current_user: User = Depends(require_api_access)):
    inference: InferenceManager = router.inference_manager  # type: ignore[attr-defined]
    current_user_id = current_user.id if getattr(current_user, "id", None) else None

    db = SessionLocal()
    try:
        model = (
            db.query(ModelConfig)
            .filter(ModelConfig.alias == payload.model, ModelConfig.activated.is_(True))
            .first()
        )
        if not model:
            raise HTTPException(status_code=404, detail="Model not found or not active")

        app_settings = get_or_create_app_settings(db)
        usage_limit_result = check_usage_limit_for_request(
            db,
            user=current_user,
            app_settings=app_settings,
        )
        if not usage_limit_result.allowed:
            raise HTTPException(status_code=429, detail=usage_limit_result.detail or "Token usage limit reached")

        if payload.requests_tooling():
            if not model.tool_calling_enabled:
                raise HTTPException(
                    status_code=400,
                    detail="Tool calling is disabled for this model. Enable tool calling in the model settings before sending tool requests.",
                )

        web_search_requested = payload.use_web_search if payload.use_web_search is not None else model.web_search_enabled

        if web_search_requested and not model.web_search_enabled:
            raise HTTPException(
                status_code=400,
                detail="Web search is disabled for this model. Enable it in the model settings before requesting search.",
            )

        if web_search_requested and not model.tool_calling_enabled:
            raise HTTPException(
                status_code=400,
                detail="Web search requires tool calling to be enabled for this model. Enable tool calling in the model settings.",
            )

        active_web_search_provider = _get_active_web_search_provider(db) if web_search_requested else None

        if active_web_search_provider is not None:
            tool_usage_limit_result = check_tool_usage_limit_for_request(
                db,
                user=current_user,
                app_settings=app_settings,
            )
            if not tool_usage_limit_result.allowed:
                raise HTTPException(status_code=429, detail=tool_usage_limit_result.detail or "Tool usage limit reached")

        if payload.requests_vision() and not model.vision_enabled:
            raise HTTPException(
                status_code=400,
                detail="Vision is disabled for this model. Enable vision in the model settings before sending image requests.",
            )

        log_event(
            db,
            "chat.completion",
            user_id=current_user_id,
            username=current_user.username,
            details={"model": model.alias, "stream": payload.stream},
        )

        request_payload = payload.model_dump(exclude_none=True)
        if "temperature" not in request_payload:
            request_payload["temperature"] = model.temperature
        if "top_p" not in request_payload:
            request_payload["top_p"] = model.top_p
        if "top_k" not in request_payload:
            request_payload["top_k"] = model.top_k
        if "presence_penalty" not in request_payload:
            request_payload["presence_penalty"] = model.presence_penalty
        if "repetition_penalty" not in request_payload:
            request_payload["repetition_penalty"] = model.repetition_penalty
        request_payload["enable_thinking"] = resolve_thinking_enabled(model, payload.enable_thinking)
        thinking_enabled = bool(request_payload["enable_thinking"])
        request_payload["messages"] = [
            {
                key: value
                for key, value in message.model_dump(exclude_none=True).items()
                if key != "content" or value != ""
            }
            for message in payload.messages
        ]

        request_payload = apply_thinking_to_request(request_payload, model, thinking_enabled)

        rag_context = ""
        rag_enabled = payload.model_extra.get("rag_enabled", False) if payload.model_extra else False
        rag_enabled = rag_enabled or model.rag_enabled
        if rag_enabled and app_settings.knowledge_base_enabled:
            last_user_message = ""
            for msg in reversed(payload.messages):
                if msg.role == "user":
                    last_user_message = msg.content if isinstance(msg.content, str) else ""
                    break
            if last_user_message:
                docs = retrieve_relevant_documents(db, current_user.id, last_user_message)
                rag_context = build_rag_context(docs, last_user_message)

        if rag_context:
            request_payload["messages"] = _prepend_rag_context(request_payload["messages"], rag_context)

        if payload.use_web_search and active_web_search_provider is None:
            raise HTTPException(
                status_code=400,
                detail="No active web search provider is configured. Select one in Settings > Web Search before requesting search.",
            )

        model_id = model.id
        model_alias = model.alias
    finally:
        db.close()

    task_id = str(uuid.uuid4())
    task_manager.add_task(
        task_id=task_id,
        task_type="chat",
        description=f"Chat request: {model_alias}",
        metadata={
            "model": model_alias,
            "user_id": current_user_id,
            "username": current_user.username,
            "stream": payload.stream,
        },
    )

    if active_web_search_provider is not None:
        existing_tools = list(request_payload.get("tools") or [])
        already_has_web_search = any(
            t.get("function", {}).get("name") == "web_search"
            for t in existing_tools
            if t.get("type") == "function"
        )
        if not already_has_web_search:
            request_payload["tools"] = existing_tools + [WEB_SEARCH_TOOL_DEFINITION]

        if payload.stream:
            _web_search_tool_calls: dict[str, int] = {}

            async def web_search_event_stream():
                accumulated_usage: dict[str, int] | None = None
                current_task = asyncio.current_task()
                if current_task is not None:
                    task_manager.attach_async_task(task_id, current_task)
                try:
                    async for chunk in _stream_with_web_search(
                        inference,
                        model_id,
                        request_payload,
                        active_web_search_provider,
                        thinking_enabled=thinking_enabled,
                        request_timeout=app_settings.request_timeout_seconds,
                        _tool_calls_container=_web_search_tool_calls,
                    ):
                        extracted_usage = _extract_usage_from_sse_chunk(chunk)
                        if extracted_usage is not None:
                            accumulated_usage = _merge_usage_counts(accumulated_usage, extracted_usage)
                        yield chunk
                    total_web_search_calls = _web_search_tool_calls.get("total", 0)
                    if accumulated_usage is not None or total_web_search_calls > 0:
                        _record_usage(
                            accumulated_usage or {},
                            user_id=current_user_id,
                            tool_calls=total_web_search_calls,
                        )
                    task_manager.complete_task(task_id)
                except asyncio.CancelledError:
                    task_manager.mark_cancelled(task_id)
                    raise
                except RuntimeError as exc:
                    task_manager.fail_task(task_id, str(exc))
                    err_msg = str(exc).replace("\\", "\\\\").replace('"', '\\"')
                    yield f'data: {{"error": {{"message": "{err_msg}"}}}}\n\n'
                    yield "data: [DONE]\n\n"

            return StreamingResponse(web_search_event_stream(), media_type="text/event-stream")

        task_manager.attach_async_task(task_id, asyncio.current_task())
        try:
            result, total_tool_calls = await _run_web_search_non_streaming(inference, model_id, request_payload, active_web_search_provider, request_timeout=app_settings.request_timeout_seconds)
        except asyncio.CancelledError:
            task_manager.mark_cancelled(task_id)
            raise
        except RuntimeError as exc:
            task_manager.fail_task(task_id, str(exc))
            raise
        task_manager.complete_task(task_id)
        _record_usage(result.get("usage"), user_id=current_user_id, tool_calls=total_tool_calls)
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_alias,
            "choices": result.get("choices", []),
            "usage": result.get("usage", {}),
        }

    if payload.stream:
        async def event_stream():
            usage_recorded = False
            current_task = asyncio.current_task()
            if current_task is not None:
                task_manager.attach_async_task(task_id, current_task)
            try:
                async for chunk in inference.stream_chat_completion(model_id, {
                    **request_payload,
                    "stream_options": {"include_usage": True},
                }, request_timeout=app_settings.request_timeout_seconds):
                    if not usage_recorded:
                        usage_recorded = _record_usage_from_sse_chunk(
                            chunk,
                            user_id=current_user_id,
                            tool_calls=0,
                        )
                    yield filter_thinking_from_sse_chunk(chunk, thinking_enabled)
                task_manager.complete_task(task_id)
            except asyncio.CancelledError:
                task_manager.mark_cancelled(task_id)
                raise
            except RuntimeError as exc:
                task_manager.fail_task(task_id, str(exc))
                message = str(exc).replace("\\", "\\\\").replace('"', '\\"')
                yield f'data: {{"error": {{"message": "{message}"}}}}\n\n'
                yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    task_manager.attach_async_task(task_id, asyncio.current_task())
    try:
        result = await inference.chat_completion(model_id, request_payload, request_timeout=app_settings.request_timeout_seconds)
    except asyncio.CancelledError:
        task_manager.mark_cancelled(task_id)
        raise
    except RuntimeError as exc:
        task_manager.fail_task(task_id, str(exc))
        raise
    task_manager.complete_task(task_id)
    _record_usage(result.get("usage"), user_id=current_user_id, tool_calls=0)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_alias,
        "choices": result.get("choices", []),
        "usage": result.get("usage", {}),
    }
