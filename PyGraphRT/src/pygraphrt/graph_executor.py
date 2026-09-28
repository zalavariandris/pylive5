
from typing import TYPE_CHECKING, Any, Hashable, Any, Iterable, Mapping
from dataclasses import dataclass, field

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
    node: NodeRef

@dataclass(frozen=True)
class ExecutionRunning:
    node: NodeRef

@dataclass(frozen=True)
class ExecutionSuccess:
    node: NodeRef
    result: Any

@dataclass(frozen=True)
class ExecutionFailure:
    node: NodeRef
    reason: str|Exception

NodeExecution = (
    ExecutionPending
    | ExecutionRunning
    | ExecutionSuccess
    | ExecutionFailure
)

@dataclass(frozen=True)
class GraphExecution:
    nodes: dict[NodeRef, NodeExecution]


class GraphExecutorRT(QObject):
    executed = Signal(dict) # dict[NodeRef, NodeExecution]
    
    def __init__(self, graph: GraphDefinitionRT, cache: MemoryCache|HistoryMemoryCache|None=None):
        super().__init__()
        self._graph: GraphDefinitionRT = graph
        self._profiler = Profiler()
        self._cache = cache if cache is not None else DummyCache(self._graph)
        
    def execute(self, root:NodeRef, profile: bool = True)->NodeExecution:
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
        ancestors_output: dict[NodeRef, Any] = {} # store node output temporary
        for node_ref in sorted_ancestors:
            node_data = self._graph._nodes[node_ref]
            
            if entry:=self._cache.lookup(node_ref, fingerprints[node_ref]):
                ancestors_output[node_ref] = entry.value
            else:
                args, kwargs = node_data.get_inputs()
                

                resolved_args = [
                    ancestors_output[value] if isinstance(value, NodeRef) else value
                    for value in args
                ]

                resolved_kwargs = {
                    key: ancestors_output[value] if isinstance(value, NodeRef) else value
                    for key, value in kwargs.items()
                }

                with self._profiler.profile(node_ref):
                    if operator := node_data.get_operator():
                        try:
                            value = operator(*resolved_args, **resolved_kwargs)
                        except Exception as error:
                            return ExecutionFailure(node_ref, reason=error)
                            raise GraphExecutionError(str(error), node_ref) from error
                    else:
                        return ExecutionFailure(node_ref, reason="Node cannot be executed because its operator is missing.")

                ancestors_output[node_ref] = value
                entry = self._cache.save(node_ref, fingerprints[node_ref], value)

        self.executed.emit({
            node_ref: ancestors_output[node_ref] 
            for node_ref in ancestors
        })
        return ExecutionSuccess(root, ancestors_output[root]) 

