"""Hot-path dialogue stage — a SINGLE guard-aware LLM call, streamed.

One call per turn, never chained. The reply is **streamed** and emitted
sentence-by-sentence so TTS can start speaking the first phrase while the rest is
still being generated (the key to the first-audio budget). The coach prompt adapts
to the learner's level and topic so questions are appropriately pitched. Reasoning
models (Qwen3) are told not to think, and any ``<think>…</think>`` is stripped so it
is never spoken. Emojis are kept in the *text* but stripped from TTS input via
:func:`speakable_text` (a spoken "smiling face" is not what a coach wants).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from backend.coldpath.scoring import level_name
from backend.serving.llm_client import VLLMClient

_MAX_HISTORY_TURNS = 8
_NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_SENTENCE = re.compile(r"(.+?[.!?…]+[\"')\]]*)(\s+|$)", re.DOTALL)

# Emoji / pictographs / symbols / variation selectors — remove before TTS so the
# voice never reads them aloud ("smiling face"). Kept in the displayed text.
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"  # symbols & pictographs, emoji, supplemental
    "\U00002600-\U000027bf"  # misc symbols + dingbats
    "\U0001f1e6-\U0001f1ff"  # regional indicators (flags)
    "\U00002190-\U000021ff"  # arrows
    "\U00002b00-\U00002bff"  # misc symbols & arrows
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"             # zero-width joiner
    "]+",
    flags=re.UNICODE,
)


def speakable_text(text: str) -> str:
    """Text with emojis/symbols removed, for TTS. Punctuation/words are preserved."""
    return re.sub(r"\s{2,}", " ", _EMOJI.sub("", text)).strip()


def coach_system_prompt(level: int, topic: str | None) -> str:
    """A coach persona pitched at the learner's level and (optional) topic."""
    name = level_name(level)
    guidance = {
        0: "Use very simple words and short sentences. Speak slowly and encourage.",
        1: "Use simple vocabulary; ask concrete, everyday questions.",
        2: "Discuss familiar topics; introduce some richer vocabulary.",
        3: "Use workplace/technical language; ask for opinions and explanations.",
        4: "Converse naturally; challenge with nuanced, open-ended questions.",
        5: "Use idiomatic, native-level language; debate and probe deeply.",
    }.get(level, "")
    topic_line = (
        f" Keep the conversation focused on this topic: {topic}." if topic else ""
    )
    return (
        f"You are a friendly, encouraging English speaking coach. The learner is at "
        f"level {level}/5 ({name}). {guidance}{topic_line} Reply in one or two short, "
        f"natural sentences and always end with ONE engaging follow-up question suited "
        f"to their level. Gently model correct usage without lecturing. Do NOT use "
        f"emojis or emoticons."
    )


def _drain_sentences(buf: str) -> tuple[list[str], str]:
    """Pull complete, think-free sentences out of a streaming buffer."""
    buf = _THINK_BLOCK.sub("", buf)
    hold = ""
    idx = buf.find("<think>")
    if idx != -1:  # unclosed think — buffer it until the closer arrives
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
        self._default_prompt = system_prompt
        self._max_tokens = max_tokens

    def _messages(
        self, transcript: str, history: list[dict[str, str]], system_prompt: str | None
    ) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": system_prompt or self._default_prompt}]
        messages.extend(history[-_MAX_HISTORY_TURNS:])
        messages.append({"role": "user", "content": transcript})
        return messages

    async def reply_stream(
        self,
        transcript: str,
        history: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield the coach reply one clean sentence at a time as it streams."""
        buf = ""
        async for delta in self._client.chat_stream(
            self._messages(transcript, history, system_prompt),
            path="hot",
            max_tokens=self._max_tokens,
            temperature=0.7,
            extra=_NO_THINKING,
        ):
            buf += delta
            sentences, buf = _drain_sentences(buf)
            for s in sentences:
                yield s
        buf = _THINK_BLOCK.sub("", buf)
        buf = re.sub(r"<think>.*", "", buf, flags=re.DOTALL)
        tail = buf.strip()
        if tail:
            yield tail

    async def reply(
        self, transcript: str, history: list[dict[str, str]], *, system_prompt: str | None = None
    ) -> str:
        text = await self._client.chat(
            self._messages(transcript, history, system_prompt),
            path="hot",
            max_tokens=self._max_tokens,
            temperature=0.7,
            extra=_NO_THINKING,
        )
        text = _THINK_BLOCK.sub("", text)
        return re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()
