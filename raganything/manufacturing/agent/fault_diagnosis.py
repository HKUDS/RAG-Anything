"""
故障诊断问答模块 — 多轮对话引擎 + 案例匹配 + 置信度评估。

诊断流程:
1. 用户描述故障现象
2. 智能体在案例库中匹配相似案例
3. 通过追问关键信息缩小原因范围
4. 输出诊断结论 + 置信度 + 排除建议
"""

import logging

from ..knowledge_graph.models import (
    ConfidenceLevel,
)

logger = logging.getLogger(__name__)


class FaultDiagnosisEngine:
    """交互式故障诊断引擎。"""

    # 诊断追问模板
    PROBING_QUESTIONS = {
        "加工精度": [
            "误差方向是正偏还是负偏？",
            "加工参数（转速/进给/切深）是多少？",
            "刀具是新刃还是已用过？",
        ],
        "表面质量": [
            "表面粗糙度大约是多少？",
            "是否有振纹或颤纹？",
            "冷却液使用情况如何？",
        ],
        "机械振动": [
            "振动频率是低频还是高频？",
            "振动发生在哪个轴方向？",
            "空载时是否仍有振动？",
        ],
        "电气故障": [
            "报警代码是什么？",
            "故障是间歇性的还是持续性的？",
            "断电重启后故障是否消失？",
        ],
        "default": [
            "故障发生前是否有异常操作？",
            "设备最近一次维护是什么时候？",
            "故障是首次出现还是重复发生？",
        ],
    }

    def __init__(self, case_library=None, llm_client=None,
                 max_dialog_rounds: int = 5,
                 confidence_threshold: float = 0.6):
        """
        Args:
            case_library: FaultCaseLibrary 实例
            llm_client: LLM 客户端
            max_dialog_rounds: 最大对话轮数
            confidence_threshold: 置信度阈值 (低于此值标注建议人工确认)
        """
        self.case_library = case_library
        self.llm_client = llm_client
        self.max_dialog_rounds = max_dialog_rounds
        self.confidence_threshold = confidence_threshold
        self._sessions: dict[str, dict] = {}

    async def start_diagnosis(self, session_id: str,
                        fault_description: str) -> dict:
        """开始诊断会话。

        Args:
            session_id: 会话 ID
            fault_description: 用户的故障描述

        Returns:
            诊断初判 + 第一个追问问题
        """
        # 初始化会话
        self._sessions[session_id] = {
            "fault_description": fault_description,
            "dialog": [{"role": "user", "content": fault_description}],
            "matched_cases": [],
            "round": 0,
        }

        # 匹配初始案例
        cases = await self._match_cases(fault_description)
        self._sessions[session_id]["matched_cases"] = cases

        # 生成追问
        next_question = self._generate_probing_question(fault_description, cases)

        return {
            "session_id": session_id,
            "initial_matches": len(cases),
            "next_question": next_question,
            "matched_cases": cases[:3],  # Top 3 for preview
        }

    async def continue_diagnosis(self, session_id: str,
                           user_answer: str) -> dict:
        """继续诊断对话。

        Args:
            session_id: 会话 ID
            user_answer: 用户对追问的回答

        Returns:
            更新后的诊断结果
        """
        session = self._sessions.get(session_id)
        if not session:
            return {"error": "会话不存在", "session_id": session_id}

        session["dialog"].append({"role": "user", "content": user_answer})
        session["round"] += 1

        # 根据新信息重新匹配案例
        full_context = self._build_context(session)
        cases = await self._match_cases(full_context)
        session["matched_cases"] = cases

        # 判断是否可以给出结论
        confidence = self._calculate_confidence(cases)
        can_conclude = (
            session["round"] >= self.max_dialog_rounds or
            confidence >= 0.8 or
            (cases and len(cases) <= 3)
        )

        if can_conclude:
            result = self._build_diagnosis(session, cases, confidence)
            del self._sessions[session_id]
            return result

        # 继续追问
        next_question = self._generate_probing_question(full_context, cases)
        return {
            "session_id": session_id,
            "round": session["round"],
            "matched_cases_count": len(cases),
            "next_question": next_question,
            "current_confidence": round(confidence, 2),
        }

    async def _match_cases(self, query: str) -> list[dict]:
        """在案例库中匹配案例。"""
        if not self.case_library:
            return []
        try:
            result = await self.case_library.search(query, top_k=10)
            if not isinstance(result, list):
                logger.warning(f"案例搜索返回非列表类型 {type(result)}，已忽略")
                return []
            # 过滤非 dict 元素
            return [r for r in result if isinstance(r, dict)]
        except Exception as e:
            logger.error(f"案例搜索失败: {e}")
            return []

    def _generate_probing_question(self, description: str,
                                   cases: list[dict]) -> str:
        """基于症状和案例生成追问。"""
        # 从案例中提取关键信息点
        key_topics = set()
        for case in cases[:5]:
            key_topics.update(self._extract_topics(case.get("phenomenon", "")))

        # 匹配预设追问模板
        questions = []
        for topic, qs in self.PROBING_QUESTIONS.items():
            if topic in description or any(topic in desc.lower() for desc in key_topics):
                questions.extend(qs)

        if not questions:
            questions = self.PROBING_QUESTIONS["default"]

        # 用 LLM 生成更精准的追问
        if self.llm_client:
            return self._llm_probing_question(description, cases, questions[0])

        return questions[0]

    def _llm_probing_question(self, description: str,
                              cases: list[dict],
                              fallback: str) -> str:
        try:
            prompt = f"""你是一位设备故障诊断专家。用户描述了以下故障：

{description}

当前匹配到 {len(cases)} 个相似案例。请生成一个精准的追问问题来缩小故障原因范围。
只返回问题本身，不要其他内容。"""

            return self.llm_client.generate(prompt).strip()
        except Exception:
            return fallback

    def _build_context(self, session: dict) -> str:
        """构建完整的诊断上下文。"""
        parts = []
        for msg in session["dialog"]:
            role = "用户" if msg["role"] == "user" else "系统"
            parts.append(f"{role}: {msg['content']}")
        return "\n".join(parts)

    def _calculate_confidence(self, cases: list[dict]) -> float:
        """根据案例匹配度计算置信度。"""
        if not cases:
            return 0.0
        scores = [c.get("score", 0.5) for c in cases]
        avg = sum(scores) / len(scores)
        # 案例越少且分数越集中，置信度越高
        concentration = 1.0 / (1.0 + len(cases) * 0.1)
        return min(avg * 0.7 + concentration * 0.3, 1.0)

    def _build_diagnosis(self, session: dict,
                         cases: list[dict],
                         confidence: float) -> dict:
        """构建最终诊断结果。"""
        possible_causes = []
        for case in cases[:5]:
            possible_causes.append({
                "description": case.get("root_cause", case.get("phenomenon", "")),
                "confidence": round(case.get("score", 0.5), 2),
                "matched_case_id": case.get("id", ""),
                "matched_case_title": case.get("title", ""),
            })

        actions = []
        for case in cases[:3]:
            actions.extend(case.get("troubleshooting_steps", []))

        needs_review = confidence < self.confidence_threshold

        return {
            "diagnosis": {
                "possible_causes": possible_causes,
                "recommended_actions": list(dict.fromkeys(actions))[:10],
                "confidence": round(confidence, 2),
                "confidence_level": (
                    ConfidenceLevel.HIGH.value if confidence >= 0.8
                    else ConfidenceLevel.MEDIUM.value if confidence >= 0.6
                    else ConfidenceLevel.LOW.value
                ),
                "needs_human_review": needs_review,
                "total_matched_cases": len(cases),
                "dialog_rounds": session["round"],
            },
            "dialog_history": session["dialog"],
        }

    @staticmethod
    def _extract_topics(text: str) -> set[str]:
        topics = set()
        for topic in ["精度", "振动", "表面", "温度", "噪声", "电气", "液压", "气动"]:
            if topic in text:
                topics.add(topic)
        return topics
