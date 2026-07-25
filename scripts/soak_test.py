"""Soak/load test under the 96% ceiling.

Runs the soak harness for a duration and asserts the guard's invariants held under
sustained concurrent pressure. Exits non-zero on any violation, so it can gate CI /
nightly runs.

Run:  uv run python scripts/soak_test.py               # 5s
      uv run python scripts/soak_test.py --seconds 30   # longer soak
"""

from __future__ import annotations

import argparse
import asyncio

from backend.core.logging import configure_logging
from backend.core.soak import run_soak


async def main() -> int:
    parser = argparse.ArgumentParser(description="Soak the ResourceGuard under load.")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--hot", type=int, default=6)
    parser.add_argument("--cold", type=int, default=6)
    args = parser.parse_args()

    configure_logging(level="WARNING", json_logs=False)
    stats = await run_soak(args.seconds, hot_workers=args.hot, cold_workers=args.cold)

    print(f"\n=== Soak ({stats.duration_s:.0f}s, {args.hot} hot + {args.cold} cold workers) ===")
    print(f"  hot turns admitted   : {stats.hot_turns}")
    print(f"  hot BLOCKED          : {stats.hot_blocked}   (must be 0)")
    print(f"  cold processed       : {stats.cold_processed}")
    print(f"  cold deferred        : {stats.cold_deferred}")
    print(f"  peak degradation lvl : {stats.max_degradation}")
    print(f"  errors               : {stats.errors}")

    if stats.healthy():
        print("\nPASSED: hot path never blocked; cold work deferred under pressure; "
              "guard climbed the ladder — the box stays alive under load.\n")
        return 0
    print("\nFAILED:\n  - " + "\n  - ".join(stats.problems()) + "\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
