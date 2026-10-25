from collections.abc import Callable
from copy import deepcopy
from typing import Hashable, Iterable, Tuple, Any, TYPE_CHECKING

from .graph import Graph, NodeRef


from dataclasses import dataclass, field

from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
import time


@dataclass(frozen=True)
class NodeStateSnapshot:
    """Captured callable and inputs for one computation."""
    operator: Callable|None
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)


import os
import time
import asyncio

def cpu_intensive_task(duration: float) -> int:
    time.sleep(duration)  # Stand-in for the actual computation.
    return os.getpid()

@dataclass(frozen=True)
class NodeOutput:
    node_id: str

class MultiprocessExecutor:
    def __init__(self, graph:'Graph', cache:dict['NodeRef', Any]|None = None):
        self.graph = graph
        self.cache = cache
        self.process_executor = ProcessPoolExecutor(max_workers=1)

    async def prepare(self, targets: Iterable['NodeRef'])->tuple[dict[str, 'NodeStateSnapshot'], dict[str, 'NodeRef']]:
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
    
        plan: dict[str, NodeStateSnapshot] = {}
        mapping: dict[str, NodeRef] = {}
        for node_ref in ordered_nodes:
            node_state = self.graph._nodes[node_ref]
            func = node_state.operator
            snapshot = NodeStateSnapshot(
                operator=func,
                args=[
                    NodeOutput(node_id=val.name()) if isinstance(val, NodeRef) else val
                    for val in node_state.args
                ],
                kwargs={
                    key: NodeOutput(node_id=val.name()) if isinstance(val, NodeRef) else val
                    for key, val in node_state.kwargs.items()
                }
            )
            plan[node_ref.name()] = snapshot
            mapping[node_ref.name()] = node_ref
        return plan, mapping

    async def execute(self, target:'NodeRef')->dict['NodeRef', Any]:
        plan, mapping = await self.prepare([target])

        outputs: dict[str, Any] = {}
        for node_name, snapshot in plan.items():
            resolved_args = [
                outputs[val.node_id] if isinstance(val, NodeOutput) else val
                for val in snapshot.args
            ]
            resolved_kwargs = {
                key: outputs[val.node_id] if isinstance(val, NodeOutput) else val
                for key, val in snapshot.kwargs.items()
            }
            if snapshot.operator is None:
                raise ValueError(f"Operator for node {node_name} is not resolved.")
            output = snapshot.operator(*resolved_args, **resolved_kwargs)
            outputs[node_name] = output

        return {mapping[name]: value for name, value in outputs.items()}

if __name__ == "__main__":
    import asyncio
    from pygraphrt2.graph import Graph, NodeRef
    import asyncio
    import time

    graph = Graph()

    @graph.node()
    def some_sleep():
        print("Execute sleep for 1 second...")
        time.sleep(1)
        print("Awake now.")
        return "Hello"

    executor = MultiprocessExecutor(graph)
    
    async def main():
        outputs = await executor.execute(some_sleep)
        print(outputs)

    asyncio.run(main())


    