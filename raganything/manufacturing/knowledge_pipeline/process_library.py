"""
企业工艺库 — PG-backed (Phase 3 migration).

Primary: PostgreSQL ``process_documents`` table.
Fallback: JSON file (``_index.json``) when PG not configured.
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


def _pg_available() -> bool:
    try:
        from raganything.services.pg_state_repo import get_pg_pool
        get_pg_pool()
        return True
    except RuntimeError:
        return False


async def _pg_pool():
    from raganything.services.pg_state_repo import get_pg_pool
    return get_pg_pool()


class ProcessLibrary:
    """企业工艺知识库 — PG-first with JSON file fallback."""

    def __init__(self, storage_path: str | Path = "./data/manufacturing_kb/processes"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, dict] = {}
        self._use_pg: bool | None = None

    async def _ensure_init(self):
        if self._use_pg is not None:
            return
        self._use_pg = _pg_available()
        if not self._use_pg:
            self._load_index()
        logger.info(f"[process-lib] {'PG' if self._use_pg else 'File'} backend active")

    # ── CRUD ──────────────────────────────────────────

    async def ingest_document(self, file_path: str | Path) -> dict:
        """录入工艺文档。"""
        file_path = Path(file_path)
        text = file_path.read_text(encoding="utf-8")
        category = self._classify_process(text)
        params = self._extract_parameters(text)
        doc_id = f"proc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file_path.stem}"

        await self._ensure_init()

        entry = {
            "id": doc_id, "title": file_path.stem, "category": category,
            "parameters": params, "file_path": str(file_path.absolute()),
            "file_size_bytes": file_path.stat().st_size,
            "ingested_at": datetime.now().isoformat(),
            "text_preview": text[:500], "full_text": text,
        }

        if self._use_pg:
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO process_documents
                       (id, title, category, parameters, file_path,
                        file_size_bytes, text_preview, full_text)
                       VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8)""",
                    doc_id, entry["title"], category,
                    json.dumps(params, ensure_ascii=False),
                    str(file_path.absolute()), file_path.stat().st_size,
                    text[:500], text,
                )
            return entry

        self._index[doc_id] = entry
        self._persist_index()
        return entry

    async def search(self, query: str, category: str = "", limit: int = 20) -> list[dict]:
        """多维检索工艺文档。"""
        await self._ensure_init()

        if self._use_pg:
            pool = await _pg_pool()
            q = f"%{query}%"
            async with pool.acquire() as conn:
                if category:
                    rows = await conn.fetch(
                        """SELECT id, title, category, parameters, text_preview,
                           file_path, file_size_bytes, ingested_at
                           FROM process_documents
                           WHERE category = $1
                             AND (title ILIKE $2 OR text_preview ILIKE $2)
                           ORDER BY ingested_at DESC LIMIT $3""",
                        category, q, limit,
                    )
                else:
                    rows = await conn.fetch(
                        """SELECT id, title, category, parameters, text_preview,
                           file_path, file_size_bytes, ingested_at
                           FROM process_documents
                           WHERE title ILIKE $1 OR text_preview ILIKE $1
                           ORDER BY ingested_at DESC LIMIT $2""",
                        q, limit,
                    )
            results = []
            for r in rows:
                params = r["parameters"]
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except Exception:
                        params = []
                results.append({
                    "id": r["id"], "title": r["title"],
                    "category": r["category"], "parameters": params,
                    "text_preview": r["text_preview"],
                    "file_path": r.get("file_path", ""),
                    "file_size_bytes": r.get("file_size_bytes", 0),
                    "ingested_at": r["ingested_at"].isoformat()
                        if hasattr(r["ingested_at"], 'isoformat')
                        else str(r.get("ingested_at", "")),
                    "relevance_score": 10,
                })
            return results

        # File fallback
        results = []
        query_lower = query.lower()
        for entry in self._index.values():
            if category and entry.get("category") != category:
                continue
            score = 0
            if query_lower in entry.get("title", "").lower():
                score += 10
            text = entry.get("text_preview", "")
            if query_lower in text.lower():
                score += 5
            for param in entry.get("parameters", []):
                if query_lower in param.get("name", "").lower():
                    score += 3
            if score > 0:
                results.append({**entry, "relevance_score": score})
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results[:limit]

    async def list_by_category(self) -> dict[str, int]:
        """按工艺类别统计文档数量。"""
        await self._ensure_init()
        if self._use_pg:
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT category, count(*) as cnt FROM process_documents "
                    "GROUP BY category"
                )
            return {r["category"]: r["cnt"] for r in rows}

        counts: dict[str, int] = {}
        for entry in self._index.values():
            cat = entry.get("category", "unknown")
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    async def get_document(self, doc_id: str) -> dict | None:
        """获取单个工艺文档。"""
        await self._ensure_init()
        if self._use_pg:
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM process_documents WHERE id = $1", doc_id,
                )
            if row:
                r = dict(row)
                params = r.get("parameters")
                if isinstance(params, str):
                    try:
                        r["parameters"] = json.loads(params)
                    except Exception:
                        r["parameters"] = []
                if hasattr(r.get("ingested_at"), 'isoformat'):
                    r["ingested_at"] = r["ingested_at"].isoformat()
                return r
            return None
        return self._index.get(doc_id)

    async def add_document(self, data: dict) -> str:
        """从结构化数据添加工艺文档。"""
        title = data.get("title", "").strip()
        text = data.get("text", "").strip()
        if not title:
            raise ValueError("工艺文档标题不能为空")
        if not text:
            raise ValueError("工艺文档内容不能为空")

        category = data.get("category") or self._classify_process(text)
        params = self._extract_parameters(text)
        doc_id = f"proc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{title[:20]}"

        await self._ensure_init()

        entry = {
            "id": doc_id, "title": title, "category": category,
            "parameters": params, "file_path": data.get("file_path", ""),
            "file_size_bytes": data.get("file_size_bytes", 0),
            "ingested_at": datetime.now().isoformat(),
            "text_preview": text[:500], "full_text": text,
        }

        if self._use_pg:
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO process_documents
                       (id, title, category, parameters, file_path,
                        file_size_bytes, text_preview, full_text)
                       VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8)""",
                    doc_id, title, category,
                    json.dumps(params, ensure_ascii=False),
                    data.get("file_path", ""), data.get("file_size_bytes", 0),
                    text[:500], text,
                )
            return doc_id

        self._index[doc_id] = entry
        self._persist_index()
        return doc_id

    async def update_document(self, doc_id: str, updates: dict) -> bool:
        """更新工艺文档。"""
        await self._ensure_init()
        if self._use_pg:
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                existing = await conn.fetchrow(
                    "SELECT * FROM process_documents WHERE id = $1", doc_id,
                )
                if not existing:
                    return False
                new_title = updates.get("title", existing["title"])
                new_full_text = updates.get("full_text", existing["full_text"])
                new_category = self._classify_process(new_full_text) \
                    if "full_text" in updates else existing["category"]
                new_params = self._extract_parameters(new_full_text) \
                    if "full_text" in updates else existing["parameters"]
                new_text_preview = new_full_text[:500] \
                    if "full_text" in updates else existing["text_preview"]

                await conn.execute(
                    """UPDATE process_documents SET
                       title=$1, category=$2, parameters=$3::jsonb,
                       text_preview=$4, full_text=$5, updated_at=NOW()
                       WHERE id=$6""",
                    new_title, new_category,
                    json.dumps(new_params, ensure_ascii=False),
                    new_text_preview, new_full_text, doc_id,
                )
            return True

        entry = self._index.get(doc_id)
        if not entry:
            return False
        for field in ("title", "category", "text_preview", "full_text"):
            if field in updates and updates[field] is not None:
                entry[field] = updates[field]
        if "full_text" in updates and updates["full_text"]:
            entry["category"] = self._classify_process(updates["full_text"])
            entry["parameters"] = self._extract_parameters(updates["full_text"])
        self._persist_index()
        return True

    async def delete_document(self, doc_id: str) -> bool:
        """删除工艺文档。"""
        await self._ensure_init()
        if self._use_pg:
            pool = await _pg_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM process_documents WHERE id = $1", doc_id,
                )
            return result and "DELETE 0" not in result

        if doc_id not in self._index:
            return False
        del self._index[doc_id]
        self._persist_index()
        return True

    # ── Internal ──────────────────────────────────────

    def _classify_process(self, text: str) -> str:
        scores = {}
        for cat, keywords in PROCESS_CATEGORIES.items():
            scores[cat] = sum(1 for kw in keywords if kw in text)
        if not scores or max(scores.values()) == 0:
            return "general"
        return max(scores, key=scores.get)

    def _extract_parameters(self, text: str) -> list[dict]:
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
        index_path = self.storage_path / "_index.json"
        index_path.write_text(
            json.dumps(list(self._index.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_index(self) -> None:
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
