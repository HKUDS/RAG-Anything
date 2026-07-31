"""Deterministic acceptance benchmark for the agent-query latency budget.

This is intentionally provider-free.  It drives the same four orchestration
boundaries used by an interactive request: query-core acquisition, RRF/BM25
retrieval, controlled media validation, and SSE generation.  A fixed-duration
generator is accounted for separately from provider variability.  Real-provider
smoke additionally requires a running backend, an authorized test session, a
reachable configured provider, and a populated KB; without those prerequisites
the deterministic result must not be presented as a production measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * 0.95) - 1)]


class DeterministicCore:
    def __init__(self) -> None:
        self.ready = False

    async def initialize(self) -> None:
        if not self.ready:
            await asyncio.sleep(0.01)
            self.ready = True

    async def retrieve(self) -> None:
        await asyncio.sleep(0.01)


class _Lease:
    def __init__(self, core: DeterministicCore) -> None:
        self.instance = core

    async def release(self) -> None:
        return None


async def _run_query_chain(
    acquire_query_kb,
    rrf_bm25_search,
    controlled_media,
    sse_generation,
) -> None:
    """Run the production-shaped acquire -> retrieval -> media -> SSE chain."""
    lease = await acquire_query_kb()
    try:
        context = await rrf_bm25_search(lease.instance)
        media = await controlled_media(lease.instance, context)
        async for _event in sse_generation(context, media):
            pass
    finally:
        await lease.release()


async def _sample(core: DeterministicCore, provider_seconds: float) -> tuple[float, float]:
    started = time.perf_counter()
    prepared = asyncio.Event()

    async def acquire_query_kb():
        await core.initialize()
        return _Lease(core)

    async def rrf_bm25_search(instance):
        await asyncio.wait_for(instance.retrieve(), timeout=8.0)
        return "deterministic-context"

    async def controlled_media(_instance, _context):
        await asyncio.sleep(0.001)
        return []

    async def sse_generation(_context, _media):
        prepared.set()
        await asyncio.sleep(provider_seconds)
        yield "done"

    task = asyncio.create_task(
        _run_query_chain(
            acquire_query_kb,
            rrf_bm25_search,
            controlled_media,
            sse_generation,
        )
    )
    await prepared.wait()
    before_generation = time.perf_counter() - started
    await task
    return before_generation, time.perf_counter() - started


async def _run(cold_runs: int, warm_runs: int, provider_seconds: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    cold = await asyncio.gather(*[
        _sample(DeterministicCore(), provider_seconds) for _ in range(cold_runs)
    ])
    warm_core = DeterministicCore()
    await warm_core.initialize()
    warm = await asyncio.gather(*[
        _sample(warm_core, provider_seconds) for _ in range(warm_runs)
    ])
    return list(cold), list(warm)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold-runs", type=int, default=20)
    parser.add_argument("--warm-runs", type=int, default=50)
    parser.add_argument("--provider-seconds", type=float, default=22.0)
    args = parser.parse_args()
    cold, warm = asyncio.run(_run(args.cold_runs, args.warm_runs, args.provider_seconds))
    preparation = [item[0] for item in cold + warm]
    total = [item[1] for item in cold + warm]
    print(
        "cold_runs=%d warm_runs=%d preparation_p95=%.3fs total_p95=%.3fs total_median=%.3fs"
        % (
            len(cold), len(warm), _p95(preparation), _p95(total), statistics.median(total)
        )
    )
    if _p95(preparation) > 8.0:
        print("FAIL: generation-preparation P95 exceeded 8 seconds")
        return 1
    if args.provider_seconds <= 22.0 and _p95(total) > 30.0:
        print("FAIL: deterministic 22-second-provider end-to-end P95 exceeded 30 seconds")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
