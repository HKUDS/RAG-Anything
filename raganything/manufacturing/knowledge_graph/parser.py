"""
赛题解析器 — 支持 PDF/Word 赛题文档的结构化提取。

提取流程:
1. 文档解析 (借助 RAG-Anything 多模态解析器)
2. 赛题识别 (基于正则 + 格式特征)
3. 知识点提取 (基于 LLM 的语义分析)
4. 层级树构建

输出: KnowledgeNode 列表 + 层级关系
"""

import re
import logging
from pathlib import Path
from typing import Optional

from .models import KnowledgeNode, ExamQuestion, ScoringRule

logger = logging.getLogger(__name__)


class ExamParser:
    """赛题文档解析器。

    将非结构化赛题文档 (PDF/Word) 转化为结构化的 KnowledgeNode
    和 ExamQuestion 对象，构建知识点层级树。
    """

    # 赛题格式识别模式
    QUESTION_PATTERNS = [
        re.compile(r"^第\s*(\d+)\s*[题、]\s*(.*)"),  # "第1题、..."
        re.compile(r"^(\d+)[\.\、\)]\s*(.+)"),       # "1. ..."
        re.compile(r"^【[题型】]+】\s*(.*)"),         # "【单选题】..."
    ]

    OPTION_PATTERN = re.compile(r"^[A-D][\.\、\)]\s*(.+)")
    ANSWER_PATTERN = re.compile(r"(?:^|\n)\s*(?:答案|参考答案)[：:]\s*([A-D]+)")

    def __init__(self, llm_client=None):
        """初始化解析器。

        Args:
            llm_client: LLM 客户端，用于语义分析和知识点提取。
                       若为 None，仅进行结构化提取。
        """
        self.llm_client = llm_client

    def parse_document(self, file_path: str | Path,
                       competition_track: str = "") -> dict:
        """解析单个赛题文档。

        Args:
            file_path: 赛题文档路径 (PDF/Word)
            competition_track: 所属赛项 track ID

        Returns:
            {"questions": list[ExamQuestion],
             "knowledge_nodes": list[KnowledgeNode],
             "raw_text": str}
        """
        file_path = Path(file_path)
        raw_text = self._extract_text(file_path)
        questions = self._extract_questions(raw_text, competition_track)
        knowledge_nodes = self._extract_knowledge(raw_text, competition_track)

        return {
            "questions": questions,
            "knowledge_nodes": knowledge_nodes,
            "raw_text": raw_text,
        }

    def parse_batch(self, file_paths: list[str | Path],
                    competition_track: str = "") -> list[dict]:
        """批量解析赛题文档。

        Args:
            file_paths: 文档路径列表
            competition_track: 所属赛项

        Returns:
            每份文档的解析结果列表
        """
        results = []
        for fp in file_paths:
            try:
                result = self.parse_document(fp, competition_track)
                results.append({"file": str(fp), "status": "success", **result})
            except Exception as e:
                logger.error(f"解析失败 {fp}: {e}")
                results.append({"file": str(fp), "status": "error", "error": str(e)})
        return results

    def build_knowledge_tree(self, nodes: list[KnowledgeNode]) -> dict:
        """将知识节点构建为层级树结构。

        Args:
            nodes: 知识点节点列表

        Returns:
            层级树 dict: {node_id: {"node": KnowledgeNode, "children": [...]}}
        """
        tree: dict = {}
        node_map = {n.id: n for n in nodes}

        for node in nodes:
            if node.id not in tree:
                tree[node.id] = {"node": node, "children": []}

            # 尝试从 metadata 中提取父子关系
            parent_id = node.metadata.get("parent_id")
            if parent_id and parent_id in node_map:
                if parent_id not in tree:
                    tree[parent_id] = {"node": node_map[parent_id], "children": []}
                tree[parent_id]["children"].append(tree[node.id])

        return tree

    # --- 私有方法 ---

    def _extract_text(self, file_path: Path) -> str:
        """从文档中提取纯文本。

        复用 RAG-Anything 的文档解析能力。
        """
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_from_pdf(file_path)
        elif suffix in (".docx", ".doc"):
            return self._extract_from_docx(file_path)
        elif suffix == ".txt":
            return file_path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"不支持的文件格式: {suffix}")

    def _extract_from_pdf(self, file_path: Path) -> str:
        """从 PDF 提取文本。"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(file_path))
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text
        except ImportError:
            logger.warning("PyMuPDF 未安装，尝试 pdfplumber")
            import pdfplumber
            with pdfplumber.open(str(file_path)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)

    def _extract_from_docx(self, file_path: Path) -> str:
        """从 Word 文档提取文本。"""
        from docx import Document
        doc = Document(str(file_path))
        return "\n".join(p.text for p in doc.paragraphs)

    def _extract_questions(self, text: str, track: str) -> list[ExamQuestion]:
        """从文本中提取赛题列表。"""
        questions = []
        lines = text.split("\n")
        current_question: Optional[ExamQuestion] = None
        current_options: list[str] = []
        question_index = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检测新题目
            for pattern in self.QUESTION_PATTERNS:
                match = pattern.match(line)
                if match:
                    # 保存前一题
                    if current_question:
                        current_question.options = current_options
                        questions.append(current_question)

                    question_index += 1
                    content = match.group(2) if match.lastindex >= 2 else line
                    current_question = ExamQuestion(
                        id=f"{track}_q{question_index:03d}",
                        competition_track=track,
                        question_number=str(question_index),
                        question_type=self._detect_question_type(line),
                        content=content,
                    )
                    current_options = []
                    break
            else:
                # 选项行
                if current_question and self.OPTION_PATTERN.match(line):
                    current_options.append(line)
                # 答案行
                elif current_question:
                    ans_match = self.ANSWER_PATTERN.search(line)
                    if ans_match:
                        current_question.correct_answer = ans_match.group(1)

        # 保存最后一题
        if current_question:
            current_question.options = current_options
            questions.append(current_question)

        return questions

    def _detect_question_type(self, text: str) -> str:
        """根据文本特征检测题型。"""
        if any(kw in text for kw in ["单选", "选择题", "选择"]):
            return "single_choice"
        if any(kw in text for kw in ["多选"]):
            return "multiple_choice"
        if any(kw in text for kw in ["实操", "操作", "编程"]):
            return "practical"
        if any(kw in text for kw in ["简答", "论述", "分析"]):
            return "essay"
        return "unknown"

    def _extract_knowledge(self, text: str, track: str) -> list[KnowledgeNode]:
        """从文本中提取知识点。

        优先使用 LLM 进行语义提取，否则使用关键词匹配降级方案。
        """
        if self.llm_client:
            return self._llm_extract_knowledge(text, track)
        return self._keyword_extract_knowledge(text, track)

    def _llm_extract_knowledge(self, text: str, track: str) -> list[KnowledgeNode]:
        """使用 LLM 提取知识点层次结构。"""
        prompt = f"""从以下赛题文本中提取知识点的层次结构。

赛项: {track}

对于每个知识点，返回:
1. 知识点名称
2. 简要描述 (1-2 句)
3. 父级知识点 (如果有)
4. 难度级别 (1-5)

请以 JSON 格式返回列表。

文本:
{text[:4000]}
"""
        try:
            response = self.llm_client.generate(prompt)
            # 解析 LLM 返回的 JSON
            import json
            knowledge_items = json.loads(response)
            nodes = []
            for item in knowledge_items:
                node = KnowledgeNode(
                    id=f"{track}_k{len(nodes):03d}",
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    node_type="knowledge_point",
                    competition_track=track,
                    difficulty_level=item.get("difficulty", 3),
                    metadata={"parent_id": item.get("parent_id", "")},
                )
                nodes.append(node)
            return nodes
        except Exception as e:
            logger.warning(f"LLM 提取失败，降级到关键词方案: {e}")
            return self._keyword_extract_knowledge(text, track)

    def _keyword_extract_knowledge(self, text: str, track: str) -> list[KnowledgeNode]:
        """关键词降级方案：基于模式匹配提取知识点。"""
        nodes = []
        # 识别标题行作为知识点节点
        heading_pattern = re.compile(r"^[#]{1,3}\s*(.+)", re.MULTILINE)
        headings = heading_pattern.findall(text)

        for i, heading in enumerate(headings):
            node = KnowledgeNode(
                id=f"{track}_k{i:03d}",
                name=heading.strip(),
                description=f"赛项 {track} 知识点：{heading.strip()}",
                node_type="knowledge_point",
                competition_track=track,
                difficulty_level=3,
            )
            nodes.append(node)

        return nodes
