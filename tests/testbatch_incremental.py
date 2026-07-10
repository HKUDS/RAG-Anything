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


def _seed_two_docs(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    first_doc = docs_dir / "a.txt"
    second_doc = docs_dir / "b.txt"
    first_doc.write_text("alpha", encoding="utf-8")
    second_doc.write_text("beta", encoding="utf-8")
    return docs_dir, first_doc, second_doc


def test_incremental_skip_does_not_rehash_unchanged_files(monkeypatch, tmp_path):
    batch_parser, _ = _make_batch_parser(monkeypatch)
    docs_dir, first_doc, second_doc = _seed_two_docs(tmp_path)
    output_dir = tmp_path / "out"

    batch_parser.process_batch([str(docs_dir)], str(output_dir), incremental=True)

    # Second run: both files are unchanged, so the size+mtime fast path must
    # skip them without hashing a single byte.
    hashed = []
    real_md5 = type(batch_parser)._compute_md5

    def counting_md5(file_path):
        hashed.append(file_path)
        return real_md5(file_path)

    monkeypatch.setattr(type(batch_parser), "_compute_md5", staticmethod(counting_md5))

    result = batch_parser.process_batch(
        [str(docs_dir)], str(output_dir), incremental=True
    )

    assert set(result.skipped_files) == {str(first_doc), str(second_doc)}
    assert hashed == []


def test_incremental_ignores_corrupt_manifest(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    docs_dir, first_doc, second_doc = _seed_two_docs(tmp_path)
    output_dir = tmp_path / "out"

    batch_parser.process_batch([str(docs_dir)], str(output_dir), incremental=True)

    manifest_path = output_dir / ".raganything_batch_manifest.json"
    manifest_path.write_text("this is not valid json{", encoding="utf-8")
    fake_parser.processed_files.clear()

    result = batch_parser.process_batch(
        [str(docs_dir)], str(output_dir), incremental=True
    )

    # A corrupt manifest must be ignored and every file reprocessed.
    assert set(result.successful_files) == {str(first_doc), str(second_doc)}
    assert result.skipped_files == []


def test_incremental_tolerates_unreadable_file(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    docs_dir, first_doc, second_doc = _seed_two_docs(tmp_path)
    output_dir = tmp_path / "out"

    batch_parser.process_batch([str(docs_dir)], str(output_dir), incremental=True)
    fake_parser.processed_files.clear()

    # Simulate one file becoming unreadable between discovery and the scan.
    real_metadata = type(batch_parser)._file_metadata

    def flaky_metadata(file_path):
        if file_path == str(first_doc):
            raise OSError("simulated unreadable file")
        return real_metadata(file_path)

    monkeypatch.setattr(
        type(batch_parser), "_file_metadata", staticmethod(flaky_metadata)
    )

    # Must not raise; the unreadable file is treated as changed (queued for
    # processing) while the other unchanged file is still skipped.
    result = batch_parser.process_batch(
        [str(docs_dir)], str(output_dir), incremental=True
    )

    assert str(first_doc) in (result.successful_files + result.failed_files)
    assert result.skipped_files == [str(second_doc)]


def test_incremental_dry_run_does_not_write_manifest(monkeypatch, tmp_path):
    batch_parser, _ = _make_batch_parser(monkeypatch)
    docs_dir, _first_doc, _second_doc = _seed_two_docs(tmp_path)
    output_dir = tmp_path / "out"

    batch_parser.process_batch(
        [str(docs_dir)], str(output_dir), incremental=True, dry_run=True
    )

    manifest_path = output_dir / ".raganything_batch_manifest.json"
    assert not manifest_path.exists()


def test_filter_supported_files_deduplicates_overlapping_inputs(monkeypatch, tmp_path):
    batch_parser, _ = _make_batch_parser(monkeypatch)
    docs_dir, first_doc, second_doc = _seed_two_docs(tmp_path)

    result = batch_parser.filter_supported_files(
        [str(docs_dir), str(first_doc), str(docs_dir)]
    )

    assert result == [str(first_doc), str(second_doc)]
