from __future__ import annotations

import importlib.util
import json


def _load_pipeline():
    spec = importlib.util.spec_from_file_location("eval_pipeline", "reproduce/eval_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, status_code: int, lines: list[str]):
        self.status_code = status_code
        self._lines = lines
        self.closed = False

    def iter_lines(self, decode_unicode: bool = False):
        assert decode_unicode is True
        yield from self._lines

    def close(self):
        self.closed = True


def _event(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False)


def test_completed_answer_records_http_and_stream_evidence(monkeypatch):
    pipeline = _load_pipeline()
    response = _Response(200, [_event({"type": "token", "content": "答案"}), _event({"type": "done"})])
    monkeypatch.setattr(pipeline.requests, "post", lambda *_args, **_kwargs: response)

    result = pipeline.query_agent_stream("token", "问题", agent_id="odl-agent")

    assert result["success"] is True
    assert result["http_status"] == 200
    assert result["request_started"] is True
    assert result["response_received"] is True
    assert result["stream_done"] is True
    assert result["answer_chars"] == 2
    assert result["failure_category"] is None
    assert response.closed is True


def test_completed_stream_without_tokens_is_answer_empty_not_unattempted(monkeypatch):
    pipeline = _load_pipeline()
    monkeypatch.setattr(
        pipeline.requests,
        "post",
        lambda *_args, **_kwargs: _Response(200, [_event({"type": "done"})]),
    )

    result = pipeline.query_agent_stream("token", "问题")

    assert result["success"] is False
    assert result["failure_category"] == "answer_empty"
    assert result["http_status"] == 200
    assert result["stream_done"] is True
    assert result["request_started"] is True


def test_timeout_and_preflight_are_distinct(monkeypatch):
    pipeline = _load_pipeline()

    def raise_timeout(*_args, **_kwargs):
        raise pipeline.requests.Timeout()

    monkeypatch.setattr(pipeline.requests, "post", raise_timeout)
    timeout = pipeline.query_agent_stream("token", "问题")
    not_attempted = pipeline.query_agent_stream("", "问题")

    assert timeout["failure_category"] == "transport_timeout"
    assert timeout["request_started"] is True
    assert timeout["response_received"] is False
    assert not_attempted["failure_category"] == "not_attempted"
    assert not_attempted["request_started"] is False


def test_retrieval_only_records_metadata_without_context_text(monkeypatch):
    pipeline = _load_pipeline()
    response = _Response(200, [
        _event({"type": "retrieval", "context_present": True, "context_chars": 321, "text_source_count": 2}),
        _event({"type": "done", "phase": "retrieval"}),
    ])
    monkeypatch.setattr(pipeline.requests, "post", lambda *_args, **_kwargs: response)

    result = pipeline.query_agent_stream("token", "问题", retrieval_only=True)

    assert result["success"] is True
    assert result["answer"] == ""
    assert result["retrieval"] == {
        "context_present": True,
        "context_chars": 321,
        "text_source_count": 2,
    }


def test_two_phase_retest_checkpoints_each_case(monkeypatch, tmp_path):
    pipeline = _load_pipeline()
    calls = []

    def fake_query(_token, question, _mode, **kwargs):
        calls.append((question, kwargs["retrieval_only"]))
        if kwargs["retrieval_only"]:
            return {
                "success": True,
                "result_status": "completed",
                "failure_category": None,
                "started_at": "2026-01-01T00:00:00+00:00",
                "retrieval": {"context_present": True, "context_chars": 10, "text_source_count": 1},
            }
        return {
            "success": True,
            "result_status": "completed",
            "failure_category": None,
            "started_at": "2026-01-01T00:00:01+00:00",
            "answer": "answer",
            "answer_chars": 6,
        }

    monkeypatch.setattr(pipeline, "query_agent_stream", fake_query)
    checkpoint = tmp_path / "retest.json"
    result = pipeline.run_two_phase_retest(
        "token",
        [(95, {"question": "Q1", "answer": "A1"}), (96, {"question": "Q2", "answer": "A2"})],
        mode="hybrid",
        agent_id="odl-agent",
        doc_id="odl-doc",
        timeout_seconds=30,
        checkpoint_path=checkpoint,
    )

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert len(saved["cases"]) == 2
    assert [case["case_id"] for case in saved["cases"]] == ["q095", "q096"]
    assert calls == [("Q1", True), ("Q1", False), ("Q2", True), ("Q2", False)]
