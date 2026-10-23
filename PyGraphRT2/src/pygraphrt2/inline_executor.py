from .graph import Graph, NodeRef
from typing import Iterable, Tuple, Any


class InlineExecutor:
    def __init__(self, graph:Graph):
        self.graph = graph

    def execute(self, node_ref:NodeRef)->dict[NodeRef, Any]:
        sorted_nodes = self.graph.topological_sort()

        outputs: dict[NodeRef, Any] = {}

        for node in sorted_nodes:
            node_state = node.resolve()
            resolved_args = [
                outputs[arg] if isinstance(arg, NodeRef) else arg 
                for loc, arg in enumerate(node_state.args)
            ]
            resolved_kwargs = {
                loc: outputs[arg] if isinstance(arg, NodeRef) else arg
                for loc, arg in node_state.kwargs.items()
            }
            op = node_state.operator
            if op is None:
                raise ValueError(f"Operator for node {node} is not resolved.")
            
            output = op(*resolved_args, **resolved_kwargs)
            outputs[node] = output

        return outputs