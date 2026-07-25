"""Benchmark the vLLM-served LLMs — streaming TTFT, total, and tokens/sec.

vLLM runs as a separate process (native Linux/WSL2). Point this at it via
COACH_VLLM_BASE_URL. Measures time-to-first-token (the hot-path-relevant metric),
total generation time, and throughput for the hot 8B and cold 14B. If the server
isn't reachable it prints the WSL2 launch command and exits cleanly.

Run (from Windows or WSL, with vLLM running):
    COACH_VLLM_BASE_URL=http://127.0.0.1:8001 \
      uv run python scripts/benchmark_llm.py          # or .venv/Scripts/python
"""

from __future__ import annotations

import asyncio
from time import perf_counter

from backend.core.logging import configure_logging, get_logger
from backend.serving.llm_client import VLLMClient
from config.settings import get_settings

log = get_logger("benchmark_llm")

_PROMPT = [
    {"role": "system", "content": "You are a concise English speaking coach."},
    {"role": "user", "content": "I very like to travel. Ask me one follow-up question."},
]


async def _measure(client: VLLMClient, path: str, runs: int) -> dict | None:
    # warmup
    async for _ in client.chat_stream(_PROMPT, path=path, max_tokens=64):
        pass
    ttfts, totals, toks = [], [], []
    for _ in range(runs):
        t0 = perf_counter()
        first = None
        n = 0
        async for _delta in client.chat_stream(_PROMPT, path=path, max_tokens=64):
            if first is None:
                first = (perf_counter() - t0) * 1000
            n += 1
        total = (perf_counter() - t0) * 1000
        if first is None:
            continue
        ttfts.append(first)
        totals.append(total)
        toks.append(n / (total / 1000) if total else 0)
    if not ttfts:
        return None
    ttfts.sort()
    totals.sort()
    return {
        "ttft_p50": ttfts[len(ttfts) // 2],
        "ttft_p90": ttfts[min(len(ttfts) - 1, int(0.9 * len(ttfts)))],
        "total_p50": totals[len(totals) // 2],
        "toks_per_s": sum(toks) / len(toks),
    }


async def main() -> int:
    settings = get_settings()
    configure_logging(level="WARNING", json_logs=False)
    client = VLLMClient(
        settings.vllm_base_url,
        hot_model=settings.vllm_hot_model,
        cold_model=settings.vllm_cold_model,
        timeout_s=settings.vllm_request_timeout_s,
    )

    print(f"\n=== vLLM LLM benchmark ({settings.vllm_base_url}) ===")
    if not await client.health():
        print(f"vLLM not reachable at {settings.vllm_base_url}.\n")
        print("Start it in WSL2 (Ubuntu), then re-run:")
        print(f"  wsl bash scripts/run_vllm.sh {settings.vllm_hot_model}\n")
        await client.aclose()
        return 1

    runs = 10
    for path, model in (("hot", settings.vllm_hot_model), ("cold", settings.vllm_cold_model)):
        stats = await _measure(client, path, runs)
        if stats is None:
            print(f"{path:>4} {model}: no tokens returned")
            continue
        budget = settings.first_audio_budget_ms
        verdict = "OK" if stats["ttft_p50"] < budget else "> first-audio budget"
        print(
            f"{path:>4} {model:<16} | TTFT p50 {stats['ttft_p50']:.0f}ms "
            f"p90 {stats['ttft_p90']:.0f}ms [{verdict}] | total p50 "
            f"{stats['total_p50']:.0f}ms | {stats['toks_per_s']:.0f} tok/s"
        )

    await client.aclose()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
