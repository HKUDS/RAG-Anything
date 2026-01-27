import networkx as nx
from pyvis.network import Network
from pathlib import Path
import logging

logger = logging.getLogger("Visualizer")

class GraphVisualizer:
    def __init__(self, storage_dir: str):
        self.graph_path = Path(storage_dir) / "graph_chunk_entity_relation.graphml"
        self.output_path = Path(storage_dir) / "interactive_graph.html"

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
        Prune graph to a smaller, meaningful subgraph.

        Strategy:
        - Score nodes by degree + pagerank.
        - (Optional) keep best neighbor per chunk to maintain document coverage.
        - Fill remaining slots by global score until max_nodes reached.
        """
        if max_nodes <= 0 or G.number_of_nodes() <= max_nodes:
            return G

        scores = GraphVisualizer._score_nodes(G)
        keep_nodes = set()

        # Identify chunk nodes by id prefix
        chunk_nodes = [n for n in G.nodes() if str(n).startswith("chunk-")]

        if ensure_chunk_coverage and chunk_nodes:
            for chunk in chunk_nodes:
                neighbors = list(G.neighbors(chunk))
                if not neighbors:
                    keep_nodes.add(chunk)
                    continue
                best_neighbor = max(neighbors, key=lambda n: scores.get(n, 0))
                keep_nodes.update({chunk, best_neighbor})

            # If coverage itself exceeds max_nodes, trim coverage by score
            if len(keep_nodes) > max_nodes:
                keep_nodes = set(
                    sorted(keep_nodes, key=lambda n: scores.get(n, 0), reverse=True)[
                        :max_nodes
                    ]
                )

        # Fill remaining slots by score
        for node in sorted(G.nodes(), key=lambda n: scores.get(n, 0), reverse=True):
            if len(keep_nodes) >= max_nodes:
                break
            keep_nodes.add(node)

        pruned = G.subgraph(keep_nodes).copy()
        return pruned

    def generate_html(self, max_nodes: int = 50):
        """
        Tạo file HTML tương tác.
        Chỉ vẽ Top 'max_nodes' quan trọng nhất để tránh bị rối (Hairball).
        """
        if not self.graph_path.exists():
            return None

        try:
            # 1. Load Graph
            G = nx.read_graphml(str(self.graph_path))
            total_nodes = G.number_of_nodes()

            # 2. Prune graph with chunk coverage
            G = self._prune_graph(G, max_nodes=max_nodes, ensure_chunk_coverage=True)

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
                f"Graph visualized with {pruned_nodes}/{total_nodes} nodes (max_nodes={max_nodes})"
            )
            return str(self.output_path)

        except Exception as e:
            logger.error(f"Error visualizing graph: {e}")
            return None
