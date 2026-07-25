"""Hot-path dialogue stage — a SINGLE guard-aware LLM call.

One call per turn, never chained: chaining LLM calls into the live loop is the
fastest way to blow the <300ms budget. Guard degradation (trimmed max_tokens under
pressure) is handled inside the vLLM client, so this stage just shapes the prompt.
"""

from __future__ import annotations

from backend.serving.llm_client import VLLMClient

# Keep the live context short — long histories cost latency and KV cache.
_MAX_HISTORY_TURNS = 8


class DialogueStage:
    def __init__(self, client: VLLMClient, *, system_prompt: str, max_tokens: int = 200):
        self._client = client
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens

    async def reply(self, transcript: str, history: list[dict[str, str]]) -> str:
        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(history[-_MAX_HISTORY_TURNS:])
        messages.append({"role": "user", "content": transcript})
        return await self._client.chat(
            messages, path="hot", max_tokens=self._max_tokens, temperature=0.7
        )
