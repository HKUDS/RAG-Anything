"""
测试环境搭建 — 集成测试用例覆盖核心检索与问答流程。
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class TestHarness:
    """集成测试框架。"""

    def __init__(self, qa_engine=None, video_locator=None,
                 code_parser=None, fault_diagnosis=None):
        self.qa_engine = qa_engine
        self.video_locator = video_locator
        self.code_parser = code_parser
        self.fault_diagnosis = fault_diagnosis
        self._results: list[dict] = []

    def run_all(self) -> dict:
        """运行全部集成测试。"""
        self._results = []

        self._results.append(self.test_qa_basic())
        self._results.append(self.test_qa_no_result())
        self._results.append(self.test_video_locate())
        self._results.append(self.test_code_parse_gcode())
        self._results.append(self.test_fault_diagnosis_flow())

        passed = sum(1 for r in self._results if r["status"] == "passed")
        failed = sum(1 for r in self._results if r["status"] == "failed")
        skipped = sum(1 for r in self._results if r["status"] == "skipped")

        return {
            "total": len(self._results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "results": self._results,
            "run_at": datetime.now().isoformat(),
        }

    def test_qa_basic(self) -> dict:
        """测试基础问答。"""
        if not self.qa_engine:
            return self._skip("QA 引擎未初始化")
        try:
            response = self.qa_engine.answer("数控铣削的基本原理是什么？")
            assert response.answer, "回答不能为空"
            assert response.processing_time_ms > 0, "应记录处理时间"
            return self._pass("QA 基础问答", f"耗时 {response.processing_time_ms:.0f}ms")
        except Exception as e:
            return self._fail("QA 基础问答", str(e))

    def test_qa_no_result(self) -> dict:
        """测试无结果降级回答。"""
        if not self.qa_engine:
            return self._skip("QA 引擎未初始化")
        try:
            response = self.qa_engine.answer("xyzabc123notexist999")
            assert response.answer, "降级回答不能为空"
            return self._pass("QA 无结果降级", response.answer[:50])
        except Exception as e:
            return self._fail("QA 无结果降级", str(e))

    def test_video_locate(self) -> dict:
        """测试视频定位。"""
        if not self.video_locator:
            return self._skip("视频定位器未初始化")
        try:
            segments = self.video_locator.locate("对刀操作")
            assert isinstance(segments, list), "应返回列表"
            return self._pass("视频片段定位", f"找到 {len(segments)} 个片段")
        except Exception as e:
            return self._fail("视频片段定位", str(e))

    def test_code_parse_gcode(self) -> dict:
        """测试 G 代码解析。"""
        if not self.code_parser:
            return self._skip("代码解析器未初始化")
        try:
            gcode = "G90 G21\nG00 X10 Y20\nG01 Z-5 F100\nM30"
            result = self.code_parser.parse(gcode, "gcode")
            assert result["language"] == "gcode"
            assert result["total_lines"] > 0
            return self._pass("G 代码解析", f"解析 {result['total_lines']} 行")
        except Exception as e:
            return self._fail("G 代码解析", str(e))

    def test_fault_diagnosis_flow(self) -> dict:
        """测试故障诊断完整流程。"""
        if not self.fault_diagnosis:
            return self._skip("故障诊断引擎未初始化")
        try:
            import uuid
            sid = str(uuid.uuid4())[:8]
            result = self.fault_diagnosis.start_diagnosis(sid, "加工精度超差")
            assert "next_question" in result, "应有追问"
            return self._pass("故障诊断流程", f"初始匹配 {result.get('initial_matches', 0)} 个案例")
        except Exception as e:
            return self._fail("故障诊断流程", str(e))

    def performance_test(self, iterations: int = 100) -> dict:
        """性能基准测试。"""
        if not self.qa_engine:
            return {"error": "QA 引擎未初始化"}

        times = []
        for i in range(iterations):
            start = time.time()
            self.qa_engine.answer("数控加工精度")
            times.append((time.time() - start) * 1000)

        times.sort()
        return {
            "iterations": iterations,
            "p50_ms": round(times[len(times) // 2], 2),
            "p95_ms": round(times[int(len(times) * 0.95)], 2),
            "p99_ms": round(times[int(len(times) * 0.99)], 2),
            "min_ms": round(times[0], 2),
            "max_ms": round(times[-1], 2),
            "pass_sla": times[int(len(times) * 0.95)] <= 2000,
        }

    def _pass(self, name: str, detail: str = "") -> dict:
        return {"name": name, "status": "passed", "detail": detail}

    def _fail(self, name: str, error: str) -> dict:
        return {"name": name, "status": "failed", "error": error}

    def _skip(self, reason: str) -> dict:
        return {"name": "unknown", "status": "skipped", "reason": reason}
