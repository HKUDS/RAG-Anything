"""
Pruning Algorithms for Knowledge Graph Visualization.

Các thuật toán để chọn N nodes "quan trọng nhất" từ full graph để hiển thị.
Không ảnh hưởng đến storage/retrieval - chỉ phục vụ visualization.
"""

from dataclasses import dataclass
from typing import Callable, Set, Dict, List
import networkx as nx
import logging

logger = logging.getLogger("PruningAlgorithms")


@dataclass
class PruningAlgorithm:
    """Định nghĩa một thuật toán pruning."""
    id: str
    name: str
    description: str
    prune_func: Callable[[nx.Graph, int, bool], nx.Graph]


def _get_chunk_nodes(G: nx.Graph) -> List[str]:
    """Lấy danh sách chunk nodes (có prefix 'chunk-')."""
    return [n for n in G.nodes() if str(n).startswith("chunk-")]


def _ensure_chunk_coverage(
    G: nx.Graph,
    keep_nodes: Set,
    scores: Dict,
    max_nodes: int
) -> Set:
    """
    Đảm bảo mỗi chunk có ít nhất 1 neighbor được giữ lại.
    Trả về set nodes đã được bổ sung.
    """
    chunk_nodes = _get_chunk_nodes(G)

    for chunk in chunk_nodes:
        neighbors = list(G.neighbors(chunk))
        if not neighbors:
            keep_nodes.add(chunk)
            continue
        best_neighbor = max(neighbors, key=lambda n: scores.get(n, 0))
        keep_nodes.update({chunk, best_neighbor})

    # Nếu coverage vượt quá max_nodes, trim theo score
    if len(keep_nodes) > max_nodes:
        keep_nodes = set(
            sorted(keep_nodes, key=lambda n: scores.get(n, 0), reverse=True)[:max_nodes]
        )

    return keep_nodes


# =============================================================================
# THUẬT TOÁN 1: BASELINE (Degree + PageRank) - Hiện tại đang dùng
# =============================================================================
def prune_baseline(G: nx.Graph, max_nodes: int = 50, ensure_coverage: bool = True) -> nx.Graph:
    """
    Thuật toán baseline: Degree + PageRank.

    Strategy:
    - Score = degree + pagerank
    - Giữ best neighbor per chunk (optional)
    - Fill remaining slots by global score
    """
    if max_nodes <= 0 or G.number_of_nodes() <= max_nodes:
        return G

    # Calculate scores
    degrees = dict(G.degree())
    try:
        pagerank = nx.pagerank(G)
    except Exception:
        pagerank = {n: 0 for n in G.nodes()}

    scores = {n: degrees.get(n, 0) + pagerank.get(n, 0) for n in G.nodes()}
    keep_nodes = set()

    # Ensure chunk coverage
    if ensure_coverage:
        keep_nodes = _ensure_chunk_coverage(G, keep_nodes, scores, max_nodes)

    # Fill remaining by score
    for node in sorted(G.nodes(), key=lambda n: scores.get(n, 0), reverse=True):
        if len(keep_nodes) >= max_nodes:
            break
        keep_nodes.add(node)

    return G.subgraph(keep_nodes).copy()


# =============================================================================
# THUẬT TOÁN 2: BETWEENNESS CENTRALITY - Ưu tiên Bridge Nodes
# =============================================================================
def prune_betweenness(G: nx.Graph, max_nodes: int = 50, ensure_coverage: bool = True) -> nx.Graph:
    """
    Ưu tiên nodes có betweenness centrality cao (bridge nodes).

    Bridge nodes là nodes kết nối các clusters, quan trọng cho việc
    hiểu cấu trúc tổng thể của knowledge graph.
    """
    if max_nodes <= 0 or G.number_of_nodes() <= max_nodes:
        return G

    try:
        betweenness = nx.betweenness_centrality(G)
    except Exception:
        logger.warning("Betweenness calculation failed, falling back to degree")
        betweenness = {n: G.degree(n) for n in G.nodes()}

    scores = betweenness
    keep_nodes = set()

    if ensure_coverage:
        keep_nodes = _ensure_chunk_coverage(G, keep_nodes, scores, max_nodes)

    for node in sorted(G.nodes(), key=lambda n: scores.get(n, 0), reverse=True):
        if len(keep_nodes) >= max_nodes:
            break
        keep_nodes.add(node)

    return G.subgraph(keep_nodes).copy()


# =============================================================================
# THUẬT TOÁN 3: EIGENVECTOR CENTRALITY - Nodes kết nối với nodes quan trọng
# =============================================================================
def prune_eigenvector(G: nx.Graph, max_nodes: int = 50, ensure_coverage: bool = True) -> nx.Graph:
    """
    Ưu tiên nodes có eigenvector centrality cao.

    Eigenvector centrality đo lường "nodes kết nối với nodes quan trọng khác",
    tốt hơn degree đơn thuần vì xét đến chất lượng connections.
    """
    if max_nodes <= 0 or G.number_of_nodes() <= max_nodes:
        return G

    try:
        eigenvector = nx.eigenvector_centrality_numpy(G)
    except Exception:
        logger.warning("Eigenvector calculation failed, falling back to degree")
        eigenvector = {n: G.degree(n) for n in G.nodes()}

    scores = eigenvector
    keep_nodes = set()

    if ensure_coverage:
        keep_nodes = _ensure_chunk_coverage(G, keep_nodes, scores, max_nodes)

    for node in sorted(G.nodes(), key=lambda n: scores.get(n, 0), reverse=True):
        if len(keep_nodes) >= max_nodes:
            break
        keep_nodes.add(node)

    return G.subgraph(keep_nodes).copy()


# =============================================================================
# THUẬT TOÁN 4: K-CORE DECOMPOSITION - Lấy "lõi" dense nhất
# =============================================================================
def prune_kcore(G: nx.Graph, max_nodes: int = 50, ensure_coverage: bool = True) -> nx.Graph:
    """
    K-Core decomposition: Giữ nodes trong core cao nhất.

    K-core là subgraph mà mọi node có ít nhất k neighbors.
    Nodes trong core cao = densely connected = quan trọng.
    """
    if max_nodes <= 0 or G.number_of_nodes() <= max_nodes:
        return G

    try:
        core_numbers = nx.core_number(G)
    except Exception:
        logger.warning("K-core calculation failed, falling back to degree")
        core_numbers = {n: G.degree(n) for n in G.nodes()}

    # Score = core number + degree (tie-breaker)
    degrees = dict(G.degree())
    max_degree = max(degrees.values()) if degrees else 1
    scores = {n: core_numbers.get(n, 0) + degrees.get(n, 0) / max_degree
              for n in G.nodes()}

    keep_nodes = set()

    if ensure_coverage:
        keep_nodes = _ensure_chunk_coverage(G, keep_nodes, scores, max_nodes)

    for node in sorted(G.nodes(), key=lambda n: scores.get(n, 0), reverse=True):
        if len(keep_nodes) >= max_nodes:
            break
        keep_nodes.add(node)

    return G.subgraph(keep_nodes).copy()


# =============================================================================
# THUẬT TOÁN 5: LOUVAIN COMMUNITY - Đảm bảo coverage từ mỗi cluster
# =============================================================================
def prune_louvain(G: nx.Graph, max_nodes: int = 50, ensure_coverage: bool = True) -> nx.Graph:
    """
    Community-aware pruning: Chọn top nodes từ mỗi Louvain community.

    Đảm bảo mỗi cluster/community có đại diện trong pruned graph,
    không bỏ sót nhóm entities nào.
    """
    if max_nodes <= 0 or G.number_of_nodes() <= max_nodes:
        return G

    # Detect communities
    try:
        communities = list(nx.community.louvain_communities(G, seed=42))
    except Exception:
        logger.warning("Louvain detection failed, falling back to baseline")
        return prune_baseline(G, max_nodes, ensure_coverage)

    if not communities:
        return prune_baseline(G, max_nodes, ensure_coverage)

    # Score by degree within each community
    degrees = dict(G.degree())

    # Proportional allocation: larger communities get more slots
    total_nodes = sum(len(c) for c in communities)
    keep_nodes = set()

    for community in communities:
        # Số slots cho community này (proportional to size)
        community_slots = max(1, int(max_nodes * len(community) / total_nodes))

        # Chọn top nodes trong community theo degree
        community_nodes = sorted(community, key=lambda n: degrees.get(n, 0), reverse=True)
        keep_nodes.update(community_nodes[:community_slots])

    # Fill remaining slots với global top degree
    for node in sorted(G.nodes(), key=lambda n: degrees.get(n, 0), reverse=True):
        if len(keep_nodes) >= max_nodes:
            break
        keep_nodes.add(node)

    # Trim nếu vượt quá
    if len(keep_nodes) > max_nodes:
        keep_nodes = set(
            sorted(keep_nodes, key=lambda n: degrees.get(n, 0), reverse=True)[:max_nodes]
        )

    return G.subgraph(keep_nodes).copy()


# =============================================================================
# THUẬT TOÁN 6: HYBRID - Kết hợp Community + Centrality (RECOMMENDED)
# =============================================================================
def prune_hybrid(G: nx.Graph, max_nodes: int = 50, ensure_coverage: bool = True) -> nx.Graph:
    """
    Hybrid approach: Community detection + Multi-centrality scoring.

    Strategy:
    1. Detect communities với Louvain
    2. Score = 0.4*betweenness + 0.4*eigenvector + 0.2*degree (normalized)
    3. Chọn top từ mỗi community theo hybrid score
    4. Fill remaining với global top

    Đây là thuật toán được recommend vì cân bằng giữa:
    - Bridge nodes (betweenness)
    - Important connections (eigenvector)
    - Local importance (degree)
    - Cluster coverage (community-aware)
    """
    if max_nodes <= 0 or G.number_of_nodes() <= max_nodes:
        return G

    # 1. Detect communities
    try:
        communities = list(nx.community.louvain_communities(G, seed=42))
    except Exception:
        communities = [set(G.nodes())]  # Treat as single community

    # 2. Calculate multi-centrality scores
    degrees = dict(G.degree())
    max_degree = max(degrees.values()) if degrees else 1
    norm_degrees = {n: degrees.get(n, 0) / max_degree for n in G.nodes()}

    try:
        betweenness = nx.betweenness_centrality(G)
    except Exception:
        betweenness = norm_degrees.copy()

    try:
        eigenvector = nx.eigenvector_centrality_numpy(G)
    except Exception:
        eigenvector = norm_degrees.copy()

    # Normalize betweenness và eigenvector
    max_between = max(betweenness.values()) if betweenness else 1
    max_eigen = max(eigenvector.values()) if eigenvector else 1

    # Hybrid score
    scores = {}
    for n in G.nodes():
        b = betweenness.get(n, 0) / max_between if max_between > 0 else 0
        e = eigenvector.get(n, 0) / max_eigen if max_eigen > 0 else 0
        d = norm_degrees.get(n, 0)
        scores[n] = 0.4 * b + 0.4 * e + 0.2 * d

    # 3. Select from each community
    keep_nodes = set()
    total_nodes = sum(len(c) for c in communities)

    for community in communities:
        community_slots = max(1, int(max_nodes * len(community) / total_nodes))
        community_nodes = sorted(community, key=lambda n: scores.get(n, 0), reverse=True)
        keep_nodes.update(community_nodes[:community_slots])

    # 4. Ensure chunk coverage nếu cần
    if ensure_coverage:
        chunk_nodes = _get_chunk_nodes(G)
        for chunk in chunk_nodes:
            if chunk not in keep_nodes:
                neighbors = list(G.neighbors(chunk))
                if neighbors:
                    best = max(neighbors, key=lambda n: scores.get(n, 0))
                    if len(keep_nodes) < max_nodes:
                        keep_nodes.update({chunk, best})

    # 5. Fill remaining
    for node in sorted(G.nodes(), key=lambda n: scores.get(n, 0), reverse=True):
        if len(keep_nodes) >= max_nodes:
            break
        keep_nodes.add(node)

    # Trim
    if len(keep_nodes) > max_nodes:
        keep_nodes = set(
            sorted(keep_nodes, key=lambda n: scores.get(n, 0), reverse=True)[:max_nodes]
        )

    return G.subgraph(keep_nodes).copy()


# =============================================================================
# REGISTRY - Tất cả thuật toán có sẵn
# =============================================================================
PRUNING_ALGORITHMS: Dict[str, PruningAlgorithm] = {
    "baseline": PruningAlgorithm(
        id="baseline",
        name="Degree + PageRank",
        description="Thuật toán mặc định: kết hợp degree và PageRank",
        prune_func=prune_baseline
    ),
    "betweenness": PruningAlgorithm(
        id="betweenness",
        name="Betweenness Centrality",
        description="Ưu tiên bridge nodes kết nối các clusters",
        prune_func=prune_betweenness
    ),
    "eigenvector": PruningAlgorithm(
        id="eigenvector",
        name="Eigenvector Centrality",
        description="Ưu tiên nodes kết nối với nodes quan trọng khác",
        prune_func=prune_eigenvector
    ),
    "kcore": PruningAlgorithm(
        id="kcore",
        name="K-Core Decomposition",
        description="Giữ nodes trong dense core của graph",
        prune_func=prune_kcore
    ),
    "louvain": PruningAlgorithm(
        id="louvain",
        name="Louvain Community",
        description="Đảm bảo coverage từ mỗi community/cluster",
        prune_func=prune_louvain
    ),
    "hybrid": PruningAlgorithm(
        id="hybrid",
        name="Hybrid (Recommended)",
        description="Kết hợp Community + Multi-centrality scoring",
        prune_func=prune_hybrid
    ),
}


def get_algorithm(algorithm_id: str) -> PruningAlgorithm:
    """Lấy thuật toán theo ID, fallback về baseline nếu không tìm thấy."""
    return PRUNING_ALGORITHMS.get(algorithm_id, PRUNING_ALGORITHMS["baseline"])


def list_algorithms() -> List[Dict]:
    """Liệt kê tất cả thuật toán có sẵn."""
    return [
        {"id": alg.id, "name": alg.name, "description": alg.description}
        for alg in PRUNING_ALGORITHMS.values()
    ]
