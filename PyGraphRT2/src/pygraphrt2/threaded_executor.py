from collections.abc import Callable
from typing import Hashable, Iterable, Tuple, Any, TYPE_CHECKING
if TYPE_CHECKING:
    from .graph import Graph, NodeRef

from typing import Iterable, Tuple, Any
from dataclasses import dataclass, field
from types import FunctionType, MappingProxyType
from typing import Mapping


class ThreadedExecutor:
    def __init__(self, graph:'Graph'):
        self.graph = graph

    async def execute(self, node_ref:'NodeRef')->dict['NodeRef', Any]:
        sorted_nodes = self.graph.topological_sort()

        outputs: dict['NodeRef', Any] = {}

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

@dataclass(frozen=True)
class NodeOutput:
    """Reference to an output computed or supplied within this plan."""
    node_id: Hashable

@dataclass(frozen=True)
class NodeSnapshot:
    """Captured callable and inputs for one computation."""
    operator: Callable
    args: tuple[Any, ...] = ()
    kwargs: tuple[tuple[str, Any], ...] = ()
    output_id: NodeOutput

@dataclass(frozen=True)
class Plan:
    """One execution's computations and copies of required cached outputs.

    ``nodes`` contains only uncached work, in dependency order. Initial outputs
    include cached targets and cached dependencies at which traversal stopped.
    Values inside this shallowly frozen plan must be treated as read-only by
    operators. Callable globals and closures are not deep-copied.
    """

    revision: int
    targets: tuple[str, ...]
    nodes: tuple[NodeSnapshot, ...]
    initial_outputs: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

def _prepare(
        graph: 'Graph', 
        targets: Iterable[NodeRef]
    ):
    all_targets = tuple(dict.fromkeys(targets))
    existing_nodes = set(graph.nodes())
    for target in all_targets:
        if target not in existing_nodes:
            raise ValueError(f"Node {target} is not in the graph.")

    cache = cached_outputs if cached_outputs is not None else {}
    needed: set[NodeRef] = set()
    visited: set[NodeRef] = set()
    cached_nodes: list[NodeRef] = []
    pending = list(reversed(all_targets))
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)

        if node in cache:
            cached_nodes.append(node)
            continue

        needed.add(node)
        args, kwargs = node.get_inputs()
        for value in (*args, *kwargs.values()):
            if isinstance(value, NodeRef):
                pending.append(value)

    # Sorting only uncached work also detects cycles in that remaining work.
    ordered_nodes = graph.topological_sort(needed)
    memo: dict[int, Any] = {}
    initial_outputs = {
        node.get_name(): deepcopy(cache[node], memo)
        for node in cached_nodes
    }

    def capture_input(value: Any) -> Any:
        if isinstance(value, NodeRef):
            return NodeOutput(value.get_name())
        return deepcopy(value, memo)

    snapshots: list[NodeSnapshot] = []
    for node_ref in ordered_nodes:
        node_state = graph._nodes[node_ref]
        args, kwargs = node.get_inputs()
        snapshots.append(
            NodeSnapshot(
                operator=_capture_operator(node.get_operator()),
                args=tuple(capture_input(value) for value in node_state.args),
                kwargs=tuple(
                    (name, capture_input(value)) for name, value in kwargs.items()
                ),
                 node_output_id=node.get_name()
            )
        )

    return ExecutionPlan(
        revision=revision,
        targets=tuple(node.get_name() for node in all_targets),
        nodes=tuple(snapshots),
        initial_outputs=MappingProxyType(initial_outputs),
    )
    

# def _execute(plan):
#     results: dict[NodeRef, Any] = {}

#     for node_snp in plan.nodes:
#         func = node_snp.operator
#         args = node_snp.args
#         kwargs = dict(node_snp.kwargs)

#         # Resolve NodeOutput to actual results
#         resolved_args = tuple(
#             results.get(arg.node_ref, arg) if isinstance(arg, NodeOutput) else arg 
#             for arg in args
#         )
#         resolved_kwargs = {
#             k: results.get(v.node_ref, v) if isinstance(v, NodeOutput) else v
#             for k, v in kwargs.items()
#         }

#         result = func(*resolved_args, **resolved_kwargs)
#         results[NodeRef(node_snp.name)] = result

#     return results

if __name__ == "__main__":
    import asyncio
    from pygraphrt2.graph import Graph, NodeRef
    import asyncio
    import time

    async def main():

        graph = Graph()
        @graph.node()
        def some_sleep():
            print("Execute sleep for 1 second...")
            time.sleep(1)
            print("Awake now.")
            return "Hello"

        executor = ThreadedExecutor(graph)
        outputs = await executor.execute(some_sleep)
        print(outputs)

    asyncio.run(main())


    