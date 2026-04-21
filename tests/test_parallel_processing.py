"""Parallel text + multimodal processing tests."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def processor():
    from raganything import RAGAnything, RAGAnythingConfig

    proc = RAGAnything.__new__(RAGAnything)
    proc.config = RAGAnythingConfig()
    proc.logger = MagicMock()
    proc.lightrag = AsyncMock()
    proc._ensure_lightrag_initialized = AsyncMock()
    proc._mark_multimodal_processing_complete = AsyncMock()
    proc.set_content_source_for_context = MagicMock()
    return proc


@pytest.mark.asyncio
async def test_text_and_multimodal_run_concurrently(processor):
    execution_log = []

    async def fake_parse(*args, **kwargs):
        return [
            {"type": "text", "text": "Hello world"},
            {"type": "image", "data": "base64data"},
        ], "doc123"

    async def fake_insert_text(*args, **kwargs):
        execution_log.append(("text_start", asyncio.get_event_loop().time()))
        await asyncio.sleep(0.1)
        execution_log.append(("text_end", asyncio.get_event_loop().time()))

    async def fake_process_multimodal(*args, **kwargs):
        execution_log.append(("mm_start", asyncio.get_event_loop().time()))
        await asyncio.sleep(0.1)
        execution_log.append(("mm_end", asyncio.get_event_loop().time()))

    processor.parse_document = fake_parse
    processor._process_multimodal_content = fake_process_multimodal

    with patch("raganything.processor.separate_content") as mock_sep, \
         patch("raganything.processor.insert_text_content", new=fake_insert_text):
        mock_sep.return_value = ("Hello world", [{"type": "image", "data": "base64data"}])

        await processor.process_document_complete("test.pdf")

    starts = {e[0].replace("_start", ""): e[1] for e in execution_log if "start" in e[0]}
    ends = {e[0].replace("_end", ""): e[1] for e in execution_log if "end" in e[0]}

    assert starts["mm"] < ends["text"], (
        "Multimodal processing should start before text insertion finishes (parallel)"
    )


@pytest.mark.parametrize("failing_branch", ["text", "multimodal"])
@pytest.mark.asyncio
async def test_one_branch_failing_lets_the_other_finish_then_raises(
    processor, failing_branch
):
    survived = False

    async def fake_parse(*args, **kwargs):
        return [
            {"type": "text", "text": "Hello"},
            {"type": "image", "data": "img"},
        ], "doc123"

    async def fake_insert_text(*args, **kwargs):
        nonlocal survived
        if failing_branch == "text":
            raise RuntimeError("Text insertion failed")
        survived = True

    async def fake_process_multimodal(*args, **kwargs):
        nonlocal survived
        if failing_branch == "multimodal":
            raise RuntimeError("Multimodal processing failed")
        survived = True

    processor.parse_document = fake_parse
    processor._process_multimodal_content = fake_process_multimodal
    processor.callback_manager = MagicMock()

    with patch("raganything.processor.separate_content") as mock_sep, \
         patch("raganything.processor.insert_text_content", new=fake_insert_text):
        mock_sep.return_value = ("Hello", [{"type": "image", "data": "img"}])

        with pytest.raises(RuntimeError, match="failed"):
            await processor.process_document_complete("test.pdf")

    assert survived, (
        f"Non-failing branch should still complete when {failing_branch} fails "
        "(gather must not cancel the sibling)"
    )

    dispatched_events = [
        call.args[0] for call in processor.callback_manager.dispatch.call_args_list
    ]
    assert "on_document_error" in dispatched_events, (
        "on_document_error should fire when a branch fails"
    )
    assert "on_document_complete" not in dispatched_events, (
        "on_document_complete must not fire when a branch fails (would silently "
        "report a partially ingested document as successful)"
    )


@pytest.mark.asyncio
async def test_both_branches_failing_raises_and_mentions_both(processor):
    async def fake_parse(*args, **kwargs):
        return [
            {"type": "text", "text": "Hello"},
            {"type": "image", "data": "img"},
        ], "doc123"

    async def fake_insert_text(*args, **kwargs):
        raise RuntimeError("Text boom")

    async def fake_process_multimodal(*args, **kwargs):
        raise RuntimeError("Multimodal boom")

    processor.parse_document = fake_parse
    processor._process_multimodal_content = fake_process_multimodal

    with patch("raganything.processor.separate_content") as mock_sep, \
         patch("raganything.processor.insert_text_content", new=fake_insert_text):
        mock_sep.return_value = ("Hello", [{"type": "image", "data": "img"}])

        with pytest.raises(RuntimeError) as excinfo:
            await processor.process_document_complete("test.pdf")

    message = str(excinfo.value)
    assert "additional failures" in message, (
        "Aggregated error should indicate that more than one branch failed"
    )


@pytest.mark.asyncio
async def test_text_only_document(processor):
    insert_called = False

    async def fake_parse(*args, **kwargs):
        return [{"type": "text", "text": "Hello world"}], "doc123"

    async def fake_insert_text(*args, **kwargs):
        nonlocal insert_called
        insert_called = True

    processor.parse_document = fake_parse

    with patch("raganything.processor.separate_content") as mock_sep, \
         patch("raganything.processor.insert_text_content", new=fake_insert_text):
        mock_sep.return_value = ("Hello world", [])

        await processor.process_document_complete("test.pdf")

    assert insert_called
    processor._mark_multimodal_processing_complete.assert_called_once()


@pytest.mark.asyncio
async def test_multimodal_only_document(processor):
    mm_called = False

    async def fake_parse(*args, **kwargs):
        return [{"type": "image", "data": "img"}], "doc123"

    async def fake_process_multimodal(*args, **kwargs):
        nonlocal mm_called
        mm_called = True

    processor.parse_document = fake_parse
    processor._process_multimodal_content = fake_process_multimodal

    with patch("raganything.processor.separate_content") as mock_sep:
        mock_sep.return_value = ("", [{"type": "image", "data": "img"}])

        await processor.process_document_complete("test.pdf")

    assert mm_called
