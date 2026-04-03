"""Tests for incremental folder scanning (issue #156).

``process_folder_complete(incremental=True)`` must:
- skip files whose MD5 has not changed since the last successful run
- process new files and files whose content changed
- persist a manifest so the decision survives across calls
- remove failed files from the manifest so they are retried
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_batch_mixin(working_dir: str):
    """Return a BatchMixin-like object with a minimal config."""
    from raganything.batch import BatchMixin

    obj = object.__new__(BatchMixin)
    obj.logger = MagicMock()

    cfg = MagicMock()
    cfg.working_dir = working_dir
    cfg.parser_output_dir = os.path.join(working_dir, "output")
    cfg.parse_method = "auto"
    cfg.supported_file_extensions = [".txt", ".pdf"]
    cfg.recursive_folder_processing = False
    cfg.max_concurrent_files = 2
    obj.config = cfg

    obj._ensure_lightrag_initialized = AsyncMock()
    return obj


# ---------------------------------------------------------------------------
# Unit tests for helper methods
# ---------------------------------------------------------------------------


class TestFileMd5:
    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_bytes(b"hello")
        from raganything.batch import BatchMixin

        md5 = BatchMixin._file_md5(f)
        assert len(md5) == 32
        assert all(c in "0123456789abcdef" for c in md5)

    def test_different_content_different_hash(self, tmp_path):
        from raganything.batch import BatchMixin

        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(b"hello")
        f2.write_bytes(b"world")
        assert BatchMixin._file_md5(f1) != BatchMixin._file_md5(f2)

    def test_same_content_same_hash(self, tmp_path):
        from raganything.batch import BatchMixin

        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(b"identical")
        f2.write_bytes(b"identical")
        assert BatchMixin._file_md5(f1) == BatchMixin._file_md5(f2)


class TestManifestIO:
    def test_load_missing_manifest_returns_empty(self, tmp_path):

        obj = _make_batch_mixin(str(tmp_path))
        mp = tmp_path / "does_not_exist.json"
        assert obj._load_manifest(mp) == {}

    def test_save_and_load_roundtrip(self, tmp_path):

        obj = _make_batch_mixin(str(tmp_path))
        mp = tmp_path / "manifest.json"
        data = {"/some/file.txt": {"md5": "abc123", "processed": True}}
        obj._save_manifest(mp, data)
        assert obj._load_manifest(mp) == data

    def test_load_corrupt_manifest_returns_empty(self, tmp_path):

        obj = _make_batch_mixin(str(tmp_path))
        mp = tmp_path / "corrupt.json"
        mp.write_text("not valid json {{{{")
        assert obj._load_manifest(mp) == {}


# ---------------------------------------------------------------------------
# Integration tests for process_folder_complete(incremental=True)
# ---------------------------------------------------------------------------


class TestIncrementalFolderScan:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_processes_all_files_on_first_run(self, tmp_path):

        src = tmp_path / "docs"
        src.mkdir()
        (src / "a.txt").write_text("alpha")
        (src / "b.txt").write_text("beta")

        obj = _make_batch_mixin(str(tmp_path / "wd"))
        processed = []

        async def fake_process(file_path, **kwargs):
            processed.append(file_path)

        obj.process_document_complete = fake_process

        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )

        assert len(processed) == 2

    def test_skips_unchanged_files_on_second_run(self, tmp_path):

        src = tmp_path / "docs"
        src.mkdir()
        (src / "a.txt").write_text("alpha")
        (src / "b.txt").write_text("beta")

        obj = _make_batch_mixin(str(tmp_path / "wd"))
        processed_runs = []

        async def fake_process(file_path, **kwargs):
            processed_runs.append(file_path)

        obj.process_document_complete = fake_process

        # First run — processes both files
        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )
        assert len(processed_runs) == 2
        processed_runs.clear()

        # Second run — nothing changed, should skip both
        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )
        assert processed_runs == []

    def test_reprocesses_changed_file(self, tmp_path):

        src = tmp_path / "docs"
        src.mkdir()
        (src / "a.txt").write_text("alpha")
        (src / "b.txt").write_text("beta")

        obj = _make_batch_mixin(str(tmp_path / "wd"))
        processed_runs = []

        async def fake_process(file_path, **kwargs):
            processed_runs.append(Path(file_path).name)

        obj.process_document_complete = fake_process

        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )
        processed_runs.clear()

        # Change only b.txt
        (src / "b.txt").write_text("CHANGED CONTENT")

        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )

        assert processed_runs == ["b.txt"], processed_runs

    def test_processes_newly_added_file(self, tmp_path):

        src = tmp_path / "docs"
        src.mkdir()
        (src / "a.txt").write_text("alpha")

        obj = _make_batch_mixin(str(tmp_path / "wd"))
        processed_runs = []

        async def fake_process(file_path, **kwargs):
            processed_runs.append(Path(file_path).name)

        obj.process_document_complete = fake_process

        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )
        processed_runs.clear()

        # Add a new file
        (src / "new.txt").write_text("new document")

        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )

        assert processed_runs == ["new.txt"]

    def test_failed_file_is_retried_next_run(self, tmp_path):

        src = tmp_path / "docs"
        src.mkdir()
        (src / "ok.txt").write_text("fine")
        (src / "bad.txt").write_text("trouble")

        obj = _make_batch_mixin(str(tmp_path / "wd"))
        call_count: dict[str, int] = {}

        async def fake_process(file_path, **kwargs):
            name = Path(file_path).name
            call_count[name] = call_count.get(name, 0) + 1
            if name == "bad.txt":
                raise RuntimeError("simulated failure")

        obj.process_document_complete = fake_process

        # First run — bad.txt fails
        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )

        # Second run — bad.txt must be retried; ok.txt must be skipped
        self._run(
            obj.process_folder_complete(str(src), incremental=True, display_stats=False)
        )

        assert call_count["ok.txt"] == 1, "ok.txt should only be processed once"
        assert call_count["bad.txt"] == 2, "bad.txt should be retried after failure"

    def test_non_incremental_does_not_create_manifest(self, tmp_path):

        src = tmp_path / "docs"
        src.mkdir()
        (src / "a.txt").write_text("hi")

        wd = tmp_path / "wd"
        wd.mkdir()
        obj = _make_batch_mixin(str(wd))

        async def fake_process(file_path, **kwargs):
            pass

        obj.process_document_complete = fake_process

        self._run(
            obj.process_folder_complete(
                str(src), incremental=False, display_stats=False
            )
        )

        manifest_files = list(wd.glob(".folder_manifest_*.json"))
        assert manifest_files == [], (
            "No manifest should be written for non-incremental runs"
        )
