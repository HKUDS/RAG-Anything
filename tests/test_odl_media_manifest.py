from pathlib import Path

from raganything.services.odl_media_manifest import (
    audit_persisted_entries,
    bind_persisted_image_chunk,
    build_media_entry,
    write_pending_manifest,
)


def _write_png(path: Path) -> None:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * 32))


def test_manifest_binds_validated_odl_image_to_persisted_chunk(tmp_path):
    output_root = tmp_path / "odl-output"
    media_dir = output_root / "media"
    media_dir.mkdir(parents=True)
    image = media_dir / "figure-1.png"
    _write_png(image)

    entry = build_media_entry(
        path=image,
        output_root=output_root,
        page=4,
        element_id="figure-1",
        caption="diagram",
    )
    manifest = output_root / "document_media_manifest.json"
    write_pending_manifest(manifest, [entry])

    assert entry["relative_path"] == "media/figure-1.png"
    assert entry["mime"] == "image/png"
    assert entry["page"] == 4
    assert entry["document_id"] is None
    assert bind_persisted_image_chunk(
        manifest,
        media_id=entry["media_id"],
        document_id="doc-1",
        chunk_id="chunk-1",
    )

    complete, counts = audit_persisted_entries(
        {str(manifest)},
        document_id="doc-1",
        expected_media_ids={entry["media_id"]},
        persisted_chunk_ids={"chunk-1"},
    )

    assert complete is True
    assert counts == {"expected": 1, "valid": 1, "chunks": 1}


def test_media_id_includes_page_occurrence(tmp_path):
    output_root = tmp_path / "odl-output"
    output_root.mkdir()
    image = output_root / "figure.png"
    _write_png(image)

    page_one = build_media_entry(
        path=image,
        output_root=output_root,
        page=1,
        element_id="page-local-1",
        caption="",
    )
    page_two = build_media_entry(
        path=image,
        output_root=output_root,
        page=2,
        element_id="page-local-1",
        caption="",
    )

    assert page_one["sha256"] == page_two["sha256"]
    assert page_one["media_id"] != page_two["media_id"]


def test_manifest_audit_fails_closed_when_chunk_is_not_persisted(tmp_path):
    output_root = tmp_path / "odl-output"
    output_root.mkdir()
    image = output_root / "figure.png"
    _write_png(image)
    entry = build_media_entry(
        path=image,
        output_root=output_root,
        page=1,
        element_id="figure-1",
        caption="",
    )
    manifest = output_root / "document_media_manifest.json"
    write_pending_manifest(manifest, [entry])
    assert bind_persisted_image_chunk(
        manifest,
        media_id=entry["media_id"],
        document_id="doc-1",
        chunk_id="chunk-1",
    )

    complete, counts = audit_persisted_entries(
        {str(manifest)},
        document_id="doc-1",
        expected_media_ids={entry["media_id"]},
        persisted_chunk_ids=set(),
    )

    assert complete is False
    assert counts["expected"] == 1


def test_odl_image_block_carries_pending_manifest_entry(tmp_path):
    from raganything.parser.opendataloader_parser import _build_image_block

    output_root = tmp_path / "odl-output"
    output_root.mkdir()
    image = output_root / "figure.png"
    _write_png(image)

    block = _build_image_block(
        {"id": "figure-7", "source": "figure.png", "caption": "wiring"},
        output_root,
        6,
        str(tmp_path),
    )

    assert block is not None
    assert block["type"] == "image"
    assert block["_odl_media"]["relative_path"] == "figure.png"
    assert block["_odl_media"]["page"] == 7
    assert block["_odl_media"]["element_id"] == "figure-7"
