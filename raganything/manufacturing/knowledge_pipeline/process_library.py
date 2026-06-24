"""
企业工艺库 — 工艺文档自动分类、参数提取、多维检索。
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# 工艺类型分类关键词
PROCESS_CATEGORIES = {
    "machining": ["车削", "铣削", "磨削", "钻孔", "镗削", "切削", "加工中心"],
    "welding": ["焊接", "电弧焊", "气焊", "激光焊", "钎焊", "焊缝"],
    "assembly": ["装配", "组装", "配合", "间隙", "过盈", "紧固"],
    "inspection": ["检测", "测量", "检验", "探伤", "三坐标", "公差"],
    "heat_treatment": ["热处理", "淬火", "回火", "退火", "正火", "渗碳"],
    "casting": ["铸造", "浇注", "砂型", "熔模", "压铸"],
    "forming": ["冲压", "锻造", "挤压", "拉拔", "轧制"],
}

# 工艺参数提取模式
PARAM_PATTERNS = [
    re.compile(r"([一-龥]+参数|[A-Za-z]+)\s*[：:]\s*([\d.]+)\s*([一-龥A-Za-z/%℃]+)"),
    re.compile(r"([\d.]+)\s*-\s*([\d.]+)\s*mm"),
    re.compile(r"转速[：:]\s*(\d+)\s*rpm"),
    re.compile(r"进给[：:]\s*([\d.]+)\s*mm"),
]


class ProcessLibrary:
    """企业工艺知识库。"""

    def __init__(self, storage_path: str | Path = "./data/manufacturing_kb/processes"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, dict] = {}
        self._load_index()

    def ingest_document(self, file_path: str | Path) -> dict:
        """录入工艺文档。

        Returns:
            处理结果: {"id", "category", "parameters", "metadata"}
        """
        file_path = Path(file_path)
        text = file_path.read_text(encoding="utf-8")

        category = self._classify_process(text)
        params = self._extract_parameters(text)
        doc_id = f"proc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file_path.stem}"

        entry = {
            "id": doc_id,
            "title": file_path.stem,
            "category": category,
            "parameters": params,
            "file_path": str(file_path.absolute()),
            "file_size_bytes": file_path.stat().st_size,
            "ingested_at": datetime.now().isoformat(),
            "text_preview": text[:500],
        }

        self._index[doc_id] = entry
        self._persist_index()
        return entry

    def search(self, query: str, category: str = "",
               limit: int = 20) -> list[dict]:
        """多维检索工艺文档。

        Args:
            query: 搜索关键词
            category: 按工艺类别筛选
            limit: 返回数量

        Returns:
            匹配的工艺条目列表
        """
        results = []
        query_lower = query.lower()

        for entry in self._index.values():
            if category and entry.get("category") != category:
                continue

            score = 0
            # 标题匹配
            if query_lower in entry.get("title", "").lower():
                score += 10
            # 文本匹配
            text = entry.get("text_preview", "")
            if query_lower in text.lower():
                score += 5
            # 参数匹配
            for param in entry.get("parameters", []):
                if query_lower in param.get("name", "").lower():
                    score += 3

            if score > 0:
                results.append({**entry, "relevance_score": score})

        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results[:limit]

    def list_by_category(self) -> dict[str, int]:
        """按工艺类别统计文档数量。"""
        counts: dict[str, int] = {}
        for entry in self._index.values():
            cat = entry.get("category", "unknown")
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    # ── CRUD ──────────────────────────────────────────

    def get_document(self, doc_id: str) -> dict | None:
        """获取单个工艺文档。"""
        return self._index.get(doc_id)

    def add_document(self, data: dict) -> str:
        """从结构化数据添加工艺文档（不从文件读取）。

        ``data`` 必须包含 ``title`` 和 ``text`` 字段。
        """
        title = data.get("title", "").strip()
        text = data.get("text", "").strip()
        if not title:
            raise ValueError("工艺文档标题不能为空")
        if not text:
            raise ValueError("工艺文档内容不能为空")

        category = data.get("category") or self._classify_process(text)
        params = self._extract_parameters(text)
        doc_id = f"proc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{title[:20]}"

        entry = {
            "id": doc_id,
            "title": title,
            "category": category,
            "parameters": params,
            "file_path": data.get("file_path", ""),
            "file_size_bytes": data.get("file_size_bytes", 0),
            "ingested_at": datetime.now().isoformat(),
            "text_preview": text[:500],
            "full_text": text,
        }
        self._index[doc_id] = entry
        self._persist_index()
        return doc_id

    def update_document(self, doc_id: str, updates: dict) -> bool:
        """更新工艺文档。返回是否成功。"""
        entry = self._index.get(doc_id)
        if not entry:
            return False
        # Allowed update fields
        for field in ("title", "category", "text_preview", "full_text"):
            if field in updates and updates[field] is not None:
                entry[field] = updates[field]
        # Re-classify if text content changed
        if "full_text" in updates and updates["full_text"]:
            entry["category"] = self._classify_process(updates["full_text"])
            entry["parameters"] = self._extract_parameters(updates["full_text"])
        self._persist_index()
        return True

    def delete_document(self, doc_id: str) -> bool:
        """删除工艺文档。返回是否成功。"""
        if doc_id not in self._index:
            return False
        del self._index[doc_id]
        self._persist_index()
        return True

    # ── Internal ──────────────────────────────────────

    def _classify_process(self, text: str) -> str:
        """根据关键词自动分类工艺类型。"""
        scores = {}
        for cat, keywords in PROCESS_CATEGORIES.items():
            scores[cat] = sum(1 for kw in keywords if kw in text)
        if not scores or max(scores.values()) == 0:
            return "general"
        return max(scores, key=scores.get)

    def _extract_parameters(self, text: str) -> list[dict]:
        """从工艺文本中提取参数表。"""
        params = []
        for pattern in PARAM_PATTERNS:
            matches = pattern.findall(text)
            for match in matches:
                if len(match) >= 2:
                    params.append({
                        "name": match[0] if match[0] else "",
                        "value": match[1] if len(match) > 1 else "",
                        "unit": match[2] if len(match) > 2 else "",
                    })
        return params

    def _persist_index(self) -> None:
        """持久化索引。"""
        index_path = self.storage_path / "_index.json"
        index_path.write_text(
            json.dumps(list(self._index.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_index(self) -> None:
        """从磁盘加载已有索引（防止重启丢数据）。"""
        index_path = self.storage_path / "_index.json"
        if not index_path.exists():
            return
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            for entry in data:
                doc_id = entry.get("id")
                if doc_id:
                    self._index[doc_id] = entry
            logger.info(f"Loaded {len(self._index)} process documents from {index_path}")
        except Exception as e:
            logger.warning(f"Failed to load process index: {e}")
