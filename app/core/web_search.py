import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PROVIDER_TYPES: list[str] = ["brave", "serper"]

WEB_SEARCH_TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information. Use this when you need up-to-date "
            "facts, news, recent events, or information that may not be in your training data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up on the web.",
                }
            },
            "required": ["query"],
        },
    },
}


class WebSearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str) -> list[dict[str, Any]]:
        ...


class BraveSearchProvider(WebSearchProvider):
    _BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, result_count: int = 5) -> None:
        self._api_key = api_key
        self._result_count = max(1, min(20, result_count))

    async def search(self, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._BASE_URL,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": self._api_key,
                },
                params={"q": query, "count": self._result_count},
            )
            response.raise_for_status()
            data = response.json()

        results: list[dict[str, Any]] = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            })
        return results


class SerperSearchProvider(WebSearchProvider):
    _BASE_URL = "https://google.serper.dev/search"

    def __init__(self, api_key: str, result_count: int = 5) -> None:
        self._api_key = api_key
        self._result_count = max(1, min(20, result_count))

    async def search(self, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self._BASE_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-API-KEY": self._api_key,
                },
                json={"q": query, "num": self._result_count},
            )
            response.raise_for_status()
            data = response.json()

        results: list[dict[str, Any]] = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "description": item.get("snippet", ""),
            })
        return results


def get_search_provider(provider_type: str, api_key: str, result_count: int = 5) -> WebSearchProvider | None:
    if provider_type == "brave":
        return BraveSearchProvider(api_key, result_count)
    if provider_type == "serper":
        return SerperSearchProvider(api_key, result_count)
    return None


def parse_sse_chunks(chunks: list) -> tuple[dict[str, Any], str | None]:
    """Parse SSE streaming chunks into an assembled assistant message and finish_reason."""
    content = ""
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    finish_reason: str | None = None
    buffer_parts: list[str] = []

    for chunk in chunks:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", errors="replace")
        buffer_parts.append(chunk)

    buffer = "".join(buffer_parts).replace("\r\n", "\n")

    for event in buffer.split("\n\n"):
        if not event.strip():
            continue

        for line in event.split("\n"):
            if not line.startswith("data:"):
                continue

            payload_str = line[5:].strip()
            if not payload_str or payload_str == "[DONE]":
                continue

            try:
                data = json.loads(payload_str)
            except (json.JSONDecodeError, ValueError):
                continue

            for choice in data.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content"):
                    content += delta["content"]
                for tc_delta in delta.get("tool_calls", []):
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc_delta.get("id"):
                        tool_calls_by_index[idx]["id"] = tc_delta["id"]
                    fn = tc_delta.get("function", {})
                    if fn.get("name"):
                        tool_calls_by_index[idx]["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        tool_calls_by_index[idx]["function"]["arguments"] += fn["arguments"]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

    message: dict[str, Any] = {"role": "assistant"}
    if content:
        message["content"] = content
    if tool_calls_by_index:
        message["tool_calls"] = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index.keys())]

    return message, finish_reason
