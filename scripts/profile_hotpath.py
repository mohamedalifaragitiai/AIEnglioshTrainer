"""Profile the hot path against the <300ms first-audio budget.

Runs synthetic turns through the REAL pipeline with fake stages whose latencies you
control, so the stage-by-stage breakdown and the time-to-first-audio are measured
the same way production is. Exits non-zero if p90 first-audio exceeds the budget —
so it can gate CI on latency regressions.

Run:  uv run python scripts/profile_hotpath.py
      uv run python scripts/profile_hotpath.py --stt-ms 90 --llm-ms 140 --tts-first-ms 60 -n 30
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator

from backend.core.logging import configure_logging
from backend.core.resource_guard import PsutilNvmlSampler, ResourceGuard
from backend.hotpath.base import HotEventKind
from backend.hotpath.pipeline import HotPathPipeline, TurnContext
from config.settings import get_settings


class FakeSTT:
    def __init__(self, ms: float):
        self.ms = ms

    def available(self) -> bool:
        return True

    async def transcribe(self, pcm: bytes, sample_rate: int) -> tuple[str, float]:
        await asyncio.sleep(self.ms / 1000)
        return "This is a synthetic learner utterance.", 0.92


class FakeDialogue:
    def __init__(self, ms: float):
        self.ms = ms

    async def reply(self, transcript: str, history: list[dict[str, str]]) -> str:
        await asyncio.sleep(self.ms / 1000)
        return "That's a great point. Tell me more about it."

    async def reply_stream(self, transcript: str, history: list[dict[str, str]]):
        await asyncio.sleep(self.ms / 1000)
        yield "That's a great point. Tell me more about it."


class FakeTTS:
    def __init__(self, first_ms: float, chunk_ms: float, chunks: int):
        self.first_ms = first_ms
        self.chunk_ms = chunk_ms
        self.chunks = chunks

    def available(self) -> bool:
        return True

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        await asyncio.sleep(self.first_ms / 1000)
        for _ in range(self.chunks):
            yield b"\x00\x00" * 160
            await asyncio.sleep(self.chunk_ms / 1000)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))
    return s[idx]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Profile the hot path.")
    parser.add_argument("--stt-ms", type=float, default=80.0)
    parser.add_argument("--llm-ms", type=float, default=120.0)
    parser.add_argument("--tts-first-ms", type=float, default=50.0)
    parser.add_argument("--tts-chunk-ms", type=float, default=20.0)
    parser.add_argument("--tts-chunks", type=int, default=8)
    parser.add_argument("-n", "--turns", type=int, default=20)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level="WARNING", json_logs=False)

    sampler = PsutilNvmlSampler(disk_path=".")
    guard = ResourceGuard(sampler=sampler, settings=settings)
    guard.feed(sampler.sample())  # level 0

    pipeline = HotPathPipeline(
        FakeSTT(args.stt_ms),
        FakeDialogue(args.llm_ms),
        FakeTTS(args.tts_first_ms, args.tts_chunk_ms, args.tts_chunks),
        guard=guard,
        settings=settings,
    )
    ctx = TurnContext(session_id="profile", user_id="profile", history=[])
    pcm = b"\x00\x00" * settings.hotpath_sample_rate  # ~1s of silence

    stt, llm, tts_first, first_audio = [], [], [], []
    for _ in range(args.turns):
        async for ev in pipeline.run_turn(pcm, ctx):
            if ev.kind == HotEventKind.TIMINGS and ev.timings:
                t = ev.timings
                stt.append(t.stt_ms)
                llm.append(t.llm_ms)
                tts_first.append(t.tts_first_ms)
                first_audio.append(t.first_audio_ms)

    budget = settings.first_audio_budget_ms
    print(f"\n=== Hot-path profile ({args.turns} synthetic turns) ===")
    print(f"{'stage':<14}{'p50 (ms)':>12}{'p90 (ms)':>12}")
    print("-" * 38)
    for name, vals in (("STT", stt), ("LLM", llm), ("TTS first", tts_first)):
        print(f"{name:<14}{_pct(vals, 50):>12.1f}{_pct(vals, 90):>12.1f}")
    print("-" * 38)
    fa_p50, fa_p90 = _pct(first_audio, 50), _pct(first_audio, 90)
    print(f"{'FIRST AUDIO':<14}{fa_p50:>12.1f}{fa_p90:>12.1f}   budget={budget:.0f}ms")

    if hasattr(sampler, "shutdown"):
        sampler.shutdown()

    if fa_p90 > budget:
        print(f"\nOVER BUDGET: p90 first-audio {fa_p90:.0f}ms > {budget:.0f}ms.\n")
        return 1
    print(f"\nWITHIN BUDGET: p90 first-audio {fa_p90:.0f}ms <= {budget:.0f}ms.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
