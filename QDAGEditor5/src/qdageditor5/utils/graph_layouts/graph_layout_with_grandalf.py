from typing import Hashable

from qdageditor5.models.standard_dag_model import StandardDAGModel

from grandalf.graphs import Vertex,Edge,Graph,graph_core
from grandalf.layouts import SugiyamaLayout

def __model_to_grandalf_graph(model: "StandardDAGModel") -> "Graph":
    """
    Layout the graph model using grandalf library.
    Returns a dictionary mapping node keys to (x, y) positions.
    """
    # == create grandalf graph from model == 
    # Map original node keys to Grandalf Vertex objects safely
    vertex_map = {node_id: Vertex(node_id) for node_id in model.nodes()}

    # index incoming links by (target, inlet) so we can add edges in inlet order
    links_by_target_inlet = {(v, inlet): u for u, _, v, inlet in model.links()}

    # grandalf seeds each layer's initial vertex order from edge insertion order,
    # so adding edges in inlet order nudges siblings to line up with their target's inlets
    edges = []
    for node_id in model.nodes():
        for inlet in model.inlets(node_id):
            u = links_by_target_inlet.get((node_id, inlet))
            if u in vertex_map and node_id in vertex_map:
                edges.append(Edge(vertex_map[u], vertex_map[node_id]))

    return Graph(list(vertex_map.values()), reversed(edges))

def layout_graph_model_with_grandalf(model: "StandardDAGModel") -> dict[Hashable, tuple[float, float]]:
    # == Convert the model to a grandalf graph ==
    G = __model_to_grandalf_graph(model)

    # == Set up a dummy view object for each vertex (grandalf layout requirement) ==
    class VertexView:
        def __init__(self):
            self.w = 100.0
            self.h = 100.0

    for v in G.V():
        v.view = VertexView()

    # == Run the Sugiyama Layout for all connected components ==
    for component in G.C:
        sug = SugiyamaLayout(component)
        sug.init_all()
        sug.draw()
        
    # == Adjust component position to avoid overlap between disconnected components ==
    x_offset = 0.0
    component_padding = 50.0  # Space between disconnected parts
    for component in G.C:
        max_x_in_component = 0.0
        for v in component.V():
            if hasattr(v.view, 'xy'):
                x, y = v.view.xy
                v.view.xy = (x + x_offset, y)
                if x > max_x_in_component:
                    max_x_in_component = x
                    
        x_offset += max_x_in_component + component_padding

    # == Center everything at (0, 0) ==

    # compute the bounding box of all vertices
    raw_positions = {}
    for v in G.V():
        node_id = v.data  # Retrieve the original identifier passed to Vertex(node_id)
        if hasattr(v.view, 'xy'):
            raw_positions[node_id] = v.view.xy
        else:
            raw_positions[node_id] = (0.0, 0.0)

    if raw_positions:
        # Find the min and max bounds of the entire layout
        xs = [pos[0] for pos in raw_positions.values()]
        ys = [pos[1] for pos in raw_positions.values()]
        
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        
        # Calculate the geometric center of the layout bounding box
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        
        # Shift every node so that the center shifts to (0, 0)
        positions = {
            node_id: (x - center_x, y - center_y) 
            for node_id, (x, y) in raw_positions.items()
        }
    else:
        positions = {}

    return positions
    
