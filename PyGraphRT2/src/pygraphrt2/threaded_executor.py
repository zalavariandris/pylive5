from collections.abc import Callable
from copy import deepcopy
from typing import Hashable, Iterable, Tuple, Any, TYPE_CHECKING

from .graph import Graph, NodeRef


from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeStateSnapshot:
    """Captured callable and inputs for one computation."""
    operator: Callable|None
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)


class ThreadedExecutor:
    def __init__(self, graph:'Graph', cache:dict['NodeRef', Any]|None = None):
        self.graph = graph
        self.cache = cache

    async def prepare(self, targets: Iterable['NodeRef'])->dict['NodeRef', 'NodeStateSnapshot']:
        all_targets = tuple(dict.fromkeys(targets))
        existing_nodes = set(self.graph.nodes())
        for target in all_targets:
            if target not in existing_nodes:
                raise ValueError(f"Node {target} is not in the graph.")
    
        cache = self.cache if self.cache is not None else {}
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
            node_state = self.graph._nodes[node]
            for value in (*node_state.args, *node_state.kwargs.values()):
                if isinstance(value, NodeRef):
                    pending.append(value)
    
        # Sorting only uncached work also detects cycles in that remaining work.
        ordered_nodes = self.graph.topological_sort(needed)
        memo: dict[int, Any] = {}
        initial_outputs = {
            node_ref: deepcopy(cache[node_ref], memo)
            for node_ref in cached_nodes
        }
    
        snapshots: dict['NodeRef', NodeStateSnapshot] = {}
        for node_ref in ordered_nodes:
            node_state = self.graph._nodes[node_ref]
            func = node_state.operator
            snapshot = NodeStateSnapshot(
                operator=func,
                args=[
                    val if isinstance(val, NodeRef) else val
                    for val in node_state.args
                ],
                kwargs={
                    key: val if isinstance(val, NodeRef) else val
                    for key, val in node_state.kwargs.items()
                }
            )
            snapshots[node_ref] = snapshot
        return snapshots

    async def execute(self, target:'NodeRef')->dict['NodeRef', Any]:
        plan = await self.prepare([target])

        outputs: dict[NodeRef, Any] = {}
        for node_ref, snapshot in plan.items():
            resolved_args = [
                outputs[val] if isinstance(val, NodeRef) else val
                for val in snapshot.args
            ]
            resolved_kwargs = {
                key: outputs[val] if isinstance(val, NodeRef) else val
                for key, val in snapshot.kwargs.items()
            }
            if snapshot.operator is None:
                raise ValueError(f"Operator for node {node_ref} is not resolved.")
            output = snapshot.operator(*resolved_args, **resolved_kwargs)
            outputs[node_ref] = output

        return outputs



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


    