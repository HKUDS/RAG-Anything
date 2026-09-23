"""Chunk-level document updates forward to the LightRAG instance.

A fake LightRAG records the calls, so these tests need no storage, model or
parser, and run against any lightrag-hku, including releases that predate
the chunk-level methods.
"""

import asyncio
from types import SimpleNamespace

import pytest

from raganything import RAGAnything
from raganything.chunk_updates import ChunkUpdateMixin


class FakeLightRAG:
    def __init__(self):
        self.calls = []

    async def aadd_chunks_to_doc(self, doc_id, contents):
        self.calls.append(("add", doc_id, contents))
        return [f"chunk-{i}" for i, _ in enumerate(contents)]

    async def adelete_chunks_from_doc(self, doc_id, chunk_ids, delete_llm_cache=False):
        self.calls.append(("delete", doc_id, chunk_ids, delete_llm_cache))
        return SimpleNamespace(status="success", message="ok")

    async def amodify_chunk_in_doc(
        self, doc_id, old_chunk_id, new_content, delete_llm_cache=False
    ):
        self.calls.append(
            ("modify", doc_id, old_chunk_id, new_content, delete_llm_cache)
        )
        return "chunk-new"


class DummyRAG(ChunkUpdateMixin):
    def __init__(self, lightrag):
        self.lightrag = lightrag

    async def _ensure_lightrag_initialized(self):
        raise AssertionError("chunk updates must not run the parser check")


def test_raganything_exposes_the_chunk_update_methods():
    for name in (
        "aadd_chunks_to_doc",
        "add_chunks_to_doc",
        "adelete_chunks_from_doc",
        "delete_chunks_from_doc",
        "amodify_chunk_in_doc",
        "modify_chunk_in_doc",
    ):
        assert callable(getattr(RAGAnything, name, None)), name


def test_async_methods_forward_arguments_and_results():
    lightrag = FakeLightRAG()
    rag = DummyRAG(lightrag)

    async def run():
        ids = await rag.aadd_chunks_to_doc("doc-1", ["a", "b"])
        deleted = await rag.adelete_chunks_from_doc(
            "doc-1", ["chunk-0"], delete_llm_cache=True
        )
        new_id = await rag.amodify_chunk_in_doc("doc-1", "chunk-1", "c")
        return ids, deleted, new_id

    ids, deleted, new_id = asyncio.run(run())
    assert ids == ["chunk-0", "chunk-1"]
    assert deleted.status == "success"
    assert new_id == "chunk-new"
    assert lightrag.calls == [
        ("add", "doc-1", ["a", "b"]),
        ("delete", "doc-1", ["chunk-0"], True),
        ("modify", "doc-1", "chunk-1", "c", False),
    ]


def test_sync_methods_forward_arguments_and_results():
    lightrag = FakeLightRAG()
    rag = DummyRAG(lightrag)

    assert rag.add_chunks_to_doc("doc-1", ["a"]) == ["chunk-0"]
    assert rag.delete_chunks_from_doc("doc-1", ["chunk-0"]).status == "success"
    assert rag.modify_chunk_in_doc("doc-1", "chunk-0", "b", True) == "chunk-new"
    assert lightrag.calls == [
        ("add", "doc-1", ["a"]),
        ("delete", "doc-1", ["chunk-0"], False),
        ("modify", "doc-1", "chunk-0", "b", True),
    ]


def test_without_a_lightrag_instance_the_call_is_refused():
    rag = DummyRAG(None)
    with pytest.raises(ValueError, match="No LightRAG instance"):
        asyncio.run(rag.adelete_chunks_from_doc("doc-1", ["chunk-0"]))


def test_an_older_lightrag_is_reported_by_method_name():
    rag = DummyRAG(SimpleNamespace())
    with pytest.raises(NotImplementedError, match="LightRAG.aadd_chunks_to_doc"):
        asyncio.run(rag.aadd_chunks_to_doc("doc-1", ["a"]))
