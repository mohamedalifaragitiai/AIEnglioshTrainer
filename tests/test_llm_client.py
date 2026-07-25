"""Tests for the vLLM HTTP client against a mock transport (no server needed)."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.serving.llm_client import LLMError, VLLMClient
from tests.conftest import feed_steady


def _client(handler, guard=None) -> VLLMClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://vllm.test")
    return VLLMClient(
        "http://vllm.test", hot_model="hot-8b", cold_model="cold-14b", guard=guard, client=http
    )


async def test_health_true():
    def handler(request):
        return httpx.Response(200, json={"status": "ok"})

    assert await _client(handler).health() is True


async def test_health_false_on_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    assert await _client(handler).health() is False


async def test_chat_returns_content():
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Hello there."}}]}
        )

    out = await _client(handler).chat([{"role": "user", "content": "hi"}])
    assert out == "Hello there."


async def test_chat_selects_model_by_path():
    seen = {}

    def handler(request):
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    client = _client(handler)
    await client.chat([{"role": "user", "content": "hi"}], path="cold")
    assert seen["model"] == "cold-14b"


async def test_chat_honors_guard_degradation(guard, sampler):
    # Drive the guard to level 2 → LLM max_tokens should be trimmed.
    feed_steady(guard, sampler, 0.92)
    seen = {}

    def handler(request):
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    client = _client(handler, guard=guard)
    await client.chat([{"role": "user", "content": "hi"}], path="hot", max_tokens=512)
    assert seen["json"]["max_tokens"] < 512  # degraded


async def test_chat_raises_on_http_error():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(LLMError):
        await _client(handler).chat([{"role": "user", "content": "hi"}])


async def test_chat_raises_on_bad_shape():
    def handler(request):
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(LLMError):
        await _client(handler).chat([{"role": "user", "content": "hi"}])
