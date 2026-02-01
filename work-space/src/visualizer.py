import networkx as nx
from pyvis.network import Network
from pathlib import Path
import logging
from typing import Optional

from .pruning_algorithms import get_algorithm

logger = logging.getLogger("Visualizer")


class GraphVisualizer:
    def __init__(self, storage_dir: str):
        self.graph_path = Path(storage_dir) / "graph_chunk_entity_relation.graphml"
        self.output_path = Path(storage_dir) / "interactive_graph.html"
        self._G_full: Optional[nx.Graph] = None  # Cache full graph

    def load_graph(self) -> Optional[nx.Graph]:
        """Load và cache full graph từ file."""
        if self._G_full is not None:
            return self._G_full

        if not self.graph_path.exists():
            logger.warning(f"Graph file not found: {self.graph_path}")
            return None

        try:
            self._G_full = nx.read_graphml(str(self.graph_path))
            logger.info(f"Loaded graph: {self._G_full.number_of_nodes()} nodes, "
                        f"{self._G_full.number_of_edges()} edges")
            return self._G_full
        except Exception as e:
            logger.error(f"Error loading graph: {e}")
            return None

    def get_full_graph(self) -> Optional[nx.Graph]:
        """Lấy full graph (load nếu chưa có)."""
        return self.load_graph()

    @staticmethod
    def _score_nodes(G: nx.Graph) -> dict:
        """Return combined score using degree + PageRank for ranking."""
        degrees = dict(G.degree())
        try:
            pagerank = nx.pagerank(G)
        except Exception:
            pagerank = {n: 0 for n in G.nodes()}

        scores = {}
        for n in G.nodes():
            scores[n] = degrees.get(n, 0) + pagerank.get(n, 0)
        return scores

    @staticmethod
    def _prune_graph(
        G: nx.Graph,
        max_nodes: int = 50,
        ensure_chunk_coverage: bool = True,
    ) -> nx.Graph:
        """
        [DEPRECATED] Sử dụng prune_with_algorithm() thay thế.

        Prune graph to a smaller, meaningful subgraph using baseline algorithm.
        """
        # Delegate to baseline algorithm for backward compatibility
        from .pruning_algorithms import prune_baseline
        return prune_baseline(G, max_nodes, ensure_chunk_coverage)

    def prune_with_algorithm(
        self,
        algorithm_id: str = "hybrid",
        max_nodes: int = 50,
        ensure_coverage: bool = True
    ) -> Optional[nx.Graph]:
        """
        Prune graph sử dụng thuật toán được chỉ định.

        Args:
            algorithm_id: ID của thuật toán (baseline, betweenness, eigenvector, kcore, louvain, hybrid)
            max_nodes: Số nodes tối đa
            ensure_coverage: Đảm bảo chunk coverage

        Returns:
            Pruned graph hoặc None nếu lỗi
        """
        G = self.load_graph()
        if G is None:
            return None

        algorithm = get_algorithm(algorithm_id)
        logger.info(f"Pruning with {algorithm.name} (max_nodes={max_nodes})")

        try:
            G_pruned = algorithm.prune_func(G, max_nodes, ensure_coverage)
            logger.info(f"Pruned: {G_pruned.number_of_nodes()} nodes, "
                        f"{G_pruned.number_of_edges()} edges")
            return G_pruned
        except Exception as e:
            logger.error(f"Pruning failed: {e}")
            return None

    def generate_html(
        self,
        max_nodes: int = 50,
        algorithm_id: str = "hybrid"
    ):
        """
        Tạo file HTML tương tác.
        Chỉ vẽ Top 'max_nodes' quan trọng nhất để tránh bị rối (Hairball).

        Args:
            max_nodes: Số nodes tối đa hiển thị
            algorithm_id: Thuật toán pruning (baseline, betweenness, eigenvector, kcore, louvain, hybrid)
        """
        if not self.graph_path.exists():
            return None

        try:
            # 1. Load Graph (sử dụng cache)
            G_full = self.load_graph()
            if G_full is None:
                return None
            total_nodes = G_full.number_of_nodes()

            # 2. Prune graph với thuật toán được chọn
            algorithm = get_algorithm(algorithm_id)
            G = algorithm.prune_func(G_full, max_nodes, ensure_coverage=True)

            # 3. Tạo PyVis Network
            net = Network(
                height="600px",
                width="100%",
                bgcolor="#ffffff",
                font_color="black",
                notebook=False,
            )
            net.from_nx(G)

            # 4. Tô màu Node (Phân biệt Text vs Multimodal)
            for node in net.nodes:
                desc = node.get("title", "").lower()  # PyVis map description vào title hover
                if "image" in desc or "table" in desc:
                    node["color"] = "#ff9999"  # Đỏ nhạt (Multimodal)
                    node["shape"] = "box"
                else:
                    node["color"] = "#97c2fc"  # Xanh nhạt (Text)

            # 5. Cấu hình Physics (Để graph bung lụa đẹp)
            net.set_options(
                """
            var options = {
              "physics": {
                "forceAtlas2Based": {
                  "gravitationalConstant": -50,
                  "centralGravity": 0.01,
                  "springLength": 100,
                  "springConstant": 0.08
                },
                "maxVelocity": 50,
                "solver": "forceAtlas2Based",
                "timestep": 0.35,
                "stabilization": {"iterations": 150}
              }
            }
            """
            )

            # 6. Save
            net.save_graph(str(self.output_path))
            pruned_nodes = G.number_of_nodes()
            logger.info(
                f"Graph visualized with {pruned_nodes}/{total_nodes} nodes "
                f"(algorithm={algorithm.name}, max_nodes={max_nodes})"
            )
            return str(self.output_path)

        except Exception as e:
            logger.error(f"Error visualizing graph: {e}")
            return None
