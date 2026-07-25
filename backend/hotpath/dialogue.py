"""Hot-path dialogue stage — a SINGLE guard-aware LLM call, streamed.

One call per turn, never chained. The reply is **streamed** and emitted
sentence-by-sentence so the TTS stage can start speaking the first phrase while the
rest is still being generated — the key to the <300ms first-audio budget. Reasoning
models (Qwen3) are told not to think, and any ``<think>…</think>`` that slips through
is stripped so it is never spoken. Guard degradation (trimmed max_tokens) is handled
inside the vLLM client.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from backend.serving.llm_client import VLLMClient

# Keep the live context short — long histories cost latency and KV cache.
_MAX_HISTORY_TURNS = 8

# Disable a reasoning model's <think> pass at the source (Qwen3 via vLLM).
_NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
# A run of text ending at sentence punctuation (with trailing quotes/brackets).
_SENTENCE = re.compile(r"(.+?[.!?…]+[\"')\]]*)(\s+|$)", re.DOTALL)


def _drain_sentences(buf: str) -> tuple[list[str], str]:
    """Pull complete, think-free sentences out of a streaming buffer.

    Removes closed ``<think>…</think>`` blocks; if an *unclosed* ``<think>`` remains,
    holds everything from it back (buffered) until the closer arrives. Returns
    (complete_sentences, remaining_buffer).
    """
    buf = _THINK_BLOCK.sub("", buf)
    hold = ""
    idx = buf.find("<think>")
    if idx != -1:  # unclosed think — keep it (and anything after) buffered
        hold = buf[idx:]
        buf = buf[:idx]

    sentences: list[str] = []
    while (m := _SENTENCE.match(buf)) is not None:
        s = m.group(1).strip()
        if s:
            sentences.append(s)
        buf = buf[m.end() :]
    return sentences, buf + hold


class DialogueStage:
    def __init__(self, client: VLLMClient, *, system_prompt: str, max_tokens: int = 200):
        self._client = client
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens

    def _messages(self, transcript: str, history: list[dict[str, str]]) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": self._system_prompt}]
        messages.extend(history[-_MAX_HISTORY_TURNS:])
        messages.append({"role": "user", "content": transcript})
        return messages

    async def reply_stream(
        self, transcript: str, history: list[dict[str, str]]
    ) -> AsyncIterator[str]:
        """Yield the coach reply one clean sentence at a time as it streams."""
        buf = ""
        async for delta in self._client.chat_stream(
            self._messages(transcript, history),
            path="hot",
            max_tokens=self._max_tokens,
            temperature=0.7,
            extra=_NO_THINKING,
        ):
            buf += delta
            sentences, buf = _drain_sentences(buf)
            for s in sentences:
                yield s
        # Flush the tail (strip any leftover/unclosed think), emit what remains.
        buf = _THINK_BLOCK.sub("", buf)
        buf = re.sub(r"<think>.*", "", buf, flags=re.DOTALL)
        tail = buf.strip()
        if tail:
            yield tail

    async def reply(self, transcript: str, history: list[dict[str, str]]) -> str:
        """Non-streaming convenience (full reply). Strips think blocks."""
        text = await self._client.chat(
            self._messages(transcript, history),
            path="hot",
            max_tokens=self._max_tokens,
            temperature=0.7,
            extra=_NO_THINKING,
        )
        text = _THINK_BLOCK.sub("", text)
        return re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()
