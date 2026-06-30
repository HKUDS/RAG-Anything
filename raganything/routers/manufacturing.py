"""Manufacturing Router — /api/manufacturing/*"""
import json
import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lightrag.llm.openai import openai_complete_if_cache
from raganything.routers import shared
from raganything.dependencies import get_current_user, require_permission
from raganything.permissions import Permission
from raganything.utils.security import validate_query_input

router = APIRouter(tags=["manufacturing"])

# ── Pydantic models ────────────────────────────────────

class ManufacturingQuery(BaseModel):
    query: str
    language: str = "gcode"
    top_k: int = 5


class MfgAgentQuery(BaseModel):
    query: str
    context: Optional[dict] = None


class MfgDiagnosisStart(BaseModel):
    query: str


class MfgDiagnosisContinue(BaseModel):
    session_id: str
    query: str


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


# ── Lazy-init manufacturing modules ───────────────────

_manufacturing_components = {}


def _get_manufacturing():
    """延迟初始化制造模块（首次 API 调用时加载）。"""
    if not _manufacturing_components:
        from raganything.manufacturing.knowledge_graph.models import (
            KnowledgeNode, KnowledgeEdge, CapabilityTag, TagTree,
        )
        from raganything.manufacturing.knowledge_pipeline.process_library import ProcessLibrary
        from raganything.manufacturing.knowledge_pipeline.fault_case_library import FaultCaseLibrary
        from raganything.manufacturing.agent.code_parser import CodeParser
        from raganything.manufacturing.agent.deployment_config import DeploymentConfig
        from raganything.manufacturing.deployment.dashboard import Dashboard

        _manufacturing_components.update({
            "process_library": ProcessLibrary(),
            "fault_case_library": FaultCaseLibrary(),
            "code_parser": CodeParser(),
            "deployment_config": DeploymentConfig(),
            "dashboard": Dashboard(),
            "TagTree": TagTree,
            "CapabilityTag": CapabilityTag,
            "KnowledgeNode": KnowledgeNode,
            "KnowledgeEdge": KnowledgeEdge,
        })
    return _manufacturing_components


def _get_mfg_graph(kb: str = "default"):
    """延迟初始化制造智能体知识图谱 API（每个 KB 独立实例）。

    每个 KB 拥有独立的 LightRAG 存储目录，此函数确保图谱
    统计（节点/边数量）来自对应 KB 的存储，而非全局默认。
    """
    from raganything.manufacturing.knowledge_graph.graph_api import (
        KnowledgeGraphAPI, LightRAGGraphStore,
    )
    from raganything.services.kb_service import kb_dir as _kb_dir

    m = _get_manufacturing()
    cache_key = f"graph_api_{kb}"
    if cache_key not in m:
        store = LightRAGGraphStore(working_dir=_kb_dir(kb))
        m[cache_key] = KnowledgeGraphAPI(graph_storage=store)
    return m[cache_key]


async def _get_mfg_agent_components(kb: str = "default"):
    """延迟初始化制造智能体组件（仅故障诊断）。"""
    m = _get_manufacturing()
    cache_key = f"diag_{kb}"
    if cache_key not in m:
        from raganything.manufacturing.agent.fault_diagnosis import FaultDiagnosisEngine
        from raganything.manufacturing.knowledge_pipeline.fault_case_library import FaultCaseLibrary
        _logger = logging.getLogger("manufacturing")

        fault_lib = FaultCaseLibrary(storage_path="./data/manufacturing_kb/fault_cases")

        class MfgLLMAdapter:
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
            "fault_diagnosis": FaultDiagnosisEngine(case_library=fault_lib, llm_client=MfgLLMAdapter()),
        }

    return m[cache_key]


async def _get_mfg_qa_engine(kb: str = "default") -> "QAEngine":
    """延迟初始化制造智能体 QA 引擎（每个 KB 独立实例）。"""
    from raganything.manufacturing.agent.qa_engine import QAEngine

    m = _get_manufacturing()
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

        m[cache_key] = QAEngine(
            rag_client=instance,
            llm_client=_llm_func,
            query_mode="rrf",
            max_steps=3,
        )
    return m[cache_key]


# ── 知识图谱 ──

@router.get("/manufacturing/knowledge-graph/summary")
async def mfg_kg_summary(kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """知识图谱统计摘要（按 KB 过滤）。"""
    return _get_mfg_graph(kb).get_graph_summary()


@router.get("/manufacturing/knowledge-graph/nodes")
async def mfg_kg_nodes(track: str = "", node_type: str = "", limit: int = 100, offset: int = 0,
                        kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """知识节点列表（按 KB 过滤）。"""
    return _get_mfg_graph(kb).get_nodes(competition_track=track, node_type=node_type, limit=limit, offset=offset)


@router.get("/manufacturing/knowledge-graph/edges")
async def mfg_kg_edges(source_id: str = "", relation_type: str = "", limit: int = 200,
                        kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """知识图谱边列表（按 KB 过滤）。"""
    return _get_mfg_graph(kb).get_edges(source_id=source_id, relation_type=relation_type, limit=limit)


@router.get("/manufacturing/knowledge-graph/nodes/{node_id}")
async def mfg_kg_node_detail(node_id: str, kb: str = QueryParam("default"),
                              _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """节点详情 + 关联边（按 KB 过滤）。"""
    detail = _get_mfg_graph(kb).get_node(node_id)
    if not detail:
        raise HTTPException(404, "节点不存在")
    return detail


@router.get("/manufacturing/knowledge-graph/nodes/{node_id}/lineage")
async def mfg_kg_lineage(node_id: str, upstream: int = 3, downstream: int = 3,
                          kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """知识谱系树（按 KB 过滤）。"""
    lineage = _get_mfg_graph(kb).get_lineage(node_id, upstream_depth=upstream, downstream_depth=downstream)
    if not lineage:
        raise HTTPException(404, "节点不存在")
    return lineage


# ── 工艺库 ──

@router.get("/manufacturing/process-library/search")
async def mfg_process_search(q: str = "", category: str = "", limit: int = 20, _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """企业工艺库检索。"""
    m = _get_manufacturing()
    results = await m["process_library"].search(q, category=category, limit=limit)
    return {"total": len(results), "results": results}


@router.get("/manufacturing/process-library/categories")
async def mfg_process_categories(_perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """工艺类别统计。"""
    m = _get_manufacturing()
    return await m["process_library"].list_by_category()


@router.get("/manufacturing/process-library/documents/{doc_id}")
async def mfg_process_get(doc_id: str, _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """获取单个工艺文档。"""
    m = _get_manufacturing()
    doc = await m["process_library"].get_document(doc_id)
    if not doc:
        raise HTTPException(404, "工艺文档不存在")
    return {
        "id": doc.get("id"), "title": doc.get("title"),
        "category": doc.get("category"),
        "parameters": doc.get("parameters", []),
        "text_preview": doc.get("text_preview", ""),
        "full_text": doc.get("full_text", doc.get("text_preview", "")),
        "file_path": doc.get("file_path", ""),
        "ingested_at": doc.get("ingested_at", ""),
    }


@router.post("/manufacturing/process-library/documents")
async def mfg_process_create(body: ProcessDocCreate,
                             _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """创建工艺文档。"""
    m = _get_manufacturing()
    doc_id = await m["process_library"].add_document({
        "title": body.title,
        "text": body.text,
        "category": body.category,
    })
    return {"status": "created", "id": doc_id}


@router.put("/manufacturing/process-library/documents/{doc_id}")
async def mfg_process_update(doc_id: str, body: ProcessDocUpdate,
                             _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """更新工艺文档。"""
    m = _get_manufacturing()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "无更新字段")
    # Map API field names to internal field names
    internal_updates = {}
    if "text" in updates:
        internal_updates["full_text"] = updates["text"]
        internal_updates["text_preview"] = updates["text"][:500]
    if "title" in updates:
        internal_updates["title"] = updates["title"]
    if "category" in updates:
        internal_updates["category"] = updates["category"]
    ok = await m["process_library"].update_document(doc_id, internal_updates)
    if not ok:
        raise HTTPException(404, "工艺文档不存在")
    return {"status": "updated"}


@router.delete("/manufacturing/process-library/documents/{doc_id}")
async def mfg_process_delete(doc_id: str, _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """删除工艺文档。"""
    m = _get_manufacturing()
    ok = await m["process_library"].delete_document(doc_id)
    if not ok:
        raise HTTPException(404, "工艺文档不存在")
    return {"status": "deleted"}


# ── 故障案例库 ──

@router.get("/manufacturing/fault-cases/search")
async def mfg_fault_search(q: str = "", top_k: int = 10, _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """故障案例检索。"""
    m = _get_manufacturing()
    results = await m["fault_case_library"].search(q, top_k=top_k)
    return {"total": len(results), "results": results}


@router.get("/manufacturing/fault-cases/stats")
async def mfg_fault_stats(_perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """故障案例统计。"""
    m = _get_manufacturing()
    return await m["fault_case_library"].get_statistics()


@router.get("/manufacturing/fault-cases/{case_id}")
async def mfg_fault_get(case_id: str, _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """获取单个故障案例。"""
    m = _get_manufacturing()
    case = await m["fault_case_library"].get_case(case_id)
    if not case:
        raise HTTPException(404, "故障案例不存在")
    return {
        "id": case.id, "title": case.title,
        "equipment_type": case.equipment_type,
        "fault_category": case.fault_category,
        "phenomenon": case.phenomenon,
        "root_cause": case.root_cause,
        "troubleshooting_steps": case.troubleshooting_steps,
        "preventive_measures": case.preventive_measures,
        "related_tags": case.related_tags,
        "severity": case.severity,
        "occurrence_count": case.occurrence_count,
    }


@router.post("/manufacturing/fault-cases")
async def mfg_fault_create(body: FaultCaseCreate,
                           _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """创建故障案例。"""
    from raganything.manufacturing.knowledge_graph.models import FaultCase
    import uuid as _uuid
    case = FaultCase(
        id=str(_uuid.uuid4())[:8],
        title=body.title,
        equipment_type=body.equipment_type,
        fault_category=body.fault_category,
        phenomenon=body.phenomenon,
        root_cause=body.root_cause,
        troubleshooting_steps=body.troubleshooting_steps,
        preventive_measures=body.preventive_measures,
        related_tags=body.related_tags,
        severity=body.severity,
    )
    m = _get_manufacturing()
    case_id = await m["fault_case_library"].add_case(case)
    return {"status": "created", "id": case_id}


@router.put("/manufacturing/fault-cases/{case_id}")
async def mfg_fault_update(case_id: str, body: FaultCaseUpdate,
                           _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """更新故障案例。"""
    m = _get_manufacturing()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "无更新字段")
    ok = await m["fault_case_library"].update_case(case_id, updates)
    if not ok:
        raise HTTPException(404, "故障案例不存在")
    return {"status": "updated"}


@router.delete("/manufacturing/fault-cases/{case_id}")
async def mfg_fault_delete(case_id: str, _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """删除故障案例。"""
    m = _get_manufacturing()
    ok = await m["fault_case_library"].delete_case(case_id)
    if not ok:
        raise HTTPException(404, "故障案例不存在")
    return {"status": "deleted"}


# ── 代码解析 ──

@router.post("/manufacturing/code/parse")
async def mfg_code_parse(body: ManufacturingQuery, _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """G 代码 / PLC 指令表解析。"""
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    m = _get_manufacturing()
    return m["code_parser"].parse(body.query, language=body.language)


# ── 数据看板 ──

@router.get("/manufacturing/dashboard")
async def mfg_dashboard(kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """制造智能体数据看板（按 KB 过滤图谱数据）。"""
    m = _get_manufacturing()
    return await m["dashboard"].get_snapshot(
        knowledge_graph_api=_get_mfg_graph(kb),
        process_library=m.get("process_library"),
        fault_case_library=m.get("fault_case_library"),
        kb_name=kb,
    )


# ── 部署配置 ──

@router.get("/manufacturing/institutions")
async def mfg_institutions(_perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """注册机构列表。"""
    m = _get_manufacturing()
    return m["deployment_config"].list_institutions()


# ── 智能体 API ──

@router.post("/manufacturing/qa")
async def mfg_qa(body: MfgAgentQuery, kb: str = QueryParam("default"),
                 _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """智能制造文本问答 — AgenticRAG 多步推理。"""
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    engine = await _get_mfg_qa_engine(kb)
    response = await engine.answer(body.query, context=body.context)
    m = _get_manufacturing()
    await m["dashboard"].log_query(
        user_id=str(current_user["id"]),
        institution_id="default",
        query=body.query,
        query_type="qa",
        response_ms=response.processing_time_ms,
        kb_name=kb,
    )
    return {
        "query": response.query,
        "answer": response.answer,
        "citations": response.citations,
        "related_images": response.related_images,
        "confidence": response.confidence,
        "processing_time_ms": response.processing_time_ms,
        "needs_human_review": response.needs_human_review,
        "trace": response.trace,
    }


@router.post("/manufacturing/qa/stream")
async def mfg_qa_stream(body: MfgAgentQuery, kb: str = QueryParam("default"),
                        _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """智能制造文本问答 — AgenticRAG 真流式 SSE（与通用智能体一致）。"""
    if not shared.API_KEY or not shared.BASE_URL:
        raise HTTPException(503, "LLM 服务未配置")

    async def event_stream():
        import time as _time
        start_time = _time.time()
        query_id = str(_uuid.uuid4())[:8]

        try:
            engine = await _get_mfg_qa_engine(kb)

            async for event_data in engine.answer_stream(body.query):
                event_type = event_data.get("type", "")

                if event_type == "thinking":
                    thought_preview = (event_data.get("thought", "") or "")[:200]
                    obs_preview = (event_data.get("observation", "") or "")[:150]
                    thinking_data = {
                        'type': 'thinking',
                        'step': event_data.get('step', 0),
                        'thought': thought_preview,
                        'action': event_data.get('action', ''),
                        'observation_preview': obs_preview,
                        'elapsed_ms': event_data.get('elapsed_ms', 0),
                    }
                    yield f"data: {json.dumps(thinking_data, ensure_ascii=False)}\n\n"

                elif event_type == "token":
                    token_data = {'type': 'token', 'content': event_data.get('content', '')}
                    yield f"data: {json.dumps(token_data, ensure_ascii=False)}\n\n"

                elif event_type == "done":
                    try:
                        m = _get_manufacturing()
                        response_ms = event_data.get("elapsed_ms", (_time.time() - start_time) * 1000)
                        await m["dashboard"].log_query(
                            user_id=str(current_user["id"]),
                            institution_id="default",
                            query=body.query,
                            query_type="qa",
                            response_ms=response_ms,
                            kb_name=kb,
                        )
                    except Exception:
                        pass

                    if event_data.get("images"):
                        img_data = {'type': 'images', 'images': event_data['images']}
                        yield f"data: {json.dumps(img_data, ensure_ascii=False)}\n\n"

                    elapsed = event_data.get("elapsed_ms", (_time.time() - start_time) * 1000) / 1000
                    done_data = {
                        'type': 'done',
                        'id': query_id,
                        'elapsed': round(elapsed, 2),
                        'confidence': event_data.get('confidence', 0),
                        'citations_count': len(event_data.get('citations', [])),
                        'images_count': len(event_data.get('images', [])),
                    }
                    yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/manufacturing/fault-diagnosis")
async def mfg_diagnosis_start(body: MfgDiagnosisStart, kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """故障诊断 — 开始新会话。"""
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    m = await _get_mfg_agent_components(kb=kb)
    sid = str(_uuid.uuid4())[:8]
    result = await m["fault_diagnosis"].start_diagnosis(sid, body.query)
    return result


@router.post("/manufacturing/fault-diagnosis/continue")
async def mfg_diagnosis_continue(body: MfgDiagnosisContinue, kb: str = QueryParam("default"), _perm: None = Depends(require_permission(Permission.MANUFACTURING_WRITE)), current_user: dict = Depends(get_current_user)):
    """故障诊断 — 继续会话。"""
    validate_query_input(body.query, user_id=str(current_user.get("id", "anonymous")))
    m = await _get_mfg_agent_components(kb=kb)
    result = await m["fault_diagnosis"].continue_diagnosis(body.session_id, body.query)
    return result


# ── 健康检查 ──

@router.get("/manufacturing/kb-list")
async def mfg_kb_list(_perm: None = Depends(require_permission(Permission.MANUFACTURING_READ)), current_user: dict = Depends(get_current_user)):
    """制造智能体可用 KB 列表（仅制造领域 KB，无则自动创建）。"""
    from raganything.services.kb_service import (
        load_kb_meta, save_kb_meta, list_kbs_by_domain, get_kb,
    )

    # Filter to manufacturing-domain KBs only
    mfg_kbs = await list_kbs_by_domain("manufacturing")

    # Auto-create manufacturing KB on first access if none exists
    if not mfg_kbs:
        kb_name = "manufacturing"
        label = "制造知识库"
        meta = await load_kb_meta()
        meta[kb_name] = {
            "name": label,
            "created": datetime.now().isoformat(),
            "domain": "manufacturing",
        }
        await save_kb_meta(meta)
        await get_kb(kb_name)  # initialize storage directory
        mfg_kbs = {kb_name: meta[kb_name]}

    kbs = []
    for name, info in mfg_kbs.items():
        kbs.append({
            "name": name,
            "label": info.get("name", name),
            "created": info.get("created", ""),
            "owner_username": info.get("owner_username", ""),
        })
    return {"knowledge_bases": kbs}


@router.get("/manufacturing/health")
async def mfg_health():
    """制造模块健康检查。"""
    try:
        m = _get_manufacturing()
        return {
            "status": "healthy",
            "graph_api": m["graph_api"] is not None,
            "process_library": m["process_library"] is not None,
            "fault_case_library": m["fault_case_library"] is not None,
            "code_parser": m["code_parser"] is not None,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
