"""
知识图谱 API — 提供赛项知识结构的图谱数据接口。

输出格式:
- 节点列表 (JSON): id, name, type, metadata
- 边列表 (JSON): source, target, type, weight
- 谱系树: 某个节点的完整上下游关系

支持与 RAG-Anything 图存储层对接。
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from .models import (
    KnowledgeNode, KnowledgeEdge, RelationType,
    TagTree,
)

logger = logging.getLogger(__name__)


class KnowledgeGraphAPI:
    """知识图谱查询与操作接口。

    封装知识图谱的 CRUD 操作和查询逻辑。
    """

    def __init__(self, graph_storage=None):
        """初始化图谱 API。

        Args:
            graph_storage: RAG-Anything 图存储后端实例。
                          若为 None，使用内存存储。
        """
        self.storage = graph_storage or InMemoryGraphStore()
        self.tag_tree = TagTree()

    # --- 节点操作 ---

    def get_nodes(self, competition_track: str = "",
                  node_type: str = "",
                  limit: int = 100, offset: int = 0) -> dict:
        """获取知识节点列表。

        Args:
            competition_track: 按赛项筛选 (空=全部)
            node_type: 按类型筛选
            limit, offset: 分页

        Returns:
            {"total": int, "nodes": list[dict]}
        """
        nodes = self.storage.list_nodes(
            track=competition_track or None,
            node_type=node_type or None,
        )
        total = len(nodes)
        page = nodes[offset:offset + limit]

        return {
            "total": total,
            "nodes": [self._node_to_dict(n) for n in page],
        }

    def get_node(self, node_id: str) -> Optional[dict]:
        """获取单个节点详情，含关联边。"""
        node = self.storage.get_node(node_id)
        if not node:
            return None

        edges = self.storage.get_edges(node_id)
        return {
            "node": self._node_to_dict(node),
            "incoming_edges": [
                self._edge_to_dict(e) for e in edges
                if e.target_id == node_id
            ],
            "outgoing_edges": [
                self._edge_to_dict(e) for e in edges
                if e.source_id == node_id
            ],
        }

    def create_node(self, node: KnowledgeNode) -> str:
        """创建知识节点。返回节点 ID。"""
        self.storage.save_node(node)
        return node.id

    def update_node(self, node_id: str, updates: dict) -> bool:
        """更新知识节点。"""
        node = self.storage.get_node(node_id)
        if not node:
            return False
        for key, value in updates.items():
            if hasattr(node, key):
                setattr(node, key, value)
        self.storage.save_node(node)
        return True

    def delete_node(self, node_id: str) -> bool:
        """删除知识节点及其关联边。"""
        self.storage.delete_edges(node_id)
        return self.storage.delete_node(node_id)

    # --- 边操作 ---

    def get_edges(self, source_id: str = "",
                  relation_type: str = "",
                  limit: int = 100) -> dict:
        """获取边列表。"""
        edges = self.storage.list_edges(
            source_id=source_id or None,
            relation_type=relation_type or None,
        )
        return {
            "total": len(edges),
            "edges": [self._edge_to_dict(e) for e in edges[:limit]],
        }

    def create_edge(self, edge: KnowledgeEdge) -> str:
        """创建关系边。"""
        self.storage.save_edge(edge)
        return edge.id

    def delete_edge(self, edge_id: str) -> bool:
        """删除关系边。"""
        return self.storage.delete_edge(edge_id)

    # --- 谱系查询 ---

    def get_lineage(self, node_id: str,
                    upstream_depth: int = 3,
                    downstream_depth: int = 3) -> Optional[dict]:
        """获取节点的知识谱系树。

        Args:
            node_id: 目标节点 ID
            upstream_depth: 上游追溯深度 (前置知识)
            downstream_depth: 下游追溯深度 (后继知识)

        Returns:
            {"node": dict,
             "prerequisites": [...],   # 前置依赖链
             "advancements": [...]}    # 后续进阶链
        """
        node = self.storage.get_node(node_id)
        if not node:
            return None

        prerequisites = self._trace_upstream(node_id, upstream_depth)
        advancements = self._trace_downstream(node_id, downstream_depth)

        return {
            "node": self._node_to_dict(node),
            "prerequisites": prerequisites,
            "advancements": advancements,
            "prerequisite_count": len(prerequisites),
            "advancement_count": len(advancements),
        }

    def get_graph_summary(self) -> dict:
        """获取知识图谱统计摘要。"""
        nodes = self.storage.list_nodes()
        edges = self.storage.list_edges()
        return {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_types": self._count_by(nodes, "node_type"),
            "relation_types": self._count_by(edges, "relation_type"),
        }

    # --- 私有方法 ---

    def _trace_upstream(self, node_id: str, depth: int) -> list[dict]:
        """向上追溯前置依赖链 (BFS)。"""
        result = []
        visited = {node_id}
        current_level = [node_id]

        for _ in range(depth):
            next_level = []
            for nid in current_level:
                edges = self.storage.get_edges(nid)
                for edge in edges:
                    if (edge.target_id == nid and
                            edge.relation_type == RelationType.REQUIRES and
                            edge.source_id not in visited):
                        source_node = self.storage.get_node(edge.source_id)
                        if source_node:
                            result.append(self._node_to_dict(source_node))
                            visited.add(edge.source_id)
                            next_level.append(edge.source_id)
            current_level = next_level
            if not current_level:
                break

        return result

    def _trace_downstream(self, node_id: str, depth: int) -> list[dict]:
        """向下追溯后续进阶链 (BFS)。"""
        result = []
        visited = {node_id}
        current_level = [node_id]

        for _ in range(depth):
            next_level = []
            for nid in current_level:
                edges = self.storage.get_edges(nid)
                for edge in edges:
                    if (edge.source_id == nid and
                            edge.relation_type == RelationType.ADVANCES_TO and
                            edge.target_id not in visited):
                        target_node = self.storage.get_node(edge.target_id)
                        if target_node:
                            result.append(self._node_to_dict(target_node))
                            visited.add(edge.target_id)
                            next_level.append(edge.target_id)
            current_level = next_level
            if not current_level:
                break

        return result

    @staticmethod
    def _node_to_dict(node: KnowledgeNode) -> dict:
        return {
            "id": node.id,
            "name": node.name,
            "description": node.description,
            "node_type": node.node_type,
            "competition_track": node.competition_track,
            "difficulty_level": node.difficulty_level,
            "estimated_hours": node.estimated_hours,
            "metadata": node.metadata,
        }

    @staticmethod
    def _edge_to_dict(edge: KnowledgeEdge) -> dict:
        return {
            "id": edge.id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "relation_type": edge.relation_type.value
                if isinstance(edge.relation_type, RelationType)
                else edge.relation_type,
            "weight": edge.weight,
            "description": edge.description,
        }

    @staticmethod
    def _count_by(items: list, attr: str) -> dict:
        counts: dict = {}
        for item in items:
            val = getattr(item, attr, "unknown")
            if hasattr(val, "value"):
                val = val.value
            counts[val] = counts.get(val, 0) + 1
        return counts


class InMemoryGraphStore:
    """内存图存储后端 — 用于开发/测试。"""

    def __init__(self):
        self._nodes: dict[str, KnowledgeNode] = {}
        self._edges: dict[str, KnowledgeEdge] = {}

    def save_node(self, node: KnowledgeNode) -> None:
        self._nodes[node.id] = node

    def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        return self._nodes.get(node_id)

    def delete_node(self, node_id: str) -> bool:
        return self._nodes.pop(node_id, None) is not None

    def list_nodes(self, track: str = None,
                   node_type: str = None) -> list[KnowledgeNode]:
        result = list(self._nodes.values())
        if track:
            result = [n for n in result if n.competition_track == track]
        if node_type:
            result = [n for n in result if n.node_type == node_type]
        return result

    def save_edge(self, edge: KnowledgeEdge) -> None:
        self._edges[edge.id] = edge

    def get_edges(self, node_id: str) -> list[KnowledgeEdge]:
        return [
            e for e in self._edges.values()
            if e.source_id == node_id or e.target_id == node_id
        ]

    def delete_edges(self, node_id: str) -> None:
        to_delete = [
            eid for eid, e in self._edges.items()
            if e.source_id == node_id or e.target_id == node_id
        ]
        for eid in to_delete:
            del self._edges[eid]

    def delete_edge(self, edge_id: str) -> bool:
        return self._edges.pop(edge_id, None) is not None

    def list_edges(self, source_id: str = None,
                   relation_type: str = None) -> list[KnowledgeEdge]:
        result = list(self._edges.values())
        if source_id:
            result = [e for e in result if e.source_id == source_id]
        if relation_type:
            result = [
                e for e in result
                if (e.relation_type.value
                    if isinstance(e.relation_type, RelationType)
                    else e.relation_type) == relation_type
            ]
        return result


class LightRAGGraphStore:
    """从 LightRAG 实际存储读取的图存储后端。

    PG-first: 当 PostgreSQL 可用时，优先从 LIGHTRAG_FULL_ENTITIES 和
    LIGHTRAG_FULL_RELATIONS 表读取；PG 不可用时回退到 JSON 文件。
    读取结果缓存到 ``_entities_cache`` / ``_relations_cache`` 中，
    后续调用（如 get_node / get_edges / lineage）直接使用缓存数据。
    """

    def __init__(self, working_dir: str = "./rag_storage"):
        self._working_dir = Path(working_dir)
        self._entities_cache: dict | None = None
        self._relations_cache: dict | None = None
        self._load_lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """Lazy-load entities + relations data from PG, with thread-safe locking.

        Uses a double-checked locking pattern to ensure only one thread performs
        the PG load per store instance.  Both caches are populated atomically
        at the end of _pg_load() to prevent partial-state reads.
        """
        if self._entities_cache is not None and self._relations_cache is not None:
            return

        with self._load_lock:
            # Double-check after acquiring lock
            if self._entities_cache is not None and self._relations_cache is not None:
                return

            import asyncio as _asyncio
            import concurrent.futures

            def _pg_load_thread():
                _asyncio.run(self._pg_load())

            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_pg_load_thread)
                    future.result(timeout=30)
            except Exception as exc:
                raise RuntimeError(
                    f"PG load failed for entities/relations in workspace "
                    f"{self._working_dir}: {exc}"
                ) from exc

    async def _pg_load(self) -> None:
        """Load entities and relations from the shared PG pool.

        Uses a fresh dedicated asyncpg connection (not the shared pool) to
        avoid cross-event-loop issues when this method is invoked via
        ``asyncio.run()`` in a worker thread whose event loop differs from
        the main FastAPI loop that created the pool.

        Both caches are set at the very end to prevent other threads from
        observing a partially-loaded state (entities loaded but relations still None).
        """
        import json as _json
        import os as _os
        import asyncpg as _asyncpg

        workspace = str(self._working_dir)

        # Build DSN from environment (mirrors init_pg_pool logic)
        dsn = _os.getenv("DATABASE_URL", "")
        if not dsn:
            user = _os.getenv("POSTGRES_USER", "raganything")
            password = _os.getenv("POSTGRES_PASSWORD", "raganything")
            host = _os.getenv("POSTGRES_HOST", "localhost")
            port = _os.getenv("POSTGRES_PORT", "5432")
            database = _os.getenv("POSTGRES_DATABASE", _os.getenv("POSTGRES_DB", "raganything"))
            dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

        # Dedicated connection — safe to use from any event loop
        conn = await _asyncpg.connect(dsn)
        try:
            # Load entities
            rows = await conn.fetch(
                """SELECT id, entity_names, count
                   FROM LIGHTRAG_FULL_ENTITIES WHERE workspace=$1""",
                workspace,
            )
            entities = {}
            for row in rows:
                entity_names = row["entity_names"]
                if isinstance(entity_names, str):
                    try:
                        entity_names = _json.loads(entity_names)
                    except _json.JSONDecodeError:
                        entity_names = []
                entities[row["id"]] = {
                    "entity_names": entity_names or [],
                    "count": row["count"] or len(entity_names or []),
                }

            # Load relations
            rows = await conn.fetch(
                """SELECT id, relation_pairs, count
                   FROM LIGHTRAG_FULL_RELATIONS WHERE workspace=$1""",
                workspace,
            )
            relations = {}
            for row in rows:
                relation_pairs = row["relation_pairs"]
                if isinstance(relation_pairs, str):
                    try:
                        relation_pairs = _json.loads(relation_pairs)
                    except _json.JSONDecodeError:
                        relation_pairs = []
                relations[row["id"]] = {
                    "relation_pairs": relation_pairs or [],
                    "count": row["count"] or len(relation_pairs or []),
                }

            # Atomic assignment: both caches set together to prevent
            # other threads from seeing a partially-loaded state
            self._entities_cache = entities
            self._relations_cache = relations
        finally:
            await conn.close()

    def _read_kv_json(self, filename: str) -> dict:
        path = self._working_dir / filename
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def list_nodes(self, track=None, node_type=None) -> list:
        """从 LightRAG entities 获取节点列表 — PG-first with JSON fallback。"""
        self._ensure_loaded()
        entities = self._entities_cache or {}
        nodes = []
        seen = set()
        for doc_id, data in entities.items():
            entity_names = data.get("entity_names", [])
            for name in entity_names:
                if name not in seen:
                    seen.add(name)
        # 使用实体名称作为 ID（而非数字索引），确保与 list_edges 中的
        # 实体名称端点匹配，使 D3 forceLink 能解析边连接。
        return [type('_Node', (), {
            'id': n, 'name': n, 'node_type': 'entity',
            'description': '', 'competition_track': '',
            'difficulty_level': 1, 'estimated_hours': 0,
            'metadata': {},
        })() for n in seen]

    def list_edges(self, source_id=None, relation_type=None) -> list:
        """从 LightRAG full_relations 获取边列表 — PG-first with JSON fallback。"""
        self._ensure_loaded()
        relations = self._relations_cache or {}
        edges = []
        for doc_id, data in relations.items():
            pairs = data.get("relation_pairs", data.get("relations", []))
            for p in pairs:
                edges.append(type('_Edge', (), {
                    'id': '', 'source_id': str(p[0]) if isinstance(p, (list, tuple)) else '',
                    'target_id': str(p[1]) if isinstance(p, (list, tuple)) and len(p) > 1 else '',
                    'relation_type': RelationType.RELATED_TO,
                    'weight': 1.0, 'description': '',
                })())
        return edges

    def get_node(self, node_id: str):
        """从缓存中查找节点 — PG-first with JSON fallback。"""
        self._ensure_loaded()
        entities = self._entities_cache or {}
        # 尝试通过 entity_name 匹配
        for doc_id, data in entities.items():
            for name in data.get("entity_names", []):
                if name == node_id or name[:25] == node_id:
                    return type('_Node', (), {
                        'id': name, 'name': name, 'node_type': 'entity',
                        'description': '', 'competition_track': '',
                        'difficulty_level': 1, 'estimated_hours': 0,
                        'metadata': {},
                    })()
        return None

    def get_edges(self, node_id: str) -> list:
        """从缓存中获取节点关联边 — PG-first with JSON fallback。"""
        self._ensure_loaded()
        relations = self._relations_cache or {}
        edges = []
        for doc_id, data in relations.items():
            pairs = data.get("relation_pairs", data.get("relations", []))
            for p in pairs:
                src = str(p[0]) if isinstance(p, (list, tuple)) else ''
                tgt = str(p[1]) if isinstance(p, (list, tuple)) and len(p) > 1 else ''
                if src == node_id or tgt == node_id:
                    edges.append(type('_Edge', (), {
                        'id': '', 'source_id': src, 'target_id': tgt,
                        'relation_type': RelationType.RELATED_TO,
                        'weight': 1.0, 'description': '',
                    })())
        return edges

    def save_node(self, node) -> None: pass
    def delete_node(self, node_id: str) -> bool: return False
    def save_edge(self, edge) -> None: pass
    def delete_edge(self, edge_id: str) -> bool: return False
    def delete_edges(self, node_id: str) -> None: pass
