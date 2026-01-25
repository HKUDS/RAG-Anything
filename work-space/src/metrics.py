import json
import logging
import networkx as nx
import tiktoken
from pathlib import Path

logger = logging.getLogger("Metrics")

def count_tokens(text: str) -> int:
    """Đếm token chuẩn (dùng cl100k_base)"""
    if not text: return 0
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(str(text)))
    except:
        return 0

def extract_storage_stats(storage_dir: str):
    stats = {
        "nodes": 0, "edges": 0, "chunks": 0, "entities": 0, "relations": 0,
        "output_tokens": 0, "api_calls": 0 # Default values
    }
    
    path = Path(storage_dir)
    
    try:
        # 1. GraphML (Nodes/Edges)
        if (path / "graph_chunk_entity_relation.graphml").exists():
            try:
                G = nx.read_graphml(str(path / "graph_chunk_entity_relation.graphml"))
                stats["nodes"] = G.number_of_nodes()
                stats["edges"] = G.number_of_edges()
            except: pass

        # 2. JSON Stats
        if (path / "kv_store_doc_status.json").exists():
            with open(path / "kv_store_doc_status.json", 'r') as f:
                data = json.load(f)
                stats["chunks"] = sum(d.get("chunks_count", 0) for d in data.values())

        if (path / "kv_store_full_entities.json").exists():
            with open(path / "kv_store_full_entities.json", 'r') as f:
                data = json.load(f)
                stats["entities"] = sum(d.get("count", 0) for d in data.values())

        if (path / "kv_store_full_relations.json").exists():
            with open(path / "kv_store_full_relations.json", 'r') as f:
                data = json.load(f)
                stats["relations"] = sum(d.get("count", 0) for d in data.values())

        # 3. Token Counting (Từ Cache)
        cache_file = path / "kv_store_llm_response_cache.json"
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                cache = json.load(f)
                stats["api_calls"] = len(cache)
                # Tính tổng output tokens
                stats["output_tokens"] = sum(count_tokens(v.get("return", "")) for v in cache.values())

    except Exception as e:
        logger.error(f"Metric extraction error: {e}")
        
    return stats