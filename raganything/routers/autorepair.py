"""AutoRepair Router — /api/autorepair/*"""
import json
import inspect
import logging
import os
import uuid as _uuid
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lightrag.llm.openai import openai_complete_if_cache
from raganything.routers import shared
from raganything.dependencies import (
    authenticated_sse_events,
    get_current_user,
    require_permission,
    verify_kb_access,
)
from raganything.permissions import Permission
from raganything.services.video_segments import enrich_video_segment_citations
from raganything.utils.security import validate_query_input

if TYPE_CHECKING:
    from raganything.autorepair.agent.qa_engine import QAEngine

router = APIRouter(tags=["autorepair"])
logger = logging.getLogger(__name__)


async def _resolve_autorepair_media_payload(kb_name: str, image_path: str) -> dict | None:
    """Return opaque controlled-media metadata for authenticated browser delivery."""
    resolver = getattr(shared, "resolve_controlled_media_payload", None)
    if not callable(resolver):
        return None
    try:
        result = resolver(kb_name=kb_name, image_path=image_path)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        logger.warning(
            "AutoRepair media directory lookup failed: error_type=%s",
            type(exc).__name__,
        )
        return None
    return result if isinstance(result, dict) else None


async def _resolve_autorepair_media_url(kb_name: str, image_path: str) -> str | None:
    """Backward-compatible internal helper for callers that need only the URL."""
    payload = await _resolve_autorepair_media_payload(kb_name, image_path)
    value = payload.get("url") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def _sanitize_sse_text(value: object) -> str:
    from raganything.autorepair.agent.qa_engine import _sanitize_client_text

    return _sanitize_client_text(value)


def _sanitize_media_payloads(value: object, kb_name: str) -> list[dict]:
    from raganything.autorepair.agent.qa_engine import (
        _is_controlled_media_url,
        _sanitize_client_text,
    )

    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for raw in value[:3]:
        if not isinstance(raw, dict):
            continue
        media_url = raw.get("url") or raw.get("data_url")
        if not _is_controlled_media_url(media_url, kb_name):
            continue
        try:
            page = int(raw["page"]) if raw.get("page") is not None else None
            page = page if page is None or page >= 0 else None
        except (TypeError, ValueError):
            page = None
        try:
            relevance = min(max(float(raw.get("relevance", 0.0)), 0.0), 1.0)
        except (TypeError, ValueError):
            relevance = 0.0
        result.append({
            "data_url": media_url,
            "url": media_url,
            **({"media_id": raw["media_id"]} if isinstance(raw.get("media_id"), str) else {}),
            **({"legacy_grant": raw["legacy_grant"]} if isinstance(raw.get("legacy_grant"), str) else {}),
            "kb": kb_name,
            "caption": _sanitize_client_text(raw.get("caption") or "Related image")[:300],
            "page": page,
            "relevance": relevance,
        })
    return result


def _sanitize_client_value(value):
    if isinstance(value, str):
        return _sanitize_sse_text(value)
    if isinstance(value, list):
        return [_sanitize_client_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _sanitize_sse_text(key) if isinstance(key, str) else key:
            _sanitize_client_value(item)
            for key, item in value.items()
        }
    return value


def _authorized_citations(value: object, kb_name: str) -> list[dict]:
    """Expose video timing only after this route has authorized its KB."""
    return _sanitize_client_value(enrich_video_segment_citations(value, kb_name))


def _sanitize_trace(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        action = item.get("action", "")
        result.append({
            "step": item.get("step", 0),
            "thought": "",
            "action": action if action in {"search", "reason", "answer"} else "",
            "observation": "",
            "elapsed_ms": item.get("elapsed_ms", 0),
        })
    return result

# ── Pydantic models ────────────────────────────────────

class AutoRepairQuery(BaseModel):
    query: str
    language: str = "gcode"
    top_k: int = 5


class AutoRepairAgentQuery(BaseModel):
    query: str
    context: Optional[dict] = None


class AutoRepairDiagnosisStart(BaseModel):
    query: str


class AutoRepairDiagnosisContinue(BaseModel):
    session_id: str
    query: str


class CaseCreate(BaseModel):
    """统一案例创建 — case_type='fault'|'process'."""
    title: str
    case_type: str = "fault"  # 'fault' | 'process'
    # Fault fields
    equipment_type: str = ""
    fault_category: str = ""
    phenomenon: str = ""
    root_cause: str = ""
    troubleshooting_steps: list[str] = []
    preventive_measures: list[str] = []
    severity: str = "medium"
    # Process fields
    category: str = ""  # process category (auto-classified if empty)
    text: str = ""  # maps to full_text
    parameters: list[dict] = []
    file_path: str = ""


class CaseUpdate(BaseModel):
    """统一案例更新 — 所有字段可选。"""
    title: Optional[str] = None
    equipment_type: Optional[str] = None
    fault_category: Optional[str] = None
    phenomenon: Optional[str] = None
    root_cause: Optional[str] = None
    troubleshooting_steps: Optional[list[str]] = None
    preventive_measures: Optional[list[str]] = None
    severity: Optional[str] = None
    occurrence_count: Optional[int] = None
    category: Optional[str] = None
    text: Optional[str] = None  # maps to full_text
    parameters: Optional[list[dict]] = None
    file_path: Optional[str] = None


# ── Deprecated Pydantic models (backward compat) ─────

class FaultCaseCreate(BaseModel):
    title: str
    equipment_type: str = ""
    fault_category: str = ""
    phenomenon: str = ""
    root_cause: str = ""
    troubleshooting_steps: list[str] = []
    preventive_measures: list[str] = []
    related_tags: list[str] = []
    severity: str = "medium"


class FaultCaseUpdate(BaseModel):
    title: Optional[str] = None
    equipment_type: Optional[str] = None
    fault_category: Optional[str] = None
    phenomenon: Optional[str] = None
    root_cause: Optional[str] = None
    troubleshooting_steps: Optional[list[str]] = None
    preventive_measures: Optional[list[str]] = None
    related_tags: Optional[list[str]] = None
    severity: Optional[str] = None
    occurrence_count: Optional[int] = None


class ProcessDocCreate(BaseModel):
    title: str
    text: str
    category: str = ""


class ProcessDocUpdate(BaseModel):
    title: Optional[str] = None
    text: Optional[str] = None
    category: Optional[str] = None


# ── Lazy-init autorepair modules ───────────────────

_autorepair_components = {}


def _get_autorepair():
    """延迟初始化制造模块（首次 API 调用时加载）。"""
    if not _autorepair_components:
        from raganything.autorepair.knowledge_graph.models import (
            KnowledgeNode, KnowledgeEdge, CapabilityTag, TagTree,
        )
        from raganything.autorepair.knowledge_pipeline.case_library import CaseLibrary
        from raganything.autorepair.agent.code_parser import CodeParser
        from raganything.autorepair.agent.deployment_config import DeploymentConfig
        from raganything.autorepair.deployment.dashboard import Dashboard

        _autorepair_components.update({
            "case_library": CaseLibrary(),
            "code_parser": CodeParser(),
            "deployment_config": DeploymentConfig(),
            "dashboard": Dashboard(),
            "TagTree": TagTree,
            "CapabilityTag": CapabilityTag,
            "KnowledgeNode": KnowledgeNode,
            "KnowledgeEdge": KnowledgeEdge,
        })
    return _autorepair_components


def _get_ar_graph(kb: str = "default"):
    """延迟初始化制造智能体知识图谱 API（每个 KB 独立实例）。

    每个 KB 拥有独立的 LightRAG 存储目录，此函数确保图谱
    统计（节点/边数量）来自对应 KB 的存储，而非全局默认。
    """
    from raganything.autorepair.knowledge_graph.graph_api import (
        KnowledgeGraphAPI, LightRAGGraphStore,
    )
    from raganything.services.kb_service import kb_dir as _kb_dir

    m = _get_autorepair()
    cache_key = f"graph_api_{kb}"
    if cache_key not in m:
        store = LightRAGGraphStore(working_dir=_kb_dir(kb))
        m[cache_key] = KnowledgeGraphAPI(graph_storage=store)
    return m[cache_key]


async def _get_ar_agent_components(kb: str = "default"):
    """延迟初始化制造智能体组件（仅故障诊断）。"""
    m = _get_autorepair()
    cache_key = f"diag_{kb}"
    if cache_key not in m:
        from raganything.autorepair.agent.fault_diagnosis import FaultDiagnosisEngine
        from raganything.autorepair.knowledge_pipeline.case_library import CaseLibrary
        _logger = logging.getLogger("autorepair")

        case_lib = CaseLibrary(storage_path="./data/autorepair_kb/cases")

        class AutoRepairLLMAdapter:
            async def generate(self, prompt: str) -> str:
                if not shared.API_KEY or not shared.BASE_URL:
                    raise RuntimeError("LLM 服务未配置")
                result = await openai_complete_if_cache(
                    shared.LLM_MODEL, prompt,
                    system_prompt="你是智能制造教学专家。",
                    api_key=shared.API_KEY, base_url=shared.BASE_URL,
                )
                if result is None:
                    raise RuntimeError("LLM 返回为空")
                return result if isinstance(result, str) else str(result)

        m[cache_key] = {
            "fault_diagnosis": FaultDiagnosisEngine(case_library=case_lib, llm_client=AutoRepairLLMAdapter()),
        }

    return m[cache_key]


async def _get_ar_qa_engine(kb: str = "default") -> "QAEngine":
    """延迟初始化制造智能体 QA 引擎（每个 KB 独立实例）。"""
    from raganything.autorepair.agent.qa_engine import QAEngine

    m = _get_autorepair()
    cache_key = f"qa_{kb}"
    if cache_key not in m:
        instance = await shared.get_kb(kb)

        async def _llm_func(prompt, system_prompt=None, history_messages=None, **kw):
            if "max_tokens" not in kw:
                kw["max_tokens"] = int(os.getenv("MAX_TOKENS", "8192"))
            return await openai_complete_if_cache(
                shared.LLM_MODEL, prompt, system_prompt=system_prompt,
                history_messages=history_messages or [],
                api_key=shared.API_KEY, base_url=shared.BASE_URL, **kw,
            )

        async def _media_url_resolver(image_path: str) -> dict | None:
            return await _resolve_autorepair_media_payload(kb, image_path)

        m[cache_key] = QAEngine(
            rag_client=instance,
            llm_client=_llm_func,
            kb_name=kb,
            media_url_resolver=_media_url_resolver,
            query_mode="rrf",
            max_steps=3,
        )
    return m[cache_key]


# ── 知识图谱 ──

@router.get("/autorepair/knowledge-graph/summary")
async def ar_kg_summary(kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)), current_user: dict = Depends(get_current_user)):
    """知识图谱统计摘要（按 KB 过滤）。"""
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    return _get_ar_graph(actual_kb).get_graph_summary()


@router.get("/autorepair/knowledge-graph/nodes")
async def ar_kg_nodes(track: str = "", node_type: str = "", limit: int = 100, offset: int = 0,
                        kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)), current_user: dict = Depends(get_current_user)):
    """知识节点列表（按 KB 过滤）。"""
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    return _get_ar_graph(actual_kb).get_nodes(
        competition_track=track,
        node_type=node_type,
        limit=limit,
        offset=offset,
    )


@router.get("/autorepair/knowledge-graph/edges")
async def ar_kg_edges(source_id: str = "", relation_type: str = "", limit: int = 200,
                        kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)), current_user: dict = Depends(get_current_user)):
    """知识图谱边列表（按 KB 过滤）。"""
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    return _get_ar_graph(actual_kb).get_edges(
        source_id=source_id,
        relation_type=relation_type,
        limit=limit,
    )


@router.get("/autorepair/knowledge-graph/nodes/{node_id}")
async def ar_kg_node_detail(node_id: str, kb: str = QueryParam("default"),
                              _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)), current_user: dict = Depends(get_current_user)):
    """节点详情 + 关联边（按 KB 过滤）。"""
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    detail = _get_ar_graph(actual_kb).get_node(node_id)
    if not detail:
        raise HTTPException(404, "节点不存在")
    return detail


@router.get("/autorepair/knowledge-graph/nodes/{node_id}/lineage")
async def ar_kg_lineage(node_id: str, upstream: int = 3, downstream: int = 3,
                          kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)), current_user: dict = Depends(get_current_user)):
    """知识谱系树（按 KB 过滤）。"""
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    lineage = _get_ar_graph(actual_kb).get_lineage(
        node_id,
        upstream_depth=upstream,
        downstream_depth=downstream,
    )
    if not lineage:
        raise HTTPException(404, "节点不存在")
    return lineage


# ── 统一案例库 (合并 故障案例库 + 维修工艺库) ──

@router.get("/autorepair/cases/search")
async def ar_cases_search(q: str = "", case_type: str = "", category: str = "",
                           top_k: int = 20, _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
                           current_user: dict = Depends(get_current_user)):
    """统一案例检索 — 支持按 case_type 过滤 (fault/process)。"""
    m = _get_autorepair()
    results = await m["case_library"].search(q, case_type=case_type, category=category, top_k=top_k)
    return {"total": len(results), "results": results}


@router.get("/autorepair/cases/stats")
async def ar_cases_stats(_perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
                          current_user: dict = Depends(get_current_user)):
    """统一案例统计。"""
    m = _get_autorepair()
    return await m["case_library"].get_statistics()


@router.get("/autorepair/cases/categories")
async def ar_cases_categories(_perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
                               current_user: dict = Depends(get_current_user)):
    """工艺类别统计 (case_type='process')。"""
    m = _get_autorepair()
    return await m["case_library"].list_categories()


@router.get("/autorepair/cases/{case_id}")
async def ar_case_get(case_id: str, _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
                       current_user: dict = Depends(get_current_user)):
    """获取单个案例。"""
    m = _get_autorepair()
    case = await m["case_library"].get_case(case_id)
    if not case:
        raise HTTPException(404, "案例不存在")
    return case


@router.post("/autorepair/cases")
async def ar_case_create(body: CaseCreate,
                          _perm: None = Depends(require_permission(Permission.AUTOREPAIR_WRITE)),
                          current_user: dict = Depends(get_current_user)):
    """创建案例 (fault 或 process)。"""
    from raganything.autorepair.knowledge_graph.models import Case as CaseModel
    import uuid as _uuid

    case = CaseModel(
        id=str(_uuid.uuid4())[:8],
        title=body.title,
        case_type=body.case_type,
        equipment_type=body.equipment_type,
        fault_category=body.fault_category,
        phenomenon=body.phenomenon,
        root_cause=body.root_cause,
        troubleshooting_steps=body.troubleshooting_steps,
        preventive_measures=body.preventive_measures,
        severity=body.severity,
        category=body.category,
        parameters=body.parameters,
        file_path=body.file_path,
        full_text=body.text,
        text_preview=body.text[:500] if body.text else "",
    )
    m = _get_autorepair()
    case_id = await m["case_library"].add_case(case)
    return {"status": "created", "id": case_id}


@router.put("/autorepair/cases/{case_id}")
async def ar_case_update(case_id: str, body: CaseUpdate,
                          _perm: None = Depends(require_permission(Permission.AUTOREPAIR_WRITE)),
                          current_user: dict = Depends(get_current_user)):
    """更新案例。"""
    m = _get_autorepair()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "无更新字段")
    # Map 'text' → 'full_text' for process updates
    if "text" in updates:
        updates["full_text"] = updates.pop("text")
    ok = await m["case_library"].update_case(case_id, updates)
    if not ok:
        raise HTTPException(404, "案例不存在")
    return {"status": "updated"}


@router.delete("/autorepair/cases/{case_id}")
async def ar_case_delete(case_id: str, _perm: None = Depends(require_permission(Permission.AUTOREPAIR_WRITE)),
                          current_user: dict = Depends(get_current_user)):
    """删除案例。"""
    m = _get_autorepair()
    ok = await m["case_library"].delete_case(case_id)
    if not ok:
        raise HTTPException(404, "案例不存在")
    return {"status": "deleted"}


# ── 向后兼容: 旧端点重定向 ──

@router.get("/autorepair/process-library/search")
async def ar_process_search_legacy(q: str = "", category: str = "", limit: int = 20,
    _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
    current_user: dict = Depends(get_current_user)):
    """@deprecated: 使用 /autorepair/cases/search?case_type=process"""
    m = _get_autorepair()
    results = await m["case_library"].search(q, case_type="process", category=category, top_k=limit)
    return {"total": len(results), "results": results}


@router.get("/autorepair/process-library/categories")
async def ar_process_categories_legacy(_perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
    current_user: dict = Depends(get_current_user)):
    """@deprecated: 使用 /autorepair/cases/categories"""
    m = _get_autorepair()
    return await m["case_library"].list_categories()


@router.get("/autorepair/process-library/documents/{doc_id}")
async def ar_process_get_legacy(doc_id: str, _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
    current_user: dict = Depends(get_current_user)):
    """@deprecated: 使用 /autorepair/cases/{case_id}"""
    m = _get_autorepair()
    doc = await m["case_library"].get_case(doc_id)
    if not doc:
        raise HTTPException(404, "工艺文档不存在")
    return doc


@router.get("/autorepair/fault-cases/search")
async def ar_fault_search_legacy(q: str = "", top_k: int = 10,
    _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
    current_user: dict = Depends(get_current_user)):
    """@deprecated: 使用 /autorepair/cases/search?case_type=fault"""
    m = _get_autorepair()
    results = await m["case_library"].search(q, case_type="fault", top_k=top_k)
    return {"total": len(results), "results": results}


@router.get("/autorepair/fault-cases/stats")
async def ar_fault_stats_legacy(_perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)),
    current_user: dict = Depends(get_current_user)):
    """@deprecated: 使用 /autorepair/cases/stats"""
    m = _get_autorepair()
    stats = await m["case_library"].get_statistics()
    return {
        "total_cases": stats.get("fault_total", 0),
        "equipment_types": stats.get("equipment_types", {}),
        "fault_categories": stats.get("fault_categories", {}),
        "severity_distribution": stats.get("severity_distribution", {}),
    }


# ── 代码解析 ──

@router.post("/autorepair/code/parse")
async def ar_code_parse(body: AutoRepairQuery, _perm: None = Depends(require_permission(Permission.AUTOREPAIR_WRITE)), current_user: dict = Depends(get_current_user)):
    """G 代码 / PLC 指令表解析。"""
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    m = _get_autorepair()
    return m["code_parser"].parse(body.query, language=body.language)


# ── 数据看板 ──

@router.get("/autorepair/dashboard")
async def ar_dashboard(kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)), current_user: dict = Depends(get_current_user)):
    """制造智能体数据看板（按 KB 过滤图谱数据）。"""
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    m = _get_autorepair()
    return await m["dashboard"].get_snapshot(
        knowledge_graph_api=_get_ar_graph(actual_kb),
        case_library=m.get("case_library"),
        kb_name=actual_kb,
    )


# ── 部署配置 ──

@router.get("/autorepair/institutions")
async def ar_institutions(_perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)), current_user: dict = Depends(get_current_user)):
    """注册机构列表。"""
    m = _get_autorepair()
    return m["deployment_config"].list_institutions()


# ── 智能体 API ──

@router.post("/autorepair/qa")
async def ar_qa(body: AutoRepairAgentQuery, kb: str = QueryParam("default"),
                 _perm: None = Depends(require_permission(Permission.AUTOREPAIR_WRITE)), current_user: dict = Depends(get_current_user)):
    """智能制造文本问答 — AgenticRAG 多步推理。"""
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    engine = await _get_ar_qa_engine(actual_kb)
    response = await engine.answer(body.query, context=body.context)
    m = _get_autorepair()
    await m["dashboard"].log_query(
        user_id=str(current_user["id"]),
        institution_id="default",
        query=body.query,
        query_type="qa",
        response_ms=response.processing_time_ms,
        kb_name=actual_kb,
    )
    return {
        "query": _sanitize_sse_text(response.query),
        "answer": _sanitize_sse_text(response.answer),
        "citations": _authorized_citations(response.citations, actual_kb),
        "related_images": _sanitize_media_payloads(response.related_images, actual_kb),
        "confidence": response.confidence,
        "processing_time_ms": response.processing_time_ms,
        "needs_human_review": response.needs_human_review,
        "trace": _sanitize_trace(response.trace),
    }


@router.post("/autorepair/qa/stream")
async def ar_qa_stream(body: AutoRepairAgentQuery, kb: str = QueryParam("default"),
                        _perm: None = Depends(require_permission(Permission.AUTOREPAIR_WRITE)), current_user: dict = Depends(get_current_user)):
    """智能制造文本问答 — AgenticRAG 真流式 SSE（与通用智能体一致）。"""
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    if not shared.API_KEY or not shared.BASE_URL:
        raise HTTPException(503, "LLM 服务未配置")

    async def event_stream():
        import time as _time
        start_time = _time.time()
        query_id = str(_uuid.uuid4())[:8]
        token_buffer = ""

        try:
            engine = await _get_ar_qa_engine(actual_kb)

            async for event_data in engine.answer_stream(body.query):
                event_type = event_data.get("type", "")

                if event_type == "thinking":
                    action = event_data.get("action", "")
                    thinking_data = {
                        'type': 'thinking',
                        'step': event_data.get('step', 0),
                        'thought': '',
                        'action': action if action in {"search", "reason", "answer", "retrieve"} else '',
                        # Retrieval observations can contain controlled local
                        # media references; they are never an SSE payload.
                        'observation_preview': '',
                        'elapsed_ms': event_data.get('elapsed_ms', 0),
                    }
                    yield f"data: {json.dumps(thinking_data, ensure_ascii=False)}\n\n"

                elif event_type == "token":
                    token_buffer += str(event_data.get('content', '') or '')
                    while "\n" in token_buffer:
                        line, token_buffer = token_buffer.split("\n", 1)
                        token_data = {
                            'type': 'token',
                            'content': _sanitize_sse_text(f"{line}\n"),
                        }
                        yield f"data: {json.dumps(token_data, ensure_ascii=False)}\n\n"

                elif event_type == "done":
                    if token_buffer:
                        token_data = {
                            'type': 'token',
                            'content': _sanitize_sse_text(token_buffer),
                        }
                        yield f"data: {json.dumps(token_data, ensure_ascii=False)}\n\n"
                        token_buffer = ""
                    try:
                        m = _get_autorepair()
                        response_ms = event_data.get("elapsed_ms", (_time.time() - start_time) * 1000)
                        await m["dashboard"].log_query(
                            user_id=str(current_user["id"]),
                            institution_id="default",
                            query=body.query,
                            query_type="qa",
                            response_ms=response_ms,
                            kb_name=actual_kb,
                        )
                    except Exception:
                        pass

                    safe_images = _sanitize_media_payloads(
                        event_data.get("images"), actual_kb
                    )
                    if safe_images:
                        img_data = {'type': 'images', 'images': safe_images}
                        yield f"data: {json.dumps(img_data, ensure_ascii=False)}\n\n"

                    elapsed = event_data.get("elapsed_ms", (_time.time() - start_time) * 1000) / 1000
                    done_data = {
                        'type': 'done',
                        'id': query_id,
                        'elapsed': round(elapsed, 2),
                        'confidence': event_data.get('confidence', 0),
                        'citations_count': len(event_data.get('citations', [])),
                        'images_count': len(safe_images),
                    }
                    citations = _authorized_citations(event_data.get("citations"), actual_kb)
                    if citations:
                        done_data["citations"] = citations
                    yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

        except Exception as exc:
            logger.warning(
                "AutoRepair QA stream failed: error_type=%s",
                type(exc).__name__,
            )
            error_data = {
                "type": "error",
                "content": "AutoRepair query failed",
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        authenticated_sse_events(event_stream(), current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/autorepair/fault-diagnosis")
async def ar_diagnosis_start(body: AutoRepairDiagnosisStart, kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.AUTOREPAIR_WRITE)), current_user: dict = Depends(get_current_user)):
    """故障诊断 — 开始新会话。"""
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    m = await _get_ar_agent_components(kb=actual_kb)
    sid = str(_uuid.uuid4())[:8]
    result = await m["fault_diagnosis"].start_diagnosis(sid, body.query)
    return result


@router.post("/autorepair/fault-diagnosis/continue")
async def ar_diagnosis_continue(body: AutoRepairDiagnosisContinue, kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.AUTOREPAIR_WRITE)), current_user: dict = Depends(get_current_user)):
    """故障诊断 — 继续会话。"""
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    actual_kb = await verify_kb_access(kb=kb, current_user=current_user)
    m = await _get_ar_agent_components(kb=actual_kb)
    result = await m["fault_diagnosis"].continue_diagnosis(body.session_id, body.query)
    return result


# ── 健康检查 ──

@router.get("/autorepair/kb-list")
async def ar_kb_list(_perm: None = Depends(require_permission(Permission.AUTOREPAIR_READ)), current_user: dict = Depends(get_current_user)):
    """List only AutoRepair KBs the current user may access."""
    from raganything.services.kb_service import list_kbs_by_domain

    ar_kbs = await list_kbs_by_domain("autorepair")

    kbs = []
    for name, info in ar_kbs.items():
        try:
            actual_kb = await verify_kb_access(kb=name, current_user=current_user)
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                continue
            raise
        kbs.append({
            "name": actual_kb,
            "label": info.get("name", actual_kb),
            "created": info.get("created", ""),
            "owner_username": info.get("owner_username", ""),
        })
    return {"knowledge_bases": kbs}


@router.get("/autorepair/health")
async def ar_health():
    """制造模块健康检查。"""
    try:
        m = _get_autorepair()
        return {
            "status": "healthy",
            "case_library": m["case_library"] is not None,
            "code_parser": m["code_parser"] is not None,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
