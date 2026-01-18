import networkx as nx
from pyvis.network import Network
from pathlib import Path
import logging

logger = logging.getLogger("Visualizer")

class GraphVisualizer:
    def __init__(self, storage_dir: str):
        self.graph_path = Path(storage_dir) / "graph_chunk_entity_relation.graphml"
        self.output_path = Path(storage_dir) / "interactive_graph.html"

    def generate_html(self, max_nodes=100):
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
            
            # 2. Filter Nodes (Dùng Degree Centrality để lấy node quan trọng)
            if total_nodes > max_nodes:
                degrees = dict(G.degree())
                top_nodes = sorted(degrees, key=degrees.get, reverse=True)[:max_nodes]
                G = G.subgraph(top_nodes)

            # 3. Tạo PyVis Network
            net = Network(height="600px", width="100%", bgcolor="#ffffff", font_color="black", notebook=False)
            net.from_nx(G)

            # 4. Tô màu Node (Phân biệt Text vs Multimodal)
            for node in net.nodes:
                # Logic: Nếu node có description chứa 'image' hoặc 'table' -> Màu đỏ
                desc = node.get('title', '').lower() # PyVis map description vào title hover
                if 'image' in desc or 'table' in desc:
                    node['color'] = '#ff9999' # Đỏ nhạt (Multimodal)
                    node['shape'] = 'box'
                else:
                    node['color'] = '#97c2fc' # Xanh nhạt (Text)

            # 5. Cấu hình Physics (Để graph bung lụa đẹp)
            net.set_options("""
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
            """)

            # 6. Save
            net.save_graph(str(self.output_path))
            return str(self.output_path)

        except Exception as e:
            logger.error(f"Error visualizing graph: {e}")
            return None