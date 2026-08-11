from types import SimpleNamespace
import logging

import pytest

from raganything.autorepair.agent.source_tracer import SourceTracer
from raganything.citation_parser import extract_citations
from raganything.processor.chunk_processor import ChunkProcessorMixin
from raganything.hybrid_search import ScoredChunk
from raganything.query.pipeline import QueryMixin
from raganything.utils import display_document_name, normalize_citation_document_names


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0fb7375fdfa54875b2ed60d479aed21a_battery.mp4", "battery.mp4"),
        ("a1b2c3d4_manual.pdf", "manual.pdf"),
        (r"C:\uploads\DEADBEEF_report.docx", "report.docx"),
        ("/srv/uploads/normal_file.pdf", "normal_file.pdf"),
        ("abcdefg_short-prefix.pdf", "abcdefg_short-prefix.pdf"),
    ],
)
def test_display_document_name_removes_only_known_staged_prefixes(value, expected):
    assert display_document_name(value) == expected


def test_citation_label_normalization_does_not_rewrite_body_text():
    prefix = "0fb7375fdfa54875b2ed60d479aed21a"
    answer = f"Body keeps {prefix}_battery.mp4 unchanged. [\u6765\u6e90 {prefix}_battery.mp4]"

    normalized = normalize_citation_document_names(answer)

    assert f"Body keeps {prefix}_battery.mp4" in normalized
    assert "[\u6765\u6e90 battery.mp4]" in normalized


def test_chunk_source_cache_keeps_raw_path_and_clean_display_name():
    processor = object.__new__(ChunkProcessorMixin)
    processor.config = SimpleNamespace(use_full_path=True)
    stored_path = r"C:\uploads\0fb7375fdfa54875b2ed60d479aed21a_battery.mp4"

    processor._register_chunk_sources("doc-1", stored_path, ["chunk-1"])

    assert processor._chunk_source_cache["chunk-1"] == {
        "file_path": stored_path,
        "document_name": "battery.mp4",
    }


def test_structured_citations_clean_document_name_but_keep_file_path():
    prefix = "0fb7375fdfa54875b2ed60d479aed21a"
    raw_path = f"/uploads/{prefix}_battery.mp4"
    result = extract_citations(
        "[\u6765\u6e90 1]",
        source_docs=[{"document_name": f"{prefix}_battery.mp4", "file_path": raw_path}],
    )

    citation = result["sources"][0]
    assert citation["document_name"] == "battery.mp4"
    assert citation["file_path"] == raw_path


def test_v5_citation_matches_clean_name_and_keeps_file_path():
    prefix = "0fb7375fdfa54875b2ed60d479aed21a"
    raw_path = f"/uploads/{prefix}_battery.mp4"
    result = extract_citations(
        "\U0001f4da \u53c2\u8003\u6765\u6e90\n"
        f"[\u6765\u6e90 {prefix}_battery.mp4] \u2014 \"excerpt\"",
        source_docs=[{"title": f"{prefix}_battery.mp4", "file_path": raw_path}],
    )

    citation = result["sources"][0]
    assert citation["document_name"] == "battery.mp4"
    assert citation["file_path"] == raw_path


def test_autorepair_source_title_matches_clean_v5_citation_name():
    prefix = "0fb7375fdfa54875b2ed60d479aed21a"
    result = SourceTracer().extract_citations(
        f"[\u6765\u6e90 {prefix}_battery.mp4]",
        [{"id": "doc-1", "title": f"{prefix}_battery.mp4", "content": "excerpt"}],
    )

    assert result[0]["source_title"] == "battery.mp4"


@pytest.mark.asyncio
async def test_rrf_context_uses_clean_document_name_for_legacy_chunk_metadata():
    class Engine:
        _lightrag = SimpleNamespace(chunk_entity_relation_graph=None)

        async def search(self, *_args, **_kwargs):
            return [ScoredChunk(
                "chunk-1", "context", 1.0, ["vector"],
                document_name="0fb7375fdfa54875b2ed60d479aed21a_battery.mp4",
            )]

    query = object.__new__(QueryMixin)
    query.hybrid_search_engine = Engine()
    query.callback_manager = None
    query.logger = logging.getLogger("test.document-display-names")

    async def source_info(_chunk_ids):
        return {}

    query.batch_get_doc_source_info_async = source_info
    context = await query._aquery_rrf("query", only_need_context=True)

    assert "battery.mp4" in context
    assert "0fb7375fdfa54875b2ed60d479aed21a" not in context


@pytest.mark.asyncio
async def test_graph_context_uses_clean_document_name_for_legacy_chunk_metadata():
    class GraphRetriever:
        _lightrag = SimpleNamespace(chunk_entity_relation_graph=None)

        async def search_with_paths(self, *_args, **_kwargs):
            return {
                "matched_entities": [{"name": "battery", "type": "equipment", "degree": 1}],
                "results": [{
                    "chunk": ScoredChunk(
                        "chunk-1", "context", 1.0, ["graph"],
                        document_name="0fb7375fdfa54875b2ed60d479aed21a_battery.mp4",
                    ),
                    "paths": [],
                }],
                "graph_stats": {"total_entities": 1, "traversal_depth": 1},
            }

    query = object.__new__(QueryMixin)
    query.hybrid_search_engine = SimpleNamespace(graph_retriever=GraphRetriever())

    async def source_info(_chunk_ids):
        return {}

    query.batch_get_doc_source_info_async = source_info
    context = await query._aquery_graph("query", only_need_context=True)

    assert "battery.mp4" in context
    assert "0fb7375fdfa54875b2ed60d479aed21a" not in context
