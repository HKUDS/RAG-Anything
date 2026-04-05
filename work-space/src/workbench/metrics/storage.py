import json
import logging
from pathlib import Path

import networkx as nx
import tiktoken

logger = logging.getLogger("StorageMetrics")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(str(text)))
    except Exception:
        return 0


def extract_storage_stats(storage_dir: str):
    stats = {
        "nodes": 0,
        "edges": 0,
        "chunks": 0,
        "entities": 0,
        "relations": 0,
        "output_tokens": 0,
        "api_calls": 0,
    }

    path = Path(storage_dir)
    try:
        graph_path = path / "graph_chunk_entity_relation.graphml"
        if graph_path.exists():
            try:
                graph = nx.read_graphml(str(graph_path))
                stats["nodes"] = graph.number_of_nodes()
                stats["edges"] = graph.number_of_edges()
            except Exception:
                pass

        doc_status_path = path / "kv_store_doc_status.json"
        if doc_status_path.exists():
            with open(doc_status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stats["chunks"] = sum(d.get("chunks_count", 0) for d in data.values())

        entity_path = path / "kv_store_full_entities.json"
        if entity_path.exists():
            with open(entity_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stats["entities"] = sum(d.get("count", 0) for d in data.values())

        relation_path = path / "kv_store_full_relations.json"
        if relation_path.exists():
            with open(relation_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stats["relations"] = sum(d.get("count", 0) for d in data.values())

        cache_path = path / "kv_store_llm_response_cache.json"
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            stats["api_calls"] = len(cache)
            stats["output_tokens"] = sum(count_tokens(v.get("return", "")) for v in cache.values())
    except Exception as exc:
        logger.error("Metric extraction error: %s", exc)

    return stats
