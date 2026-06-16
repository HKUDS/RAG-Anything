"""
工作流执行引擎 — 拓扑排序 + 节点执行器注册 + WebSocket 状态推送
"""
import json
import time
import uuid
from pathlib import Path
from datetime import datetime
from collections import deque

RUNS_DIR = Path("./workflows/runs")
RUNS_DIR.mkdir(parents=True, exist_ok=True)


class NodeExecutor:
    """执行器基类"""
    node_type: str = ""

    async def execute(self, config: dict, inputs: dict) -> dict:
        raise NotImplementedError


class DocumentInputExecutor(NodeExecutor):
    """文档输入 — 读取文件返回文本"""
    node_type = "document_input"

    async def execute(self, config: dict, inputs: dict) -> dict:
        file_type = config.get("file_type", ".pdf")
        text = f"[模拟] 读取了 {file_type} 文件内容（示例文本，实际文件读取待集成）"
        return {"content": text, "file_type": file_type}


class TextSplitterExecutor(NodeExecutor):
    """文本分割 — 按 chunk 参数分块"""
    node_type = "text_splitter"

    async def execute(self, config: dict, inputs: dict) -> dict:
        upstream = inputs.get("content", "")
        chunk_size = config.get("chunk_size", 800)
        chunk_overlap = config.get("chunk_overlap", 100)

        if isinstance(upstream, list):
            upstream = "\n".join(str(c) for c in upstream)
        text = str(upstream)
        chunks = []
        step = chunk_size - chunk_overlap
        for i in range(0, len(text), step):
            chunk = text[i:i + chunk_size]
            if len(chunk) >= 50:
                chunks.append(chunk)
        if not chunks:
            chunks = [text]
        return {"chunks": chunks, "count": len(chunks)}


class EmbeddingExecutor(NodeExecutor):
    """嵌入向量 — 调用嵌入 API"""
    node_type = "embedding"

    async def execute(self, config: dict, inputs: dict) -> dict:
        model = config.get("model", "text-embedding-3-small")
        dims = config.get("dims", 1536)
        text = inputs.get("content", "")
        if isinstance(text, list):
            text = " ".join(str(t) for t in text)
        return {"model": model, "dims": dims, "vector_count": 1,
                "note": f"Vectorized with {model} ({dims}d) — production embedding pending"}


class RetrieverExecutor(NodeExecutor):
    """检索器 — 查询 LightRAG 知识库"""
    node_type = "retriever"

    async def execute(self, config: dict, inputs: dict) -> dict:
        top_k = config.get("top_k", 10)
        mode = config.get("mode", "hybrid")
        query = inputs.get("content", "")
        if isinstance(query, list):
            query = " ".join(str(q) for q in query[:3])
        return {"results": [f"[{mode}] 检索结果 #{i}" for i in range(1, min(top_k, 5) + 1)],
                "query": str(query)[:200], "mode": mode, "top_k": top_k}


class LLMAnswerExecutor(NodeExecutor):
    """LLM 回答 — 调用 LLM 生成"""
    node_type = "llm_answer"

    async def execute(self, config: dict, inputs: dict) -> dict:
        model = config.get("model", "gpt-4o")
        temperature = config.get("temperature", 0.1)
        system_prompt = config.get("system_prompt", "")
        context = inputs.get("content", "") or inputs.get("results", "")
        if isinstance(context, list):
            context = "\n".join(str(c) for c in context)

        answer = f"[LLM: {model}]\n基于上下文生成回答（实际 LLM 调用待集成）\n上下文摘要: {str(context)[:300]}"
        return {"answer": answer, "model": model, "temperature": temperature}


class OutputExecutor(NodeExecutor):
    """输出 — 格式化上游结果"""
    node_type = "output"

    async def execute(self, config: dict, inputs: dict) -> dict:
        fmt = config.get("format", "markdown")
        content = inputs.get("answer", "") or inputs.get("content", "") or inputs.get("results", "")
        if isinstance(content, list):
            content = "\n".join(f"- {c}" for c in content)
        if fmt == "markdown":
            formatted = f"## 工作流输出\n\n{content}"
        elif fmt == "json":
            formatted = json.dumps({"output": str(content)}, ensure_ascii=False, indent=2)
        else:
            formatted = str(content)
        return {"formatted": formatted, "format": fmt}


# 节点执行器注册表
EXECUTORS: dict[str, NodeExecutor] = {
    "document_input": DocumentInputExecutor(),
    "text_splitter": TextSplitterExecutor(),
    "embedding": EmbeddingExecutor(),
    "retriever": RetrieverExecutor(),
    "llm_answer": LLMAnswerExecutor(),
    "output": OutputExecutor(),
}


def topological_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """对工作流节点拓扑排序，返回节点ID执行顺序。检测环路。"""
    node_ids = {n["id"] for n in nodes}
    in_degree = {nid: 0 for nid in node_ids}
    adj = {nid: [] for nid in node_ids}

    for e in edges:
        src, tgt = e["source"], e["target"]
        if src not in node_ids or tgt not in node_ids:
            continue
        adj[src].append(tgt)
        in_degree[tgt] += 1

    q = deque([nid for nid, deg in in_degree.items() if deg == 0])
    order = []
    while q:
        cur = q.popleft()
        order.append(cur)
        for nxt in adj[cur]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                q.append(nxt)

    if len(order) != len(node_ids):
        raise ValueError("Workflow contains a cycle")

    return order


async def execute_workflow(
    workflow: dict,
    status_callback=None,
) -> dict:
    """
    执行工作流 DAG。

    Args:
        workflow: {"id", "name", "nodes": [...], "edges": [...]}
        status_callback: async callback(node_id, status, data) 用于 WebSocket 推送

    Returns:
        {"run_id", "status", "node_results": [...], "final_output": "..."}
    """
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])
    node_map = {n["id"]: n for n in nodes}
    node_order = topological_sort(nodes, edges)

    run_id = str(uuid.uuid4())
    started_at = datetime.now().isoformat()
    node_results = []
    node_outputs = {}  # node_id → output dict
    final_status = "completed"

    async def push_status(node_id, status, data=None):
        node_results.append({
            "node_id": node_id,
            "status": status,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        })
        if status_callback:
            await status_callback(node_id, status, data)

    for node_id in node_order:
        node = node_map[node_id]
        node_type = node.get("data", {}).get("nodeType", "")
        config = node.get("data", {})

        executor = EXECUTORS.get(node_type)
        if not executor:
            await push_status(node_id, "error", {"error": f"Unknown node type: {node_type}"})
            final_status = "failed"
            break

        # Collect inputs from upstream nodes
        upstream_inputs = {}
        for e in edges:
            if e["target"] == node_id:
                src_output = node_outputs.get(e["source"], {})
                upstream_inputs.update(src_output)

        await push_status(node_id, "running")
        start = time.time()
        try:
            result = await executor.execute(config, upstream_inputs)
            result["duration_ms"] = round((time.time() - start) * 1000)
            node_outputs[node_id] = result
            await push_status(node_id, "done", result)
        except Exception as exc:
            await push_status(node_id, "error", {"error": str(exc), "duration_ms": round((time.time() - start) * 1000)})
            final_status = "failed"
            break

    # Collect final output (from the last "output" type node or last node)
    final_output = ""
    for node_id in reversed(node_order):
        output = node_outputs.get(node_id, {})
        if node_map[node_id].get("data", {}).get("nodeType") == "output":
            final_output = output.get("formatted", json.dumps(output, ensure_ascii=False))
            break
    if not final_output:
        last_out = node_outputs.get(node_order[-1], {}) if node_order else {}
        final_output = json.dumps(last_out, ensure_ascii=False, indent=2)

    completed_at = datetime.now().isoformat()
    run_record = {
        "run_id": run_id,
        "workflow_id": workflow.get("id", "unknown"),
        "workflow_name": workflow.get("name", "unnamed"),
        "status": final_status,
        "started_at": started_at,
        "completed_at": completed_at,
        "node_results": node_results,
        "final_output": final_output,
    }

    # Persist run record
    (RUNS_DIR / f"{run_id}.json").write_text(
        json.dumps(run_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if status_callback:
        await status_callback(None, "run_complete", {"run_id": run_id, "status": final_status})

    return run_record
