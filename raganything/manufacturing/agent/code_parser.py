"""
代码解析器 — 支持 G 代码、PLC 指令表的结构化分析。

功能:
- G 代码: 语法高亮、行号标注、功能解释、刀具路径描述、风险标注
- PLC 指令表: 逻辑流程解析、I/O 信号对应、常见逻辑错误识别
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CodeParser:
    """智能制造领域代码解析器。"""

    # G 代码常见指令
    GCODE_INFO = {
        "G00": "快速定位 (Rapid positioning)",
        "G01": "直线插补 (Linear interpolation)",
        "G02": "顺时针圆弧插补 (CW circular)",
        "G03": "逆时针圆弧插补 (CCW circular)",
        "G04": "暂停 (Dwell)",
        "G17": "XY 平面选择",
        "G18": "XZ 平面选择",
        "G19": "YZ 平面选择",
        "G20": "英制单位",
        "G21": "公制单位",
        "G40": "取消刀具补偿",
        "G41": "左刀补",
        "G42": "右刀补",
        "G90": "绝对坐标",
        "G91": "增量坐标",
        "M03": "主轴正转",
        "M05": "主轴停止",
        "M06": "换刀",
        "M30": "程序结束",
    }

    # 风险检测模式
    RISK_PATTERNS = [
        (re.compile(r"G00.*Z\s*-\d", re.IGNORECASE), "🔴 快速定位直接进入工件 — 可能撞刀"),
        (re.compile(r"(?<!G4[012])G0[01].*\n(?!.*G0[01])", re.IGNORECASE), "🟡 未启用刀具补偿"),
        (re.compile(r"M03.*S(\d+)", re.IGNORECASE), None),  # 无风险，仅记录
    ]

    def parse(self, code: str, language: str = "gcode") -> dict:
        """解析代码。

        Args:
            code: 源代码文本
            language: 语言类型 (gcode / plc_instruction_list / ladder_diagram)

        Returns:
            {"language", "lines": [...], "summary": str, "risks": [...]}
        """
        if language == "gcode":
            return self._parse_gcode(code)
        elif language in ("plc_instruction_list", "plc"):
            return self._parse_plc(code)
        else:
            return {"error": f"不支持的语言类型: {language}", "language": language}

    def parse_file(self, file_path: str) -> dict:
        """从文件解析代码。"""
        from pathlib import Path
        path = Path(file_path)
        code = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()

        lang_map = {
            ".gcode": "gcode", ".nc": "gcode", ".txt": "gcode",
            ".plc": "plc_instruction_list",
        }
        language = lang_map.get(suffix, "gcode")
        return self.parse(code, language)

    def _parse_gcode(self, code: str) -> dict:
        """解析 G 代码。"""
        lines = []
        risks = []
        tool_changes = 0
        current_tool = None

        for line_num, raw_line in enumerate(code.strip().split("\n"), 1):
            line = raw_line.strip()
            if not line or line.startswith(("(", ";", "%")):
                lines.append({
                    "line_number": line_num,
                    "code": line,
                    "type": "comment_or_meta",
                    "explanation": "注释/程序头",
                })
                continue

            # 识别 G/M 指令
            gcodes = re.findall(r"G\d{2}", line)
            mcode_match = re.search(r"(M\d{2})", line)
            explanation = self._explain_gcode_line(line, gcodes, mcode_match)

            # 刀具路径
            toolpath = None
            if any(g in gcodes for g in ("G00", "G01", "G02", "G03")):
                coords = re.findall(r"([XYZ])\s*(-?[\d.]+)", line)
                if coords:
                    toolpath = {axis: float(val) for axis, val in coords}

            # 换刀检测
            if mcode_match and mcode_match.group(1) == "M06":
                tool_changes += 1

            # 风险检测
            for pattern, risk_msg in self.RISK_PATTERNS:
                if risk_msg and pattern.search(line):
                    risks.append({
                        "line": line_num,
                        "code": line,
                        "risk": risk_msg,
                    })

            lines.append({
                "line_number": line_num,
                "code": line,
                "type": "gcode_command",
                "g_codes": gcodes,
                "m_code": mcode_match.group(1) if mcode_match else None,
                "explanation": explanation,
                "toolpath": toolpath,
            })

        return {
            "language": "gcode",
            "total_lines": len(lines),
            "lines": lines,
            "summary": self._summarize_gcode(lines, tool_changes, risks),
            "risks": risks,
            "risk_count": len(risks),
        }

    def _parse_plc(self, code: str) -> dict:
        """解析 PLC 指令表程序。"""
        lines = []
        io_signals = {"inputs": [], "outputs": []}
        logic_issues = []

        for line_num, raw_line in enumerate(code.strip().split("\n"), 1):
            line = raw_line.strip()
            if not line or line.startswith(("//", "#", ";")):
                lines.append({"line_number": line_num, "code": line, "type": "comment"})
                continue

            # 提取 I/O 信号
            inputs = re.findall(r"[IX]\d+\.?\d*", line)
            outputs = re.findall(r"[QY]\d+\.?\d*", line)

            if inputs:
                io_signals["inputs"].extend(inputs)
            if outputs:
                io_signals["outputs"].extend(outputs)

            # 常见逻辑错误检测
            if "SET" in line and "RST" in line:
                logic_issues.append({
                    "line": line_num,
                    "issue": "SET 和 RST 同时作用于同一 rung — 可能导致不可预测行为",
                })

            lines.append({
                "line_number": line_num,
                "code": line,
                "type": "instruction",
                "inputs": inputs,
                "outputs": outputs,
                "mnemonic": line.split()[0] if line.split() else "",
            })

        return {
            "language": "plc_instruction_list",
            "total_lines": len(lines),
            "lines": lines,
            "io_signals": {
                "inputs": list(set(io_signals["inputs"])),
                "outputs": list(set(io_signals["outputs"])),
            },
            "logic_issues": logic_issues,
            "issue_count": len(logic_issues),
        }

    def _explain_gcode_line(self, line: str,
                            gcodes: list[str],
                            mcode_match) -> str:
        explanations = []
        for g in gcodes:
            if g in self.GCODE_INFO:
                explanations.append(f"{g}: {self.GCODE_INFO[g]}")
        if mcode_match:
            m = mcode_match.group(1)
            if m in self.GCODE_INFO:
                explanations.append(f"{m}: {self.GCODE_INFO[m]}")
        return "; ".join(explanations) if explanations else "—"

    def _summarize_gcode(self, lines: list[dict],
                         tool_changes: int,
                         risks: list[dict]) -> str:
        g_codes = set()
        for l in lines:
            g_codes.update(l.get("g_codes", []))
        return (
            f"共 {len(lines)} 行 G 代码，"
            f"使用 {len(g_codes)} 种指令，"
            f"换刀 {tool_changes} 次，"
            f"发现 {len(risks)} 个潜在风险。"
        )
