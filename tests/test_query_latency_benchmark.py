import pytest

from scripts.benchmark_agent_query_latency import _p95, _run, _run_query_chain


@pytest.mark.asyncio
async def test_deterministic_benchmark_keeps_generation_preparation_bounded():
    cold, warm = await _run(20, 50, 0.001)
    assert _p95([sample[0] for sample in cold + warm]) <= 8.0
    assert _p95([sample[1] for sample in cold + warm]) < 1.0


@pytest.mark.asyncio
async def test_benchmark_drives_acquire_rrf_media_and_sse_boundaries():
    events = []

    class Lease:
        instance = object()

        async def release(self):
            events.append("release")

    async def acquire():
        events.append("acquire")
        return Lease()

    async def rrf(instance):
        assert instance is Lease.instance
        events.append("rrf-bm25")
        return "context"

    async def media(instance, context):
        assert instance is Lease.instance
        assert context == "context"
        events.append("media")
        return []

    async def sse(context, media_payload):
        assert context == "context"
        assert media_payload == []
        events.append("sse")
        yield "done"

    await _run_query_chain(acquire, rrf, media, sse)
    assert events == ["acquire", "rrf-bm25", "media", "sse", "release"]
