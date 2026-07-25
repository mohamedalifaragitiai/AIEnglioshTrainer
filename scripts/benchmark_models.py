"""Benchmark model latency + VRAM on the actual host.

Makes model choices evidence-based: measures per-stage latency against the <300ms
first-audio hot-path budget and the resident VRAM footprint. Only benchmarks what is
actually available/loadable — missing models are reported, not faked. Safe to run
with nothing installed (it will just report availability + the VRAM baseline).

Run:  uv run python scripts/benchmark_models.py
"""

from __future__ import annotations

import asyncio
from time import perf_counter

from backend.core.logging import configure_logging, get_logger
from backend.core.resource_guard import PsutilNvmlSampler, ResourceGuard
from backend.serving.adapters import build_default_registry
from backend.serving.base import ModelStatus
from config.settings import get_settings

log = get_logger("benchmark")


def _vram_used_gb(sampler: PsutilNvmlSampler) -> float | None:
    r = sampler.sample().get("vram")
    if r is None or not sampler.vram_total_bytes:
        return None
    return r * sampler.vram_total_bytes / 1e9


async def main() -> int:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=False)

    sampler = PsutilNvmlSampler(disk_path=str(settings.models_dir))
    guard = ResourceGuard(sampler=sampler, settings=settings)
    guard.feed(sampler.sample())
    registry, llm_client = build_default_registry(guard, settings)

    print("\n=== Model benchmark ===")
    base_vram = _vram_used_gb(sampler)
    base_str = f"{base_vram:.2f} GB" if base_vram is not None else "N/A (no GPU)"
    print(f"VRAM baseline: {base_str}")
    print(f"Budget: {registry.budget()['detail']}\n")

    print(f"{'model':<40} {'kind':>4} {'available':>10} {'load(s)':>8} {'dVRAM(GB)':>10}")
    print("-" * 78)
    for model in registry.models:
        avail = model.available()
        load_s = ""
        dvram = ""
        if avail and settings.load_models:
            before = _vram_used_gb(sampler)
            t0 = perf_counter()
            try:
                await model.load()
                load_s = f"{perf_counter() - t0:.2f}"
                after = _vram_used_gb(sampler)
                if before is not None and after is not None:
                    dvram = f"{after - before:+.2f}"
            except Exception as exc:  # noqa: BLE001
                load_s = "FAIL"
                log.warning("benchmark_load_failed", model=model.name, error=str(exc))
        name = model.name[:39]
        print(f"{name:<40} {str(model.kind):>4} {str(avail):>10} {load_s:>8} {dvram:>10}")

    # LLM latency, if a vLLM server is up.
    print("\nLLM (vLLM) latency vs <300ms hot-path budget:")
    if await llm_client.health():
        msgs = [{"role": "user", "content": "Say 'ready' in one word."}]
        t0 = perf_counter()
        try:
            out = await llm_client.chat(msgs, path="hot", max_tokens=8)
            dt = (perf_counter() - t0) * 1000
            verdict = "OK" if dt < 300 else "OVER BUDGET"
            print(f"  hot 8B round-trip: {dt:.0f} ms  [{verdict}]  reply={out!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  chat failed: {exc}")
    else:
        print(
            f"  vLLM not reachable at {llm_client.base_url} — "
            f"start it to benchmark (see setup_models.py)."
        )

    await registry.unload_all()
    await llm_client.aclose()
    if hasattr(sampler, "shutdown"):
        sampler.shutdown()

    loaded = sum(1 for m in registry.models if m.status == ModelStatus.LOADED)
    hint = (
        "Set COACH_LOAD_MODELS=true after setup_models --download to load."
        if not settings.load_models
        else ""
    )
    print(f"\nLoaded {loaded}/{len(registry.models)} models. {hint}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
