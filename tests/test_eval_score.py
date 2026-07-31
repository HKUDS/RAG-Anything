from __future__ import annotations

import importlib.util


def _load_score():
    spec = importlib.util.spec_from_file_location("eval_score", "reproduce/eval_score.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_failed_and_empty_answers_remain_in_unscored_denominator():
    score = _load_score()

    assert score.classify_unscored({"success": False, "error": "transport_timeout"}) == "transport_timeout"
    assert score.classify_unscored({"success": True, "answer": ""}) == "answer_empty"
    assert score.classify_unscored({"success": True, "answer": "有效回答"}) is None
