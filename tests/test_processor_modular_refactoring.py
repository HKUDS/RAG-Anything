from pathlib import Path
from unittest.mock import MagicMock

from raganything import RAGAnything
from raganything.processor import (
    AUDIO_FILE_EXTENSIONS,
    VIDEO_FILE_EXTENSIONS,
    ProcessorMixin,
    _is_lightrag_token_chunker,
)
from raganything.processor_cache import ProcessorCacheMixin
from raganything.processor_deletion import DocumentDeletionMixin
from raganything.processor_multimodal import MultimodalIngestMixin
from raganything.processor_status import DocumentStatusSyncMixin


def test_processor_mixin_inheritance_and_mro():
    """Verify ProcessorMixin inherits from all four modular mixins in consistent MRO order."""
    assert issubclass(ProcessorMixin, ProcessorCacheMixin)
    assert issubclass(ProcessorMixin, DocumentStatusSyncMixin)
    assert issubclass(ProcessorMixin, MultimodalIngestMixin)
    assert issubclass(ProcessorMixin, DocumentDeletionMixin)

    mro_names = [cls.__name__ for cls in ProcessorMixin.__mro__]
    assert "ProcessorCacheMixin" in mro_names
    assert "DocumentStatusSyncMixin" in mro_names
    assert "MultimodalIngestMixin" in mro_names
    assert "DocumentDeletionMixin" in mro_names


def test_raganything_inherits_all_mixins():
    """Verify top-level RAGAnything class retains all processor mixin methods and attributes."""
    assert issubclass(RAGAnything, ProcessorMixin)
    assert issubclass(RAGAnything, ProcessorCacheMixin)
    assert issubclass(RAGAnything, DocumentStatusSyncMixin)
    assert issubclass(RAGAnything, MultimodalIngestMixin)
    assert issubclass(RAGAnything, DocumentDeletionMixin)


def test_expected_methods_present_on_processor_mixin():
    """Ensure all 51 core methods and attributes remain callable on ProcessorMixin."""
    expected_cache_methods = [
        "_relevant_parser_kwargs",
        "_file_content_fingerprint",
        "_get_file_reference",
        "_generate_cache_key",
        "_generate_content_based_doc_id",
        "_get_cached_result",
        "_compute_parsed_output_dirs",
        "_record_parsed_output_location",
        "_store_cached_result",
    ]
    for method in expected_cache_methods:
        assert hasattr(ProcessorMixin, method), f"Missing cache method: {method}"
        assert hasattr(ProcessorCacheMixin, method)

    expected_status_methods = [
        "_LEGACY_DOC_STATUS_FIELDS",
        "_current_doc_status_timestamp",
        "_ensure_doc_status_record",
        "_drop_placeholder_doc_status",
        "_lightrag_pipeline_status",
        "_wait_for_text_processing",
        "_annotate_text_chunk_pages",
        "_text_chunk_page_labels",
        "_doc_status_supports_multimodal_processed",
        "_sanitize_doc_status_record",
        "_upsert_doc_status",
        "_get_multimodal_status_record",
        "_set_multimodal_status_record",
        "_get_multimodal_processed_flag",
        "_mark_multimodal_processing_complete",
        "is_document_fully_processed",
        "get_document_processing_status",
    ]
    for method in expected_status_methods:
        assert hasattr(ProcessorMixin, method), f"Missing status method: {method}"
        assert hasattr(DocumentStatusSyncMixin, method)

    expected_deletion_methods = [
        "_resolve_parsed_output_dirs_for_deletion",
        "adelete_by_doc_id",
    ]
    for method in expected_deletion_methods:
        assert hasattr(ProcessorMixin, method), f"Missing deletion method: {method}"
        assert hasattr(DocumentDeletionMixin, method)

    expected_multimodal_methods = [
        "_process_multimodal_content",
        "_process_multimodal_content_individual",
        "_modal_description_only_text",
        "_chunk_token_budget_for_extraction",
        "_count_tokens_for_extraction",
        "_build_multimodal_extraction_chunks",
        "_convert_to_lightrag_chunks_type_aware",
        "_format_window_part",
        "_apply_chunk_template",
        "_store_chunks_to_lightrag_storage_type_aware",
        "_store_multimodal_main_entities",
        "_batch_extract_entities_lightrag_style_type_aware",
        "_batch_add_belongs_to_relations_type_aware",
        "_batch_merge_lightrag_style_type_aware",
        "_update_doc_status_with_chunks_type_aware",
    ]
    for method in expected_multimodal_methods:
        assert hasattr(ProcessorMixin, method), f"Missing multimodal method: {method}"
        assert hasattr(MultimodalIngestMixin, method)

    # Core batch processing and full entity merge methods are preserved on ProcessorMixin
    assert hasattr(ProcessorMixin, "_process_multimodal_content_batch_type_aware")
    assert hasattr(ProcessorMixin, "_store_multimodal_entities_to_full_entities")

    expected_orchestrator_methods = [
        "parse_document",
        "process_document_complete",
        "process_document_complete_lightrag_api",
        "insert_content_list",
        "process_preprocessed_output",
        "process_preprocessed_directory",
    ]
    for method in expected_orchestrator_methods:
        assert hasattr(ProcessorMixin, method), f"Missing orchestrator method: {method}"


def test_backward_compatibility_constants_and_helpers():
    """Verify package constants and helpers exported from raganything.processor."""
    assert isinstance(AUDIO_FILE_EXTENSIONS, frozenset)
    assert ".mp3" in AUDIO_FILE_EXTENSIONS
    assert isinstance(VIDEO_FILE_EXTENSIONS, frozenset)
    assert ".mp4" in VIDEO_FILE_EXTENSIONS
    assert callable(_is_lightrag_token_chunker)


def test_cache_mixin_standalone(tmp_path):
    """Verify ProcessorCacheMixin can be instantiated and utilized independently."""

    class DummyCacheHost(ProcessorCacheMixin):
        def __init__(self):
            self.config = MagicMock(use_full_path=False)

    host = DummyCacheHost()
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("hello test")

    fp = host._file_content_fingerprint(sample_file)
    assert isinstance(fp, str)
    assert len(fp) == 64

    ref = host._get_file_reference(str(sample_file))
    assert ref == "sample.txt"


def test_processor_mixin_line_count_is_modular():
    """Verify that processor.py is cleanly decomposed from ~3850 lines to under 1600 lines."""
    processor_path = (
        Path(__file__).resolve().parents[1] / "raganything" / "processor.py"
    )
    with open(processor_path) as f:
        lines = f.readlines()
    assert len(lines) < 1600, f"Expected processor.py < 1600 lines, got {len(lines)}"
