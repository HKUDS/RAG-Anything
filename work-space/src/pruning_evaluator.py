"""
Pruning Evaluator - Đánh giá chất lượng các thuật toán pruning.

Metrics:
1. Hub Retention: % top hubs được giữ lại
2. Bridge Retention: % top bridges được giữ lại
3. Cluster Coverage: % clusters có đại diện
4. Connectivity: Tỉ lệ largest connected component
5. Avg Degree: Mật độ trung bình của pruned graph
6. LLM Score: Đánh giá từ LLM (optional, có fallback nếu lỗi)
"""

import networkx as nx
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
import json

logger = logging.getLogger("PruningEvaluator")


@dataclass
class EvaluationResult:
    """Kết quả đánh giá một thuật toán pruning."""
    algorithm_id: str
    algorithm_name: str
    max_nodes: int
    actual_nodes: int
    actual_edges: int

    # Graph Metrics
    hub_retention: float = 0.0
    bridge_retention: float = 0.0
    cluster_coverage: float = 0.0
    connectivity: float = 0.0
    avg_degree: float = 0.0

    # LLM Evaluation (optional)
    llm_score: Optional[float] = None
    llm_reasoning: Optional[str] = None
    llm_error: Optional[str] = None

    # Weighted Score
    weighted_score: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "algorithm_id": self.algorithm_id,
            "algorithm_name": self.algorithm_name,
            "max_nodes": self.max_nodes,
            "actual_nodes": self.actual_nodes,
            "actual_edges": self.actual_edges,
            "hub_retention": round(self.hub_retention, 4),
            "bridge_retention": round(self.bridge_retention, 4),
            "cluster_coverage": round(self.cluster_coverage, 4),
            "connectivity": round(self.connectivity, 4),
            "avg_degree": round(self.avg_degree, 4),
            "llm_score": round(self.llm_score, 4) if self.llm_score is not None else None,
            "llm_reasoning": self.llm_reasoning,
            "llm_error": self.llm_error,
            "weighted_score": round(self.weighted_score, 4),
        }


class PruningEvaluator:
    """
    Đánh giá chất lượng của pruned graph so với full graph.
    """

    def __init__(
        self,
        G_full: nx.Graph,
        top_k: int = 20,
        weights: Optional[Dict[str, float]] = None
    ):
        """
        Args:
            G_full: Full graph gốc
            top_k: Số lượng top nodes để tính retention (default 20)
            weights: Weights cho weighted score (default balanced)
        """
        self.G_full = G_full
        self.top_k = top_k
        self.weights = weights or {
            "hub_retention": 0.20,
            "bridge_retention": 0.20,
            "cluster_coverage": 0.25,
            "connectivity": 0.20,
            "avg_degree": 0.05,
            "llm_score": 0.10,  # LLM score có weight thấp hơn vì optional
        }

        # Pre-compute ground truth từ full graph
        self._compute_ground_truth()

    def _compute_ground_truth(self):
        """Tính toán các metrics chuẩn từ full graph."""
        logger.info("Computing ground truth metrics from full graph...")

        # Top-k hubs by degree
        degrees = dict(self.G_full.degree())
        sorted_by_degree = sorted(degrees.items(), key=lambda x: x[1], reverse=True)
        self.top_hubs: Set[str] = set(n for n, _ in sorted_by_degree[:self.top_k])

        # Top-k bridges by betweenness
        try:
            betweenness = nx.betweenness_centrality(self.G_full)
            sorted_by_between = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)
            self.top_bridges: Set[str] = set(n for n, _ in sorted_by_between[:self.top_k])
        except Exception as e:
            logger.warning(f"Betweenness calculation failed: {e}")
            self.top_bridges = self.top_hubs.copy()

        # Louvain clusters
        try:
            self.clusters: List[Set] = list(nx.community.louvain_communities(self.G_full, seed=42))
        except Exception as e:
            logger.warning(f"Louvain detection failed: {e}")
            self.clusters = [set(self.G_full.nodes())]

        # Full graph stats for reference
        self.full_nodes = self.G_full.number_of_nodes()
        self.full_edges = self.G_full.number_of_edges()
        self.full_avg_degree = (2 * self.full_edges / self.full_nodes) if self.full_nodes > 0 else 0

        logger.info(f"Ground truth: {self.full_nodes} nodes, {self.full_edges} edges, "
                    f"{len(self.clusters)} clusters, top_k={self.top_k}")

    def _calc_hub_retention(self, G_pruned: nx.Graph) -> float:
        """% của top-k hubs được giữ lại trong pruned graph."""
        pruned_nodes = set(G_pruned.nodes())
        retained = len(self.top_hubs & pruned_nodes)
        return retained / len(self.top_hubs) if self.top_hubs else 0.0

    def _calc_bridge_retention(self, G_pruned: nx.Graph) -> float:
        """% của top-k bridges được giữ lại trong pruned graph."""
        pruned_nodes = set(G_pruned.nodes())
        retained = len(self.top_bridges & pruned_nodes)
        return retained / len(self.top_bridges) if self.top_bridges else 0.0

    def _calc_cluster_coverage(self, G_pruned: nx.Graph) -> float:
        """% clusters có ít nhất 1 node đại diện trong pruned graph."""
        pruned_nodes = set(G_pruned.nodes())
        covered = sum(1 for cluster in self.clusters if cluster & pruned_nodes)
        return covered / len(self.clusters) if self.clusters else 0.0

    def _calc_connectivity(self, G_pruned: nx.Graph) -> float:
        """Tỉ lệ largest connected component / total pruned nodes."""
        if G_pruned.number_of_nodes() == 0:
            return 0.0

        if G_pruned.is_directed():
            components = list(nx.weakly_connected_components(G_pruned))
        else:
            components = list(nx.connected_components(G_pruned))

        if not components:
            return 0.0

        largest_cc = max(components, key=len)
        return len(largest_cc) / G_pruned.number_of_nodes()

    def _calc_avg_degree(self, G_pruned: nx.Graph) -> float:
        """Average degree của pruned graph (normalized by full graph avg degree)."""
        if G_pruned.number_of_nodes() == 0:
            return 0.0

        pruned_avg_degree = 2 * G_pruned.number_of_edges() / G_pruned.number_of_nodes()

        # Normalize: 1.0 = same density as full graph
        if self.full_avg_degree > 0:
            return min(1.0, pruned_avg_degree / self.full_avg_degree)
        return 0.0

    def _calc_weighted_score(self, result: EvaluationResult) -> float:
        """Tính weighted score từ tất cả metrics."""
        score = 0.0
        total_weight = 0.0

        for metric, weight in self.weights.items():
            value = getattr(result, metric, None)
            if value is not None:
                score += weight * value
                total_weight += weight

        # Normalize nếu có metrics missing (như llm_score)
        if total_weight > 0:
            return score / total_weight
        return 0.0

    def evaluate(
        self,
        G_pruned: nx.Graph,
        algorithm_id: str,
        algorithm_name: str,
        max_nodes: int
    ) -> EvaluationResult:
        """
        Đánh giá một pruned graph.

        Args:
            G_pruned: Pruned graph đã được xử lý
            algorithm_id: ID của thuật toán
            algorithm_name: Tên thuật toán
            max_nodes: Số max nodes đã set

        Returns:
            EvaluationResult với tất cả metrics
        """
        result = EvaluationResult(
            algorithm_id=algorithm_id,
            algorithm_name=algorithm_name,
            max_nodes=max_nodes,
            actual_nodes=G_pruned.number_of_nodes(),
            actual_edges=G_pruned.number_of_edges(),
        )

        # Calculate graph metrics
        result.hub_retention = self._calc_hub_retention(G_pruned)
        result.bridge_retention = self._calc_bridge_retention(G_pruned)
        result.cluster_coverage = self._calc_cluster_coverage(G_pruned)
        result.connectivity = self._calc_connectivity(G_pruned)
        result.avg_degree = self._calc_avg_degree(G_pruned)

        # Calculate weighted score (without LLM for now)
        result.weighted_score = self._calc_weighted_score(result)

        return result

    async def evaluate_with_llm(
        self,
        G_pruned: nx.Graph,
        algorithm_id: str,
        algorithm_name: str,
        max_nodes: int,
        llm_func=None
    ) -> EvaluationResult:
        """
        Đánh giá với cả LLM evaluation.

        Args:
            G_pruned: Pruned graph
            algorithm_id: ID thuật toán
            algorithm_name: Tên thuật toán
            max_nodes: Số max nodes
            llm_func: Async LLM function (optional)

        Returns:
            EvaluationResult với đầy đủ metrics + LLM score
        """
        # First get basic metrics
        result = self.evaluate(G_pruned, algorithm_id, algorithm_name, max_nodes)

        # Try LLM evaluation if available
        if llm_func is not None:
            try:
                llm_result = await self._llm_evaluate(G_pruned, llm_func)
                result.llm_score = llm_result.get("score")
                result.llm_reasoning = llm_result.get("reasoning")
            except Exception as e:
                logger.warning(f"LLM evaluation failed: {e}")
                result.llm_error = str(e)
                result.llm_score = None

        # Recalculate weighted score with LLM
        result.weighted_score = self._calc_weighted_score(result)

        return result

    async def _llm_evaluate(self, G_pruned: nx.Graph, llm_func) -> Dict:
        """
        Gọi LLM để đánh giá chất lượng của pruned graph.

        Returns:
            {"score": 0.0-1.0, "reasoning": "..."}
        """
        # Prepare graph summary for LLM
        nodes_sample = list(G_pruned.nodes())[:20]  # Sample 20 nodes
        edges_sample = list(G_pruned.edges())[:30]  # Sample 30 edges

        # Get node labels/descriptions if available
        node_info = []
        for node in nodes_sample:
            label = G_pruned.nodes[node].get("label", str(node))
            node_type = G_pruned.nodes[node].get("entity_type", "unknown")
            node_info.append(f"- {label} ({node_type})")

        edge_info = []
        for u, v in edges_sample:
            u_label = G_pruned.nodes[u].get("label", str(u))
            v_label = G_pruned.nodes[v].get("label", str(v))
            edge_info.append(f"- {u_label} -- {v_label}")

        prompt = f"""You are evaluating the quality of a pruned knowledge graph for visualization.

TASK: Rate how well this subset of {G_pruned.number_of_nodes()} nodes represents the key concepts and relationships from a larger graph of {self.full_nodes} nodes.

PRUNED GRAPH STATISTICS:
- Nodes: {G_pruned.number_of_nodes()}
- Edges: {G_pruned.number_of_edges()}
- Connected Components: {nx.number_connected_components(G_pruned)}

SAMPLE NODES (showing {len(node_info)} of {G_pruned.number_of_nodes()}):
{chr(10).join(node_info)}

SAMPLE EDGES (showing {len(edge_info)} of {G_pruned.number_of_edges()}):
{chr(10).join(edge_info)}

EVALUATION CRITERIA:
1. Diversity: Are different types of entities represented?
2. Connectivity: Do the nodes form a connected structure?
3. Importance: Do the nodes seem to be key concepts (not trivial)?
4. Relationships: Are meaningful relationships preserved?

RESPOND IN JSON FORMAT ONLY:
{{
    "score": <float 0.0 to 1.0>,
    "reasoning": "<brief explanation in 2-3 sentences>"
}}
"""

        try:
            response = await llm_func(prompt)

            # Parse JSON response
            # Try to extract JSON from response
            response_text = response if isinstance(response, str) else str(response)

            # Find JSON in response
            import re
            json_match = re.search(r'\{[^{}]*"score"[^{}]*\}', response_text, re.DOTALL)

            if json_match:
                result = json.loads(json_match.group())
                score = float(result.get("score", 0.5))
                score = max(0.0, min(1.0, score))  # Clamp to [0, 1]
                return {
                    "score": score,
                    "reasoning": result.get("reasoning", "No reasoning provided")
                }
            else:
                logger.warning("Could not parse LLM JSON response")
                return {"score": None, "reasoning": "Failed to parse response"}

        except Exception as e:
            logger.error(f"LLM evaluation error: {e}")
            raise


class PruningBenchmark:
    """
    Chạy benchmark so sánh nhiều thuật toán pruning.
    """

    def __init__(self, G_full: nx.Graph, max_nodes: int = 50):
        """
        Args:
            G_full: Full graph gốc
            max_nodes: Số nodes tối đa cho pruning
        """
        self.G_full = G_full
        self.max_nodes = max_nodes
        self.evaluator = PruningEvaluator(G_full)
        self.results: List[EvaluationResult] = []

    def run(
        self,
        algorithms: Dict,
        ensure_coverage: bool = True
    ) -> List[EvaluationResult]:
        """
        Chạy benchmark cho tất cả thuật toán.

        Args:
            algorithms: Dict của PruningAlgorithm
            ensure_coverage: Đảm bảo chunk coverage

        Returns:
            List các EvaluationResult, sorted by weighted_score
        """
        from .pruning_algorithms import PruningAlgorithm

        self.results = []

        for alg_id, alg in algorithms.items():
            logger.info(f"Benchmarking: {alg.name}...")

            try:
                # Run pruning
                G_pruned = alg.prune_func(self.G_full, self.max_nodes, ensure_coverage)

                # Evaluate
                result = self.evaluator.evaluate(
                    G_pruned, alg.id, alg.name, self.max_nodes
                )
                self.results.append(result)

                logger.info(f"  → Score: {result.weighted_score:.4f} "
                            f"(hub={result.hub_retention:.2f}, "
                            f"bridge={result.bridge_retention:.2f}, "
                            f"cluster={result.cluster_coverage:.2f})")

            except Exception as e:
                logger.error(f"  → Failed: {e}")
                # Add failed result
                self.results.append(EvaluationResult(
                    algorithm_id=alg_id,
                    algorithm_name=alg.name,
                    max_nodes=self.max_nodes,
                    actual_nodes=0,
                    actual_edges=0,
                    llm_error=str(e)
                ))

        # Sort by weighted score (descending)
        self.results.sort(key=lambda r: r.weighted_score, reverse=True)

        return self.results

    async def run_with_llm(
        self,
        algorithms: Dict,
        llm_func,
        ensure_coverage: bool = True
    ) -> List[EvaluationResult]:
        """
        Chạy benchmark với cả LLM evaluation.

        Args:
            algorithms: Dict của PruningAlgorithm
            llm_func: Async LLM function
            ensure_coverage: Đảm bảo chunk coverage

        Returns:
            List các EvaluationResult với LLM scores
        """
        self.results = []

        for alg_id, alg in algorithms.items():
            logger.info(f"Benchmarking with LLM: {alg.name}...")

            try:
                # Run pruning
                G_pruned = alg.prune_func(self.G_full, self.max_nodes, ensure_coverage)

                # Evaluate with LLM
                result = await self.evaluator.evaluate_with_llm(
                    G_pruned, alg.id, alg.name, self.max_nodes, llm_func
                )
                self.results.append(result)

                llm_str = f"llm={result.llm_score:.2f}" if result.llm_score else "llm=N/A"
                logger.info(f"  → Score: {result.weighted_score:.4f} "
                            f"(hub={result.hub_retention:.2f}, "
                            f"bridge={result.bridge_retention:.2f}, "
                            f"{llm_str})")

            except Exception as e:
                logger.error(f"  → Failed: {e}")
                self.results.append(EvaluationResult(
                    algorithm_id=alg_id,
                    algorithm_name=alg.name,
                    max_nodes=self.max_nodes,
                    actual_nodes=0,
                    actual_edges=0,
                    llm_error=str(e)
                ))

        # Sort by weighted score
        self.results.sort(key=lambda r: r.weighted_score, reverse=True)

        return self.results

    def to_csv(self, filepath: str):
        """Export kết quả ra CSV."""
        import csv

        if not self.results:
            logger.warning("No results to export")
            return

        fieldnames = [
            "algorithm_id", "algorithm_name", "max_nodes",
            "actual_nodes", "actual_edges",
            "hub_retention", "bridge_retention", "cluster_coverage",
            "connectivity", "avg_degree", "llm_score", "weighted_score"
        ]

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for result in self.results:
                row = result.to_dict()
                # Only write specified fields
                filtered_row = {k: row.get(k) for k in fieldnames}
                writer.writerow(filtered_row)

        logger.info(f"Exported benchmark results to {filepath}")

    def get_best_algorithm(self) -> Optional[EvaluationResult]:
        """Trả về thuật toán có score cao nhất."""
        if not self.results:
            return None
        return self.results[0]  # Already sorted

    def get_summary(self) -> str:
        """Trả về summary text của benchmark."""
        if not self.results:
            return "No benchmark results available."

        lines = [
            f"=== PRUNING BENCHMARK RESULTS (max_nodes={self.max_nodes}) ===",
            f"Full graph: {self.evaluator.full_nodes} nodes, {self.evaluator.full_edges} edges",
            "",
            "Ranking:",
        ]

        for i, result in enumerate(self.results, 1):
            llm_str = f", LLM={result.llm_score:.2f}" if result.llm_score else ""
            lines.append(
                f"  {i}. {result.algorithm_name}: {result.weighted_score:.4f} "
                f"(Hub={result.hub_retention:.2f}, Bridge={result.bridge_retention:.2f}, "
                f"Cluster={result.cluster_coverage:.2f}{llm_str})"
            )

        if self.results:
            best = self.results[0]
            lines.append("")
            lines.append(f"RECOMMENDED: {best.algorithm_name} (score={best.weighted_score:.4f})")

        return "\n".join(lines)
