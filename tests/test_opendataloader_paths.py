from pathlib import Path

from raganything.parser.office_parser import PageTrackedContent
from raganything.parser.opendataloader_parser import _resolve_output_base


def test_relative_output_directory_resolves_before_artifact_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_path = (tmp_path / "uploads" / "document.pdf").resolve()

    output_base = _resolve_output_base("odl-artifacts", pdf_path)
    artifact = (output_base / "document" / "run-1" / "page.json").resolve()

    assert output_base.is_absolute()
    assert artifact.relative_to(output_base).as_posix() == (
        "document/run-1/page.json"
    )


def test_default_output_directory_is_absolute(tmp_path):
    pdf_path = (tmp_path / "uploads" / "document.pdf").resolve()

    assert _resolve_output_base(None, pdf_path) == (
        pdf_path.parent / "odl_output"
    ).resolve()


def test_page_tracked_content_carries_odl_provenance_reference():
    reference = {
        "schema": "odl-provenance-ref-v1",
        "relative_path": "document/run-1/provenance.json",
    }

    content = PageTrackedContent([], {"source_total_pages": 1}, reference)

    assert content.provenance_ref == reference
