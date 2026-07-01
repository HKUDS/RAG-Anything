import importlib.util
import sys
import types
from pathlib import Path


class FakeParser:
    OFFICE_FORMATS = {".docx"}
    IMAGE_FORMATS = {".png"}
    TEXT_FORMATS = {".txt", ".md"}

    def __init__(self):
        self.processed_files = []

    def check_installation(self):
        return True

    def parse_document(self, file_path, output_dir, method="auto", **kwargs):
        self.processed_files.append(file_path)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return [{"type": "text", "text": Path(file_path).read_text()}]


def _make_batch_parser(monkeypatch):
    fake_parser = FakeParser()
    repo_root = Path(__file__).parents[1]

    package = types.ModuleType("raganything")
    package.__path__ = [str(repo_root / "raganything")]
    parser_module = types.ModuleType("raganything.parser")
    parser_module.get_parser = lambda parser_type: fake_parser

    monkeypatch.setitem(sys.modules, "raganything", package)
    monkeypatch.setitem(sys.modules, "raganything.parser", parser_module)
    sys.modules.pop("raganything.batch_parser", None)

    spec = importlib.util.spec_from_file_location(
        "raganything.batch_parser",
        repo_root / "raganything" / "batch_parser.py",
    )
    batch_parser_module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "raganything.batch_parser", batch_parser_module)
    spec.loader.exec_module(batch_parser_module)

    batch_parser = batch_parser_module.BatchParser(
        parser_type="fake",
        max_workers=1,
        show_progress=False,
        skip_installation_check=True,
    )
    return batch_parser, fake_parser


def test_incremental_batch_skips_unchanged_files(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    first_doc = docs_dir / "a.txt"
    second_doc = docs_dir / "b.txt"
    first_doc.write_text("alpha", encoding="utf-8")
    second_doc.write_text("beta", encoding="utf-8")
    output_dir = tmp_path / "out"

    first_result = batch_parser.process_batch(
        [str(docs_dir)],
        str(output_dir),
        incremental=True,
    )

    assert set(first_result.successful_files) == {str(first_doc), str(second_doc)}
    assert first_result.skipped_files == []
    assert set(fake_parser.processed_files) == {str(first_doc), str(second_doc)}

    fake_parser.processed_files.clear()
    second_result = batch_parser.process_batch(
        [str(docs_dir)],
        str(output_dir),
        incremental=True,
    )

    assert second_result.successful_files == []
    assert set(second_result.skipped_files) == {str(first_doc), str(second_doc)}
    assert second_result.success_rate == 100.0
    assert fake_parser.processed_files == []

    first_doc.write_text("alpha changed", encoding="utf-8")
    third_result = batch_parser.process_batch(
        [str(docs_dir)],
        str(output_dir),
        incremental=True,
    )

    assert third_result.successful_files == [str(first_doc)]
    assert third_result.skipped_files == [str(second_doc)]
    assert fake_parser.processed_files == [str(first_doc)]


def test_incremental_dry_run_reports_changed_and_skipped_files(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    first_doc = docs_dir / "a.txt"
    second_doc = docs_dir / "b.txt"
    first_doc.write_text("alpha", encoding="utf-8")
    second_doc.write_text("beta", encoding="utf-8")
    output_dir = tmp_path / "out"

    batch_parser.process_batch([str(docs_dir)], str(output_dir), incremental=True)
    fake_parser.processed_files.clear()

    first_doc.write_text("alpha changed", encoding="utf-8")
    dry_run_result = batch_parser.process_batch(
        [str(docs_dir)],
        str(output_dir),
        incremental=True,
        dry_run=True,
    )

    assert dry_run_result.dry_run is True
    assert dry_run_result.successful_files == [str(first_doc)]
    assert dry_run_result.skipped_files == [str(second_doc)]
    assert fake_parser.processed_files == []
