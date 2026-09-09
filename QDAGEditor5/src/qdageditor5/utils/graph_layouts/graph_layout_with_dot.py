import glob
import os
import shutil
from typing import Hashable

from qdageditor5.models.standard_dag_model import StandardDAGModel


def _ensure_dot_on_path() -> None:
    """Patch PATH for this process if 'dot' isn't resolvable yet.

    Long-running processes (e.g. a VS Code window) keep the PATH they were
    started with, so a Graphviz install done afterwards won't be picked up
    until the process restarts. Look in common install locations instead.
    """
    if shutil.which("dot"):
        return

    candidates = glob.glob(r"C:\Program Files\Graphviz*\bin") + glob.glob(r"C:\Program Files (x86)\Graphviz*\bin")
    for bin_dir in candidates:
        if os.path.isfile(os.path.join(bin_dir, "dot.exe")):
            os.environ["PATH"] += os.pathsep + bin_dir
            return


def layout_graph_model_with_dot(model: "StandardDAGModel") -> dict[Hashable, tuple[float, float]]:
    """
    Layout the graph model using Graphviz's `dot` (via pydot).

    Edges are added in each node's inlet order and `ordering="in"` is set on
    every node, so dot keeps a node's incoming edges (and their upstream
    siblings) in that exact order during crossing minimization, instead of
    only nudging the initial order like the grandalf-based layout does.

    Returns a dictionary mapping node keys to (x, y) positions, centered at (0, 0).

    Raises:
        ImportError: if pydot is not installed.
        RuntimeError: if the Graphviz `dot` executable is unavailable or produces no layout.
    """
    import pydot

    _ensure_dot_on_path()

    node_ids = list(model.nodes())
    node_names = {node_id: f"n{i}" for i, node_id in enumerate(node_ids)}

    dot = pydot.Dot(graph_type="digraph", rankdir="TB", nodesep="0.5", ranksep="0.75")
    for node_id in node_ids:
        dot.add_node(pydot.Node(
            node_names[node_id],
            ordering="in",
            shape="box",
            fixedsize="true",
            width=str(100 / 72),
            height=str(100 / 72),
        ))

    # index incoming links by (target, inlet) so edges are added in inlet order;
    # combined with ordering="in" this keeps siblings aligned with target inlets
    links_by_target_inlet = {(v, inlet): u for u, _, v, inlet in model.links()}
    for node_id in node_ids:
        for inlet in model.inlets(node_id):
            u = links_by_target_inlet.get((node_id, inlet))
            if u in node_names:
                dot.add_edge(pydot.Edge(node_names[u], node_names[node_id]))

    rendered = dot.create_dot(prog="dot").decode()
    layouts = pydot.graph_from_dot_data(rendered)
    if not layouts:
        raise RuntimeError("Graphviz 'dot' produced no output.")
    layout_graph = layouts[0]

    name_to_id = {name: node_id for node_id, name in node_names.items()}
    raw_positions: dict[Hashable, tuple[float, float]] = {}
    for pydot_node in layout_graph.get_nodes():
        node_id = name_to_id.get(pydot_node.get_name().strip('"'))
        pos = pydot_node.get_pos()
        if node_id is None or not pos:
            continue
        x_str, y_str = pos.strip('"').split(",")
        # dot's y grows upward; negate to match the top-down scene convention used elsewhere
        raw_positions[node_id] = (float(x_str), -float(y_str))

    if not raw_positions:
        return {}

    xs = [x for x, _ in raw_positions.values()]
    ys = [y for _, y in raw_positions.values()]
    center_x = (min(xs) + max(xs)) / 2.0
    center_y = (min(ys) + max(ys)) / 2.0

    return {
        node_id: (x - center_x, y - center_y)
        for node_id, (x, y) in raw_positions.items()
    }