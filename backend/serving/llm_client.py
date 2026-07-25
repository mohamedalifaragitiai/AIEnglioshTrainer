"""vLLM client — OpenAI-compatible HTTP, guard-aware.

vLLM runs as a **separate process** (native Linux/WSL2) and exposes an
OpenAI-compatible API. The app worker never imports vLLM or loads weights; it only
talks HTTP. One vLLM server hosts both the hot 8B and the cold 14B; this client
selects the model per call.

Guard integration: before a hot-path call the client asks the ResourceGuard for an
admission and honors a degraded ``max_tokens`` (never blocks the live turn). The
vLLM VRAM reservation is the guard's fixed pre-committed block, so ``acquire`` here
governs request shape, not admission of the reservation itself.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Literal

import httpx

from backend.core import metrics
from backend.core.logging import get_logger
from backend.core.resource_guard import ResourceEstimate, ResourceGuard

log = get_logger("llm_client")

Path = Literal["hot", "cold"]


class LLMError(RuntimeError):
    pass


class VLLMClient:
    def __init__(
        self,
        base_url: str,
        *,
        hot_model: str,
        cold_model: str,
        guard: ResourceGuard | None = None,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.hot_model = hot_model
        self.cold_model = cold_model
        self.guard = guard
        # Injectable client makes this unit-testable against a MockTransport.
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout_s)

    def model_for(self, path: Path) -> str:
        return self.hot_model if path == "hot" else self.cold_model

    async def health(self) -> bool:
        """True if the vLLM server responds. Never raises."""
        try:
            resp = await self._client.get("/health")
            if resp.status_code == 200:
                return True
            resp = await self._client.get("/v1/models")
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            log.warning("vllm_health_failed", error=str(exc))
            return False

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        path: Path = "hot",
        max_tokens: int = 512,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """One chat completion. Honors guard degradation on the hot path."""
        effective_max = max_tokens
        if self.guard is not None:
            adm = await self.guard.acquire(
                ResourceEstimate(llm_max_tokens=max_tokens, llm_context=4096), path
            )
            if adm.kind == "reject":
                raise LLMError(f"guard rejected LLM call: {adm.reason}")
            if adm.kind == "degraded" and "max_tokens" in adm.params:
                effective_max = adm.params["max_tokens"]
                log.info("llm_degraded", path=path, max_tokens=effective_max, reason=adm.reason)

        model = self.model_for(path)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": effective_max,
            "temperature": temperature,
        }
        if extra:
            payload.update(extra)

        t0 = perf_counter()
        try:
            resp = await self._client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"vLLM request failed: {exc}") from exc
        finally:
            metrics.llm_request_duration_seconds.labels(model, path).observe(perf_counter() - t0)

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected vLLM response shape: {data!r}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()
