"""Sidecar-backed text insertion: page provenance for text chunks (#330).

``separate_content`` joins every text block into one string before LightRAG
chunks it, so MinerU's per-block ``page_idx`` never reaches text chunks —
page-anchored citations, reader jump-to-page and page-based figure
association are unbuildable for exactly the chunks that carry the bulk of a
document.

LightRAG already ships the machinery that preserves this: parser adapters
emit an IR whose blocks carry positions, ``write_sidecar`` persists it as a
``*.parsed/`` directory, and the paragraph-semantic ("P") chunker records
each chunk's source blocks as ``sidecar.refs`` — joinable back to page
numbers and bounding boxes. Documents parsed by RAG-Anything bypass all of
it because they are inserted as one raw string.

This module routes RAG-Anything's own MinerU parse through that pipeline:

    content_list (text blocks only)
      → MinerUIRBuilder.normalize_from_workdir   (LightRAG's own adapter)
      → write_sidecar                            (LightRAG's own writer)
      → apipeline_enqueue_documents(process_options="P")
      → full_docs row marked parse_format="lightrag" + sidecar_location
      → pipeline dispatches by format to ReuseParser
      → P chunker consumes blocks.jsonl → chunks carry sidecar.refs

Multimodal items (images/tables/equations) are excluded from the IR: the
modal processors own them, exactly as on the plain-insertion path, and their
chunks already carry ``page_idx`` one-to-one.

Requires a lightrag-hku build with the sidecar subsystem; callers check
:func:`sidecar_available` and fall back to plain insertion otherwise.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from lightrag.utils import logger


def sidecar_available() -> bool:
    """True when the installed lightrag build ships the sidecar pipeline."""
    try:
        from lightrag.parser.external.mineru.ir_builder import (  # noqa: F401
            MinerUIRBuilder,
        )
        from lightrag.sidecar.writer import write_sidecar  # noqa: F401
        from lightrag.utils_pipeline import (  # noqa: F401
            make_lightrag_doc_content,
            sidecar_uri_for,
        )
    except ImportError:
        return False
    return True


def text_only_content_list(
    content_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep only the text blocks, mirroring ``separate_content``'s split.

    Everything non-text goes to the modal processors on both insertion
    paths; feeding it to the IR builder as well would put tables/equations
    into the text chunks a second time.
    """
    return [
        item
        for item in content_list
        if item.get("type") == "text" and str(item.get("text") or "").strip()
    ]


async def insert_text_with_sidecar(
    lightrag,
    *,
    content_list: List[Dict[str, Any]],
    doc_id: str,
    file_name: str,
    document_name: str,
    sidecar_parent_dir: str | Path,
) -> str:
    """Insert a document's text through LightRAG's sidecar pipeline.

    Args:
        lightrag: Initialized LightRAG instance.
        content_list: Full MinerU content list; non-text items are filtered
            out here (the modal processors own them).
        doc_id: Content-based ``doc-<md5>`` id (also seeds sidecar block ids).
        file_name: Citation file reference (``_get_file_reference`` output).
        document_name: Original file name (e.g. ``report.pdf``) recorded in
            the sidecar meta.
        sidecar_parent_dir: Directory the ``<stem>.parsed/`` sidecar is
            written under; must outlive the document (chunk provenance
            resolves against it).

    Returns:
        ``"inserted"`` or ``"duplicate"`` (content already known to LightRAG
        — same silent-skip semantics as ``ainsert``).

    Raises:
        Exception: any failure before the enqueue step; the caller is
        expected to fall back to plain text insertion.
    """
    from lightrag.parser.external.mineru.ir_builder import MinerUIRBuilder
    from lightrag.sidecar.writer import write_sidecar
    from lightrag.utils_pipeline import (
        make_lightrag_doc_content,
        sidecar_uri_for,
    )

    text_items = text_only_content_list(content_list)
    if not text_items:
        return "duplicate"  # nothing textual to insert; caller's gate should
        # have caught this, but never enqueue an empty document.

    # The builder's public contract is a directory holding content_list.json;
    # no assets are needed for text-only input.
    with tempfile.TemporaryDirectory(prefix="ra_sidecar_") as tmp:
        raw_dir = Path(tmp)
        (raw_dir / "content_list.json").write_text(
            json.dumps(text_items, ensure_ascii=False), encoding="utf-8"
        )
        ir = MinerUIRBuilder().normalize_from_workdir(
            raw_dir, document_name=document_name
        )

    parsed_dir = Path(sidecar_parent_dir) / f"{Path(document_name).stem}.parsed"
    parsed_data = write_sidecar(
        ir, parsed_dir=parsed_dir, doc_id=doc_id, engine="mineru"
    )
    merged_text = parsed_data["content"]

    # "P" selects the paragraph-semantic chunker — the only strategy that
    # consumes blocks.jsonl and records per-chunk block refs; the default
    # fixed-token chunker ignores the sidecar entirely.
    await lightrag.apipeline_enqueue_documents(
        input=[merged_text],
        ids=[doc_id],
        file_paths=[file_name],
        process_options=["P"],
    )

    # Enqueue skipping the doc (content-hash duplicate) leaves no doc_status
    # row; forging full_docs for a skipped document would strand an orphan
    # record, so mirror ainsert's silent-skip semantics instead.
    if not await lightrag.doc_status.get_by_id(doc_id):
        logger.info(
            f"Sidecar insertion: {document_name} already known to LightRAG "
            f"({doc_id}); skipping"
        )
        return "duplicate"

    # MERGE into the enqueued full_docs row, never replace it: enqueue stores
    # process_options there and the chunking stage reads them back — a
    # wholesale overwrite silently reverts the document to the default
    # fixed-token chunker.
    existing = await lightrag.full_docs.get_by_id(doc_id) or {}
    await lightrag.full_docs.upsert(
        {
            doc_id: {
                **existing,
                "content": make_lightrag_doc_content(merged_text),
                "file_path": file_name,
                "parse_format": "lightrag",
                "sidecar_location": sidecar_uri_for(parsed_dir),
                "parse_engine": "mineru",
            }
        }
    )
    await lightrag.full_docs.index_done_callback()

    await lightrag.apipeline_process_enqueue_documents()
    return "inserted"
