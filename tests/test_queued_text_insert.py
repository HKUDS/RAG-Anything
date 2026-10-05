"""Text inserted while LightRAG's pipeline is busy must still be indexed.

``ainsert`` only enqueues a document when another insert's pipeline run is
busy; that run processes it later. RAG-Anything used to write its own
statuses (HANDLING, then PROCESSED) right after ``ainsert`` returned, which
took the PENDING document out of LightRAG's queue: the text was never
chunked while doc_status said "processed". The same overwrite hid a FAILED
text insert, so LightRAG never retried it.

The pipeline tests use the real LightRAG pipeline offline; an LLM stub held
on a gate keeps the first run busy deterministically.
"""

import asyncio
import atexit
import json
import types
import uuid
from pathlib import Path

import numpy as np
import pytest
from lightrag.utils import EmbeddingFunc, Tokenizer

from raganything import RAGAnything, RAGAnythingConfig
from raganything.base import DocStatus
from raganything.parser import MineruParser
from raganything.processor import ProcessorMixin


class _ByteTokenizer:
    def encode(self, content):
        return list(content.encode("utf-8"))

    def decode(self, tokens):
        return bytes(tokens).decode("utf-8", errors="replace")


def _gated_llm():
    """An LLM stub that blocks every call until the gate opens and can be
    switched to fail. A plain function, not an object holding the events:
    LightRAG deep-copies its config (``asdict``), and copying an Event that
    has waiters fails while functions are copied by reference."""
    state = types.SimpleNamespace(
        gate=asyncio.Event(), called=asyncio.Event(), fail=False, fail_on=None
    )

    async def llm(prompt, system_prompt=None, history_messages=None, **kwargs):
        state.called.set()
        if state.fail_on and state.fail_on in prompt:
            raise RuntimeError("LLM unavailable")
        await state.gate.wait()
        if state.fail:
            raise RuntimeError("LLM unavailable")
        return ""

    return llm, state


async def _constant_embeddings(texts):
    return np.ones((len(texts), 8), dtype=np.float32)


@pytest.fixture
def make_rag(monkeypatch, tmp_path):
    monkeypatch.setattr(MineruParser, "check_installation", lambda self: True)

    def build(llm):
        config = RAGAnythingConfig(
            working_dir=str(tmp_path / uuid.uuid4().hex), display_content_stats=False
        )
        return RAGAnything(
            config=config,
            llm_model_func=llm,
            embedding_func=EmbeddingFunc(
                embedding_dim=8, max_token_size=8192, func=_constant_embeddings
            ),
            lightrag_kwargs={
                "tokenizer": Tokenizer("bytes", _ByteTokenizer()),
                "chunk_token_size": 64,
                "chunk_overlap_token_size": 8,
                # shared storage is keyed by workspace, not working_dir
                "workspace": f"q{uuid.uuid4().hex[:8]}",
            },
        )

    return build


async def _close(rag, state):
    state.gate.set()  # nothing may still be waiting on the stub
    await rag.finalize_storages()
    atexit.unregister(rag.close)
    workers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in workers:
        task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)


def _kv(rag, name):
    path = next(Path(rag.config.working_dir).glob(f"**/kv_store_{name}.json"), None)
    return json.loads(path.read_text(encoding="utf-8")) if path else {}


def _content(name, pages=2):
    return [
        {
            "type": "text",
            "text": f"{name} page {page}: findings that only {name} reports.",
            "page_idx": page,
        }
        for page in range(pages)
    ]


def _chunks_of(rag, doc_id):
    return [
        row
        for row in _kv(rag, "text_chunks").values()
        if row.get("full_doc_id") == doc_id
    ]


@pytest.mark.asyncio
async def test_insert_queued_behind_a_busy_pipeline_is_indexed(make_rag):
    llm, state = _gated_llm()
    rag = make_rag(llm)
    try:
        first = asyncio.create_task(
            rag.insert_content_list(
                _content("Alpha"), file_path="a.pdf", doc_id="doc-a"
            )
        )
        await asyncio.wait_for(state.called.wait(), 10)  # first run is now busy
        queued = [
            asyncio.create_task(
                rag.insert_content_list(
                    _content(name), file_path=f"{name}.pdf", doc_id=f"doc-{name}"
                )
            )
            for name in ("Bravo", "Charlie", "Delta")
        ]
        await asyncio.sleep(0.5)
        # Each queued insert waits for its text instead of returning early.
        assert not any(task.done() for task in queued)
        state.gate.set()
        await asyncio.wait_for(asyncio.gather(first, *queued), 60)
    finally:
        await _close(rag, state)

    status = _kv(rag, "doc_status")
    for doc_id in ("doc-a", "doc-Bravo", "doc-Charlie", "doc-Delta"):
        chunks = _chunks_of(rag, doc_id)
        assert chunks, f"text of {doc_id} was never indexed"
        assert status[doc_id]["status"] == DocStatus.PROCESSED
        assert status[doc_id]["chunks_count"] == len(chunks)
        # the wait also lets the queued document get its pages (#330)
        assert all("page_idx" in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_failed_text_insert_is_reported_and_retried_later(make_rag):
    llm, state = _gated_llm()
    state.gate.set()
    state.fail = True
    rag = make_rag(llm)
    try:
        with pytest.raises(RuntimeError, match="LightRAG failed"):
            await rag.insert_content_list(
                _content("Alpha"), file_path="a.pdf", doc_id="doc-a"
            )
        # LightRAG's FAILED is kept, so its next pipeline run retries it.
        assert (await rag.lightrag.doc_status.get_by_id("doc-a"))[
            "status"
        ] == DocStatus.FAILED

        state.fail = False
        await rag.insert_content_list(
            _content("Bravo"), file_path="b.pdf", doc_id="doc-b"
        )
    finally:
        await _close(rag, state)

    status = _kv(rag, "doc_status")
    for doc_id in ("doc-a", "doc-b"):
        assert status[doc_id]["status"] == DocStatus.PROCESSED
        assert _chunks_of(rag, doc_id)


@pytest.mark.asyncio
async def test_process_document_complete_marks_failed_text_failed(
    make_rag, monkeypatch
):
    llm, state = _gated_llm()
    state.gate.set()
    state.fail = True
    rag = make_rag(llm)

    async def parse_document(file_path, *args, **kwargs):
        return _content("Alpha"), "doc-a"

    monkeypatch.setattr(rag, "parse_document", parse_document)
    try:
        with pytest.raises(RuntimeError, match="LightRAG failed"):
            await rag.process_document_complete("/in/a.pdf")
        record = await rag.lightrag.doc_status.get_by_id("doc-a")
    finally:
        await _close(rag, state)

    assert record["status"] == DocStatus.FAILED
    assert "LLM unavailable" in record["error_msg"]


@pytest.mark.asyncio
async def test_text_failing_while_the_run_is_busy_is_retried_by_it(make_rag):
    """A document whose text fails while its pipeline run is still busy with
    another one is retried by that run (it was asked to come back), so the
    caller waits for the retry instead of raising on the first FAILED."""
    llm, state = _gated_llm()
    state.fail_on = "Xray"
    rag = make_rag(llm)
    try:
        await rag._ensure_lightrag_initialized()
        inserts = [
            asyncio.create_task(
                rag.insert_content_list(
                    _content(name), file_path=f"{name}.pdf", doc_id=f"doc-{name}"
                )
            )
            for name in ("Alpha", "Xray")
        ]

        async def xray_failed():
            while True:
                record = await rag.lightrag.doc_status.get_by_id("doc-Xray")
                if record and record.get("status") == DocStatus.FAILED:
                    return
                await asyncio.sleep(0.05)

        await asyncio.wait_for(xray_failed(), 10)  # Alpha still holds the run
        state.fail_on = None
        await asyncio.sleep(0.5)
        assert not any(task.done() for task in inserts)
        state.gate.set()
        await asyncio.wait_for(asyncio.gather(*inserts), 60)
    finally:
        await _close(rag, state)

    status = _kv(rag, "doc_status")
    for doc_id in ("doc-Alpha", "doc-Xray"):
        assert status[doc_id]["status"] == DocStatus.PROCESSED
        assert _chunks_of(rag, doc_id)


@pytest.mark.asyncio
async def test_failure_before_the_text_insert_does_not_block_the_document(
    make_rag, monkeypatch
):
    """A parse failure leaves a FAILED record without stored text; LightRAG
    would drop every later insert of that doc_id and never retry it."""
    llm, state = _gated_llm()
    state.gate.set()
    rag = make_rag(llm)
    attempts = []

    async def parse_document(file_path, *args, **kwargs):
        attempts.append(file_path)
        if len(attempts) == 1:
            raise RuntimeError("MinerU timed out")
        return _content("Alpha"), "content-based-id"

    monkeypatch.setattr(rag, "parse_document", parse_document)
    try:
        with pytest.raises(RuntimeError, match="MinerU timed out"):
            await rag.process_document_complete("/in/report.pdf", doc_id="report")
        failed = await rag.lightrag.doc_status.get_by_id("report")
        await rag.process_document_complete("/in/report.pdf", doc_id="report")
    finally:
        await _close(rag, state)

    assert failed["status"] == DocStatus.FAILED
    assert _kv(rag, "doc_status")["report"]["status"] == DocStatus.PROCESSED
    assert _chunks_of(rag, "report")


# --------------------------------------------------------------------------
# the wait itself, against a scripted doc_status and pipeline status
# --------------------------------------------------------------------------


class _ScriptedLightRAG:
    """Each doc_status read returns the next scripted (status, busy) step and
    sets the pipeline's busy flag to match; the last step repeats."""

    def __init__(self, steps, error="boom", history=()):
        self.steps = list(steps)
        self.error = error
        self.kicks = 0
        self.pipeline = {"busy": False, "history_messages": list(history)}
        self.doc_status = types.SimpleNamespace(get_by_id=self._get)

    async def _get(self, doc_id):
        status, busy = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        self.pipeline["busy"] = busy
        return None if status is None else {"status": status, "error_msg": self.error}

    async def apipeline_process_enqueue_documents(self, *args):
        self.kicks += 1


def _processor(lightrag):
    processor = ProcessorMixin()
    processor.lightrag = lightrag
    processor.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: None,
    )

    async def pipeline_status():
        return lightrag.pipeline

    processor._lightrag_pipeline_status = pipeline_status
    return processor


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return slept


@pytest.mark.parametrize("status", ["processed", "handling", None])
@pytest.mark.asyncio
async def test_finished_or_unknown_text_does_not_wait(status, no_sleep):
    lightrag = _ScriptedLightRAG([(status, False)])

    await _processor(lightrag)._wait_for_text_processing("doc-1", None, False)

    assert lightrag.kicks == 0 and no_sleep == []


@pytest.mark.asyncio
async def test_busy_pipeline_is_polled_not_nudged(no_sleep):
    """ainsert already asked the busy run to come back for the document."""
    lightrag = _ScriptedLightRAG(
        [
            ("pending", True),
            ("pending", True),
            ("processing", True),
            ("processed", False),
        ]
    )

    await _processor(lightrag)._wait_for_text_processing("doc-1", None, False)

    assert lightrag.kicks == 0
    assert no_sleep == [0.2, 0.4, 0.8]


@pytest.mark.asyncio
async def test_idle_pipeline_with_the_document_queued_is_run(no_sleep):
    """A run that ended without reaching the document leaves it PENDING."""
    lightrag = _ScriptedLightRAG([("pending", False), ("processed", False)])

    await _processor(lightrag)._wait_for_text_processing("doc-1", None, False)

    assert lightrag.kicks == 1 and no_sleep == []


@pytest.mark.asyncio
async def test_failed_text_a_busy_run_will_retry_is_waited_for(no_sleep):
    lightrag = _ScriptedLightRAG([("failed", True), ("processed", False)])

    await _processor(lightrag)._wait_for_text_processing("doc-1", None, False)

    assert no_sleep == [0.2]


@pytest.mark.asyncio
async def test_failed_text_raises_with_lightrags_error(no_sleep):
    lightrag = _ScriptedLightRAG([("failed", False)])

    with pytest.raises(RuntimeError, match="doc-1: boom"):
        await _processor(lightrag)._wait_for_text_processing("doc-1", None, False)


@pytest.mark.asyncio
async def test_repeated_failures_do_not_nest_the_message(no_sleep):
    error = "LightRAG failed to process the text of doc-1: boom"
    lightrag = _ScriptedLightRAG([("failed", False)], error=error)

    with pytest.raises(RuntimeError) as raised:
        await _processor(lightrag)._wait_for_text_processing("doc-1", None, False)

    assert str(raised.value) == error


@pytest.mark.asyncio
async def test_cancelled_pipeline_is_not_restarted(no_sleep):
    lightrag = _ScriptedLightRAG(
        [("pending", False)], history=["Pipeline cancelled by user"]
    )

    with pytest.raises(RuntimeError, match="cancelled"):
        await _processor(lightrag)._wait_for_text_processing("doc-1", None, False)

    assert lightrag.kicks == 0


@pytest.mark.asyncio
async def test_long_wait_is_reported(no_sleep, monkeypatch):
    """A pipeline that never gets to the document (e.g. a busy flag left by a
    dead process) must not look like a silent hang."""
    clock = iter(range(0, 10_000, 200))
    monkeypatch.setattr("raganything.processor.time.monotonic", lambda: next(clock))
    warnings = []
    lightrag = _ScriptedLightRAG([("pending", True)] * 8 + [("processed", False)])
    processor = _processor(lightrag)
    processor.logger.warning = lambda message: warnings.append(message)

    await processor._wait_for_text_processing("doc-1", None, False)

    assert warnings and "doc-1" in warnings[0]
