import json
import os
import logging
import networkx as nx
from pathlib import Path

logger = logging.getLogger("Metrics")

def extract_storage_stats(storage_dir: str):
    """
    Trích xuất số liệu thống kê.
    OUTPUT KEYS: nodes, edges, chunks, entities, relations
    """
    stats = {
        "nodes": 0,
        "edges": 0,
        "chunks": 0,
        "entities": 0,   # <--- Đã đổi từ entities_db thành entities
        "relations": 0   # <--- Đã đổi từ relations_db thành relations
    }
    
    storage_path = Path(storage_dir)
    
    try:
        # 1. Graph Stats (Nodes/Edges)
        graph_file = storage_path / "graph_chunk_entity_relation.graphml"
        if graph_file.exists():
            try:
                G = nx.read_graphml(str(graph_file))
                stats["nodes"] = G.number_of_nodes()
                stats["edges"] = G.number_of_edges()
            except Exception as e:
                logger.warning(f"Failed to parse GraphML: {e}")
            
        # 2. Doc Status (Total Chunks)
        doc_status_file = storage_path / "kv_store_doc_status.json"
        if doc_status_file.exists():
            with open(doc_status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                stats["chunks"] = sum(doc.get("chunks_count", 0) for doc in data.values())

        # 3. Entities Count
        entities_file = storage_path / "kv_store_full_entities.json"
        if entities_file.exists():
            with open(entities_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Đếm tổng entity unique
                stats["entities"] = sum(doc.get("count", 0) for doc in data.values())

        # 4. Relations Count
        relations_file = storage_path / "kv_store_full_relations.json"
        if relations_file.exists():
            with open(relations_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                stats["relations"] = sum(doc.get("count", 0) for doc in data.values())
                
    except Exception as e:
        logger.error(f"Error extracting metrics: {e}")
        
    return stats