
from typing import Any
from dataclasses import dataclass

from qtpy.QtCore import (
    QObject, 
    Signal
)

from myutils.profiler import Profiler


from .errors import (
    GraphExecutionError
)

from .graph_definition_rt import (
    GraphDefinitionRT, 
    NodeRef
)

from .graph_cache import (
    MemoryCache, 
    HistoryMemoryCache, 
    DummyCache
)

# @dataclass
# class NodeExecution:
#     node: NodeRef
#     result: Any
#     error: Exception | str | None = None

# from dataclasses import dataclass

@dataclass(frozen=True)
class ExecutionPending:
    """Represents node execution state that is pending."""
    node: NodeRef

@dataclass(frozen=True)
class ExecutionRunning:
    """Represents node execution state that is currently running."""
    node: NodeRef

@dataclass(frozen=True)
class ExecutionSuccess:
    """Represents node execution state that has succeeded."""
    node: NodeRef
    result: Any
    duration_seconds: float | None = None

@dataclass(frozen=True)
class ExecutionFailure:
    """Represents node execution state that has failed
    due to an error."""
    node: NodeRef
    reason: str|Exception
    duration_seconds: float | None = None

@dataclass(frozen=True)
class ExecutionBlocked:
    """Represents node execution state that is blocked
    due to unavailable dependencies."""
    node: NodeRef
    blocked_by: frozenset[NodeRef]

NodeExecution = (
    ExecutionPending
    | ExecutionRunning
    | ExecutionSuccess
    | ExecutionFailure
    | ExecutionBlocked
)

# @dataclass(frozen=True)
# class GraphExecution:
#     nodes: dict[NodeRef, NodeExecution]


class GraphExecutorRT(QObject):
    executed = Signal(dict) # dict[NodeRef, NodeExecution]
    
    def __init__(self, graph: GraphDefinitionRT, cache: MemoryCache|HistoryMemoryCache|None=None):
        super().__init__()
        self._graph: GraphDefinitionRT = graph
        self._profiler = Profiler()
        self._cache = cache if cache is not None else DummyCache()
        
    def execute(self, root:NodeRef, profile: bool = True)->NodeExecution:
        print(f"Executing node: {root}")
        """Evaluate pure operators with immutable inputs and operator data.

        Upstream signatures are reduced to Python hashes, so dependency hash
        collisions are possible. Cache lookups compare full local signatures.
        """
        assert isinstance(root, NodeRef), f"root must be an instance of NodeRef, got: {root}"
        if root is None:
            raise ValueError("No output node specified.")

        if root not in self._graph._nodes:
            raise ValueError(f"Node {root} does not exist in the engine.")
        
        if profile:
            self._profiler.clear()

        ancestors = self._graph.ancestors(root)
        sorted_ancestors = self._graph.topological_sort(ancestors)

        # execute nodes
        fingerprints = self._cache._build_fingerprints(sorted_ancestors)
        outputs: dict[NodeRef, Any] = {} # store node output temporary
        exceptions: dict[NodeRef, Exception] = {} # store node execution status temporary
        blocked: dict[NodeRef, ExecutionBlocked] = {} # store blocked nodes temporary
        for node_ref in sorted_ancestors:
            node_data = self._graph._nodes[node_ref]
            args, kwargs = node_data.get_inputs()

            unavailable = frozenset(
                value
                for value in (*args, *kwargs.values())
                if isinstance(value, NodeRef) and value not in outputs
            )

            if unavailable:
                blocked[node_ref] = ExecutionBlocked(
                    node=node_ref,
                    blocked_by=unavailable,
                )
                continue

            if entry:=self._cache.lookup(node_ref, fingerprints[node_ref]):
                outputs[node_ref] = entry.value
            else:
                resolved_args = [
                    outputs[value] if isinstance(value, NodeRef) else value
                    for value in args
                ]

                resolved_kwargs = {
                    key: outputs[value] if isinstance(value, NodeRef) else value
                    for key, value in kwargs.items()
                }

                try:
                    operator = node_ref.get_operator()
                    with self._profiler.profile(node_ref):
                        output = operator(*resolved_args, **resolved_kwargs)
                    
                except Exception as error:
                    exceptions[node_ref] = error
                else:
                    outputs[node_ref] = output
                    entry = self._cache.save(node_ref, fingerprints[node_ref], outputs.get(node_ref))

        # merge execution results
        executions: dict[NodeRef, NodeExecution] = dict()
        executions.update({
            node_ref: ExecutionSuccess(node_ref, output) 
            for node_ref, output in outputs.items()
        })
        executions.update({
            node_ref: ExecutionFailure(node_ref, error) 
            for node_ref, error in exceptions.items()
        })
        executions.update(blocked)

        self.executed.emit(executions)
        return executions[root]

