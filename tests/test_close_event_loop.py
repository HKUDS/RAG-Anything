"""Tests for RAGAnything.close() event loop handling (issue #135).

Standalone test that reproduces the close() logic without importing the full
RAGAnything module (which requires heavy deps like lightrag, dotenv, etc.).
"""

import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Replicate the close() logic under test ──────────────────────────────


def _close_impl(finalize_coro_factory):
    """The fixed close() logic extracted for unit testing.

    Args:
        finalize_coro_factory: callable that returns a coroutine (or None)
    """

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            loop.create_task(finalize_coro_factory())
        else:
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass
                asyncio.set_event_loop(None)
            asyncio.run(finalize_coro_factory())
    except Exception:
        pass


# ── Tests ──────────────────────────────────────────────────────────────


class TestCloseEventLoop:
    """Test the fixed close() logic under various event loop states."""

    def test_no_event_loop(self):
        """Should not raise when there is no event loop in the thread."""
        called = {"n": 0}

        async def finalize():
            called["n"] += 1

        _close_impl(finalize)
        assert called["n"] == 1

    def test_with_closed_loop(self):
        """Should handle a stale (closed) event loop without warnings."""
        called = {"n": 0}

        async def finalize():
            called["n"] += 1

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.close()

        _close_impl(finalize)
        assert called["n"] == 1

    def test_inside_running_loop(self):
        """Should schedule cleanup as a task when inside a running loop."""
        called = {"n": 0}

        async def finalize():
            called["n"] += 1

        async def run_test():
            _close_impl(finalize)
            await asyncio.sleep(0.05)
            return called["n"]

        count = asyncio.run(run_test())
        assert count == 1

    def test_finalize_raises(self):
        """Should silently handle exceptions during finalize."""

        async def fail_finalize():
            raise RuntimeError("storage error")

        # Should not raise
        _close_impl(fail_finalize)

    def test_no_warning_output(self, capsys):
        """Verify the fixed logic produces no stderr/stdout warnings."""
        called = {"n": 0}

        async def finalize():
            called["n"] += 1

        # Simulate the atexit race: loop exists but is closed
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.close()

        _close_impl(finalize)
        captured = capsys.readouterr()
        assert "Warning" not in captured.out
        assert "Warning" not in captured.err
        assert called["n"] == 1
