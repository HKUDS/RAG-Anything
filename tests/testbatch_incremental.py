import importlib.util
import json
import sys
import time
import types
from pathlib import Path

import pytest


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


def _load_batch_parser_module(monkeypatch):
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

    return batch_parser_module, fake_parser


def _make_batch_parser(monkeypatch):
    batch_parser_module, fake_parser = _load_batch_parser_module(monkeypatch)

    batch_parser = batch_parser_module.BatchParser(
        parser_type="fake",
        max_workers=1,
        show_progress=False,
        skip_installation_check=True,
    )
    return batch_parser, fake_parser


def test_cli_can_disable_recursive_scan(monkeypatch, tmp_path):
    batch_parser_module, _ = _load_batch_parser_module(monkeypatch)
    captured = {}

    class FakeResult:
        successful_files = []
        failed_files = []
        skipped_files = []

        @staticmethod
        def summary():
            return "Batch processing results"

    class FakeBatchParser:
        def __init__(self, **kwargs):
            pass

        def process_batch(self, **kwargs):
            captured.update(kwargs)
            return FakeResult()

    monkeypatch.setattr(batch_parser_module, "BatchParser", FakeBatchParser)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "raganything.batch_parser",
            str(tmp_path / "docs"),
            "--output",
            str(tmp_path / "output"),
            "--no-recursive",
        ],
    )

    assert batch_parser_module.main() == 0
    assert captured["recursive"] is False


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

    # docs_dir (listed twice) overlaps with first_doc; dedup keeps each file
    # exactly once. Compare sorted since directory glob order is not defined.
    assert sorted(result) == sorted([str(first_doc), str(second_doc)])


def test_batch_isolates_same_name_files(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    batch_parser.max_workers = 2

    first_doc = tmp_path / "source_a" / "report.txt"
    second_doc = tmp_path / "source_b" / "report.txt"
    first_doc.parent.mkdir()
    second_doc.parent.mkdir()
    first_doc.write_text("from source A", encoding="utf-8")
    second_doc.write_text("from source B", encoding="utf-8")

    output_dirs = {}

    def parse_document(file_path, output_dir, method="auto", **kwargs):
        output_dirs[file_path] = output_dir
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / "source.txt").write_text(
            Path(file_path).read_text(encoding="utf-8"), encoding="utf-8"
        )
        fake_parser.processed_files.append(file_path)
        return [{"type": "text", "text": "parsed"}]

    fake_parser.parse_document = parse_document

    result = batch_parser.process_batch(
        [str(first_doc), str(second_doc)], str(tmp_path / "out")
    )

    assert sorted(result.successful_files) == sorted([str(first_doc), str(second_doc)])
    assert output_dirs[str(first_doc)] != output_dirs[str(second_doc)]
    assert (Path(output_dirs[str(first_doc)]) / "source.txt").read_text(
        encoding="utf-8"
    ) == "from source A"
    assert (Path(output_dirs[str(second_doc)]) / "source.txt").read_text(
        encoding="utf-8"
    ) == "from source B"


def test_timeout_is_applied_per_file_not_to_entire_batch(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    docs_dir, first_doc, second_doc = _seed_two_docs(tmp_path)
    batch_parser.timeout_per_file = 0.1

    original_parse = fake_parser.parse_document

    def slow_parse(*args, **kwargs):
        time.sleep(0.06)
        return original_parse(*args, **kwargs)

    fake_parser.parse_document = slow_parse

    result = batch_parser.process_batch([str(docs_dir)], str(tmp_path / "out"))

    # Both files finish under the per-file timeout, so both succeed. The old
    # as_completed(timeout=...) applied the timeout to the whole batch and would
    # have failed here. Compare sorted since glob order is not defined.
    assert sorted(result.successful_files) == sorted([str(first_doc), str(second_doc)])
    assert result.failed_files == []


@pytest.mark.parametrize(
    "first_options,second_options",
    [
        ({"parse_method": "auto"}, {"parse_method": "ocr"}),
        ({"lang": "en"}, {"lang": "ch"}),
        ({"start_page": 0, "end_page": 1}, {"start_page": 2, "end_page": 3}),
        ({"include_layout_blocks": False}, {"include_layout_blocks": True}),
    ],
)
def test_incremental_reprocesses_when_parse_options_change(
    monkeypatch, tmp_path, first_options, second_options
):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("unchanged source", encoding="utf-8")
    output_dir = str(tmp_path / "out")
    inputs = [str(document)]

    batch_parser.process_batch(inputs, output_dir, incremental=True, **first_options)
    fake_parser.processed_files.clear()
    result = batch_parser.process_batch(
        inputs, output_dir, incremental=True, **second_options
    )

    assert result.successful_files == inputs
    assert result.skipped_files == []
    assert fake_parser.processed_files == inputs
    repeated = batch_parser.process_batch(
        inputs, output_dir, incremental=True, **second_options
    )
    assert repeated.skipped_files == inputs


def test_incremental_reprocesses_when_parser_changes(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("unchanged source", encoding="utf-8")
    inputs = [str(document)]
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(inputs, output_dir, incremental=True)

    # A different parser instance shares the same output directory/manifest.
    other = type(batch_parser)(
        parser_type="other", show_progress=False, skip_installation_check=True
    )
    fake_parser.processed_files.clear()
    result = other.process_batch(inputs, output_dir, incremental=True)

    assert result.successful_files == inputs
    assert fake_parser.processed_files == inputs


def test_incremental_legacy_manifest_is_refreshed_once(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("unchanged source", encoding="utf-8")
    inputs = [str(document)]
    output_dir = str(tmp_path / "out")
    signature = batch_parser._file_signature(str(document))
    batch_parser._save_incremental_manifest(output_dir, {signature["path"]: signature})

    result = batch_parser.process_batch(inputs, output_dir, incremental=True)
    assert result.successful_files == inputs
    assert fake_parser.processed_files == inputs
    assert (
        batch_parser.process_batch(inputs, output_dir, incremental=True).skipped_files
        == inputs
    )


def test_incremental_configuration_is_per_file_and_failed_reparse_is_retried(
    monkeypatch, tmp_path
):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    _docs_dir, first_doc, second_doc = _seed_two_docs(tmp_path)
    inputs = [str(first_doc), str(second_doc)]
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(inputs, output_dir, incremental=True, lang="en")
    original_parse = fake_parser.parse_document

    def fail_second(file_path, **kwargs):
        if file_path == str(second_doc):
            raise RuntimeError("temporary parser failure")
        return original_parse(file_path, **kwargs)

    fake_parser.parse_document = fail_second
    changed = batch_parser.process_batch(
        inputs, output_dir, incremental=True, lang="ch"
    )
    assert changed.successful_files == [str(first_doc)]
    assert changed.failed_files == [str(second_doc)]

    fake_parser.parse_document = original_parse
    retried = batch_parser.process_batch(
        inputs, output_dir, incremental=True, lang="ch"
    )
    assert retried.successful_files == [str(second_doc)]
    assert retried.skipped_files == [str(first_doc)]


def test_incremental_option_order_and_worker_count_do_not_invalidate(
    monkeypatch, tmp_path
):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("source", encoding="utf-8")
    inputs = [str(document)]
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(
        inputs, output_dir, incremental=True, lang="en", start_page=0
    )
    batch_parser.max_workers = 3
    result = batch_parser.process_batch(
        inputs, output_dir, incremental=True, start_page=0, lang="en"
    )
    assert result.skipped_files == inputs
    assert fake_parser.processed_files == inputs


def test_incremental_dry_run_with_new_options_preserves_manifest(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("source", encoding="utf-8")
    inputs = [str(document)]
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(inputs, output_dir, incremental=True, lang="en")
    manifest_path = batch_parser._manifest_path(output_dir)
    before = manifest_path.read_bytes()
    result = batch_parser.process_batch(
        inputs, output_dir, incremental=True, dry_run=True, lang="ch"
    )
    assert result.successful_files == inputs
    assert result.skipped_files == []
    assert manifest_path.read_bytes() == before
    assert fake_parser.processed_files == inputs


def test_incremental_does_not_persist_raw_parser_options(monkeypatch, tmp_path):
    batch_parser, _ = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("source", encoding="utf-8")
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(
        [str(document)], output_dir, incremental=True, api_key="private-test-key"
    )
    manifest_text = batch_parser._manifest_path(output_dir).read_text(encoding="utf-8")
    assert "private-test-key" not in manifest_text
    assert json.loads(manifest_text)["files"]


def test_incremental_custom_option_objects_disable_reuse(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("source", encoding="utf-8")
    inputs = [str(document)]
    output_dir = str(tmp_path / "out")
    custom_option = object()
    for _ in range(2):
        result = batch_parser.process_batch(
            inputs, output_dir, incremental=True, custom_option=custom_option
        )
        assert result.successful_files == inputs
        assert result.skipped_files == []
    assert fake_parser.processed_files == inputs * 2


def test_failed_reparse_invalidates_previous_configuration(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("source", encoding="utf-8")
    inputs = [str(document)]
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(inputs, output_dir, incremental=True, lang="en")
    original_parse = fake_parser.parse_document

    def fail_parse(**kwargs):
        raise RuntimeError("parser failed after overwriting old output")

    fake_parser.parse_document = fail_parse
    result = batch_parser.process_batch(inputs, output_dir, incremental=True, lang="ch")
    assert result.failed_files == inputs
    fake_parser.parse_document = original_parse
    restored = batch_parser.process_batch(
        inputs, output_dir, incremental=True, lang="en"
    )
    assert restored.successful_files == inputs
    assert restored.skipped_files == []


@pytest.mark.parametrize(
    "first_options,second_options",
    [
        ({}, {"include_layout_blocks": False}),
        ({}, {"lang": None}),
        ({"lang": "en"}, {"lang": "en", "start_page": None}),
    ],
)
def test_incremental_explicit_defaults_do_not_invalidate(
    monkeypatch, tmp_path, first_options, second_options
):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("unchanged source", encoding="utf-8")
    output_dir = str(tmp_path / "out")
    inputs = [str(document)]

    batch_parser.process_batch(inputs, output_dir, incremental=True, **first_options)
    fake_parser.processed_files.clear()
    result = batch_parser.process_batch(
        inputs, output_dir, incremental=True, **second_options
    )

    assert result.skipped_files == inputs
    assert fake_parser.processed_files == []


def test_incremental_parser_name_case_does_not_invalidate(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("unchanged source", encoding="utf-8")
    inputs = [str(document)]
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(inputs, output_dir, incremental=True)

    upper = type(batch_parser)(
        parser_type=batch_parser.parser_type.upper(),
        show_progress=False,
        skip_installation_check=True,
    )
    fake_parser.processed_files.clear()
    result = upper.process_batch(inputs, output_dir, incremental=True)

    assert result.skipped_files == inputs
    assert fake_parser.processed_files == []


def test_incremental_custom_parser_option_change_still_invalidates(
    monkeypatch, tmp_path
):
    # Options outside the built-in set are kept verbatim: a custom parser may
    # depend on them, so changing one must still force a reparse.
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    document = tmp_path / "document.txt"
    document.write_text("unchanged source", encoding="utf-8")
    inputs = [str(document)]
    output_dir = str(tmp_path / "out")

    batch_parser.process_batch(inputs, output_dir, incremental=True, custom_mode="a")
    fake_parser.processed_files.clear()
    result = batch_parser.process_batch(
        inputs, output_dir, incremental=True, custom_mode="b"
    )

    assert result.successful_files == inputs
    assert fake_parser.processed_files == inputs


@pytest.mark.parametrize("fail_reparse", [False, True])
def test_non_incremental_reparse_invalidates_old_artifacts(
    monkeypatch, tmp_path, fail_reparse
):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    _, first_doc, second_doc = _seed_two_docs(tmp_path)
    inputs = [str(first_doc), str(second_doc)]
    output_dir = str(tmp_path / "out")

    def parse_with_artifacts(file_path, output_dir, method="auto", **kwargs):
        artifact = Path(output_dir) / "result.txt"
        artifact.write_text(kwargs["lang"], encoding="utf-8")
        if fail_reparse and kwargs["lang"] == "ch":
            raise RuntimeError("failed after replacing the artifact")
        return [{"type": "text", "text": kwargs["lang"]}]

    fake_parser.parse_document = parse_with_artifacts
    batch_parser.process_batch(inputs, output_dir, incremental=True, lang="en")
    result = batch_parser.process_batch(
        [str(first_doc)], output_dir, incremental=False, lang="ch"
    )
    assert result.failed_files == ([str(first_doc)] if fail_reparse else [])
    artifact = batch_parser._file_output_dir(output_dir, str(first_doc)) / "result.txt"
    assert artifact.read_text(encoding="utf-8") == "ch"

    restored = batch_parser.process_batch(
        inputs, output_dir, incremental=True, lang="en"
    )
    assert restored.successful_files == [str(first_doc)]
    assert restored.skipped_files == [str(second_doc)]
    assert artifact.read_text(encoding="utf-8") == "en"


def test_non_incremental_dry_run_preserves_manifest(monkeypatch, tmp_path):
    batch_parser, _ = _make_batch_parser(monkeypatch)
    _, first_doc, _ = _seed_two_docs(tmp_path)
    inputs = [str(first_doc)]
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(inputs, output_dir, incremental=True, lang="en")
    manifest = batch_parser._manifest_path(output_dir)
    before = manifest.read_bytes()
    batch_parser.process_batch(
        inputs, output_dir, incremental=False, dry_run=True, lang="ch"
    )
    assert manifest.read_bytes() == before
    result = batch_parser.process_batch(inputs, output_dir, incremental=True, lang="en")
    assert result.skipped_files == inputs


def test_non_incremental_run_does_not_create_manifest(monkeypatch, tmp_path):
    batch_parser, _ = _make_batch_parser(monkeypatch)
    _, first_doc, _ = _seed_two_docs(tmp_path)
    output_dir = str(tmp_path / "out")
    result = batch_parser.process_batch([str(first_doc)], output_dir)
    assert result.successful_files == [str(first_doc)]
    assert not batch_parser._manifest_path(output_dir).exists()


def test_non_incremental_parse_waits_for_manifest_invalidation(monkeypatch, tmp_path):
    batch_parser, fake_parser = _make_batch_parser(monkeypatch)
    _, first_doc, _ = _seed_two_docs(tmp_path)
    inputs = [str(first_doc)]
    output_dir = str(tmp_path / "out")
    batch_parser.process_batch(inputs, output_dir, incremental=True)
    fake_parser.processed_files.clear()

    def fail_save(*args):
        raise OSError("manifest cannot be replaced")

    monkeypatch.setattr(batch_parser, "_save_incremental_manifest", fail_save)
    with pytest.raises(OSError, match="manifest cannot be replaced"):
        batch_parser.process_batch(inputs, output_dir)
    assert fake_parser.processed_files == []
