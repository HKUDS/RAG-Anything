"""Document context must stay local while shared processors run concurrently."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from raganything.base import DocStatus
from raganything.modalprocessors import (
    ContextConfig,
    ContextExtractor,
    TableModalProcessor,
)
from raganything.processor import ProcessorMixin
from raganything.raganything import RAGAnything


class Storage:
    def __init__(self):
        self.records = {}

    async def get_by_id(self, key):
        return self.records.get(key)

    async def upsert(self, records):
        self.records.update(records)

    async def index_done_callback(self):
        pass


class Processor(ProcessorMixin):
    set_content_source_for_context = RAGAnything.set_content_source_for_context


def content(label):
    return [
        {"type": "text", "text": f"Only document {label} context.", "page_idx": 0},
        {"type": "table", "table_body": f"Table {label}", "page_idx": 0},
    ]


@pytest.fixture
def processor(monkeypatch):
    p = Processor()
    p.logger = logging.getLogger(__name__)
    p.config = SimpleNamespace(
        use_full_path=False,
        display_content_stats=False,
        parser_output_dir="unused",
        parse_method="auto",
        content_format="minerU",
    )
    p.lightrag = SimpleNamespace(
        doc_status=Storage(), full_docs=Storage(), max_parallel_insert=2
    )
    p._ensure_lightrag_initialized = AsyncMock(return_value={"success": True})
    p._wait_for_text_processing = AsyncMock()
    p._annotate_text_chunk_pages = AsyncMock()
    p.multimodal_status_cache = Storage()
    p._convert_to_lightrag_chunks_type_aware = Mock(return_value={"modal": {}})
    for name in (
        "_store_chunks_to_lightrag_storage_type_aware",
        "_store_multimodal_main_entities",
        "_batch_extract_entities_lightrag_style_type_aware",
        "_batch_add_belongs_to_relations_type_aware",
        "_batch_merge_lightrag_style_type_aware",
        "_update_doc_status_with_chunks_type_aware",
    ):
        setattr(p, name, AsyncMock(return_value=[]))

    # Instantiate the real table processor without external storage connections.
    modal = TableModalProcessor.__new__(TableModalProcessor)
    modal.content_source = None
    modal.content_format = "auto"
    modal.context_extractor = ContextExtractor()
    p.prompts = []

    async def caption(prompt, **kwargs):
        p.prompts.append(prompt)
        return json.dumps(
            {
                "detailed_description": "Table analysis",
                "entity_info": {
                    "entity_name": "Table",
                    "entity_type": "table",
                    "summary": "Table summary",
                },
            }
        )

    modal.modal_caption_func = caption
    p.modal_processors = {"table": modal}
    p.entered = asyncio.Event()
    p.release = asyncio.Event()
    p.fail_insert = False

    async def ainsert(input, ids, multimodal_content=None, **kwargs):
        if ids == "doc-A":
            p.entered.set()
            await p.release.wait()
        if p.fail_insert:
            raise RuntimeError("text insert failed")
        await p.lightrag.doc_status.upsert(
            {ids: {"status": DocStatus.PROCESSED, "chunks_count": 1}}
        )
        p.lightrag.full_docs.records[ids] = {"content": input}
        # Legacy LightRAG API delegates modality work to ainsert.
        for item in multimodal_content or []:
            await modal.generate_chunk_sections(
                item, "table", {"page_idx": 0, "index": 1}
            )
        return "track"

    p.lightrag.ainsert = ainsert

    async def parse(file_path, *args, **kwargs):
        label = "A" if file_path == "A.pdf" else "B"
        return content(label), f"doc-{label}"

    p.parse_document = parse
    shared = {"history_messages": []}
    monkeypatch.setattr(
        "lightrag.kg.shared_storage.get_namespace_data",
        AsyncMock(return_value=shared),
    )
    monkeypatch.setattr(
        "lightrag.kg.shared_storage.get_pipeline_status_lock", lambda: asyncio.Lock()
    )
    return p


async def insert(p, entry, label):
    if entry == "content_list":
        return await p.insert_content_list(content(label), doc_id=f"doc-{label}")
    elif entry == "document":
        return await p.process_document_complete(f"{label}.pdf")
    else:
        return await p.process_document_complete_lightrag_api(f"{label}.pdf")


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["content_list", "document", "lightrag_api"])
@pytest.mark.parametrize("mode", ["page", "chunk"])
async def test_overlapping_documents_keep_their_own_table_prompt(
    processor, entry, mode
):
    p = processor
    modal = p.modal_processors["table"]
    modal.context_extractor = ContextExtractor(ContextConfig(context_mode=mode))
    direct_source = content("direct")
    modal.set_content_source(direct_source, "minerU")
    task_a = asyncio.create_task(insert(p, entry, "A"))
    try:
        await asyncio.wait_for(p.entered.wait(), 2)
        # B must finish while A is blocked: the fix must retain concurrency.
        await asyncio.wait_for(insert(p, entry, "B"), 2)
        p.release.set()
        await asyncio.wait_for(task_a, 2)
    finally:
        p.release.set()
        task_a.cancel()
        await asyncio.gather(task_a, return_exceptions=True)
    assert len(p.prompts) == 2
    for label in ("A", "B"):
        prompt = next(x for x in p.prompts if f"Body: Table {label}\n" in x)
        assert f"Only document {label} context." in prompt
        other = "B" if label == "A" else "A"
        assert f"Only document {other} context." not in prompt
    assert modal.content_source is direct_source
    assert (
        modal._get_context_for_item({"page_idx": 0, "index": 1})
        == "Only document direct context."
    )


@pytest.mark.asyncio
async def test_individual_fallback_keeps_operation_context(processor):
    p = processor
    p._process_multimodal_content_batch_type_aware = AsyncMock(
        side_effect=RuntimeError("batch storage unavailable")
    )
    modal = p.modal_processors["table"]

    async def process_item(modal_content, item_info, **kwargs):
        sections = await modal.generate_chunk_sections(
            modal_content, "table", item_info
        )
        return sections[0]["description"], sections[0]["entity_info"], []

    modal.process_multimodal_content = process_item
    task_a = asyncio.create_task(insert(p, "document", "A"))
    try:
        await asyncio.wait_for(p.entered.wait(), 2)
        await asyncio.wait_for(insert(p, "document", "B"), 2)
        p.release.set()
        await asyncio.wait_for(task_a, 2)
    finally:
        p.release.set()
        task_a.cancel()
        await asyncio.gather(task_a, return_exceptions=True)
    prompt_a = next(x for x in p.prompts if "Body: Table A\n" in x)
    assert "Only document A context." in prompt_a
    assert "Only document B context." not in prompt_a


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["content_list", "document", "lightrag_api"])
@pytest.mark.parametrize("failure", ["cancel", "exception"])
async def test_failed_operation_does_not_replace_direct_processor_context(
    processor, entry, failure
):
    p = processor
    modal = p.modal_processors["table"]
    direct_source = content("direct")
    modal.set_content_source(direct_source, "minerU")
    task = asyncio.create_task(insert(p, entry, "A"))
    await asyncio.wait_for(p.entered.wait(), 2)
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        p.fail_insert = True
        p.release.set()
        if entry == "lightrag_api":
            # This public API intentionally returns False instead of raising.
            assert await task is False
        else:
            with pytest.raises(RuntimeError, match="text insert failed"):
                await task
    assert modal.content_source is direct_source
    assert (
        modal._get_context_for_item({"page_idx": 0, "index": 1})
        == "Only document direct context."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_scope_is_restored_when_failure_is_caught_in_the_same_task(
    processor, failure
):
    p = processor
    modal = p.modal_processors["table"]
    p.lightrag.ainsert = AsyncMock(side_effect=failure("aborted insert"))
    with pytest.raises(failure):
        await p.insert_content_list(content("A"), doc_id="doc-A")
    # A setter after the failed await must have its usual direct-use behavior.
    source = content("after failure")
    modal.set_content_source(source, "minerU")
    assert modal.content_source is source
    assert (
        modal._get_context_for_item({"page_idx": 0, "index": 1})
        == "Only document after failure context."
    )


@pytest.mark.asyncio
async def test_child_context_setter_preserves_parent_source_and_format(processor):
    p = processor
    modal = p.modal_processors["table"]
    p.release.set()

    async def extract(chunks):
        async def child():
            modal.set_content_source("Child context.", "text")
            return modal._get_context_for_item({"page_idx": 0, "index": 0})

        assert await asyncio.create_task(child()) == "Child context."
        assert (
            modal._get_context_for_item({"page_idx": 0, "index": 1})
            == "Only document A context."
        )
        return []

    p._batch_extract_entities_lightrag_style_type_aware = extract
    await p.insert_content_list(content("A"), doc_id="doc-A")
