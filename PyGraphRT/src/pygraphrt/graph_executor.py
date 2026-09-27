
from typing import TYPE_CHECKING, Any, Hashable, Any, Iterable, Mapping
from dataclasses import dataclass, field

from qtpy.QtCore import (
    QObject, 
    Signal
)

from myutils.profiler import Profiler


from .abstract_module_rt import AbstractOperator, OperatorRef


from .errors import (
    GraphExecutionError
)


from .graph_definition_rt import GraphStateRT, NodeRef



@dataclass(frozen=True)
class CacheEntry:
    fingerprint: Hashable
    value: Any


class MemoryCache:
    """Keep only the latest saved result for each node."""

    def __init__(self) -> None:
        self._entries: dict[NodeRef, CacheEntry] = {}

    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        entry = self._entries.get(node)
        if entry is not None and entry.fingerprint == fingerprint:
            return entry
        return None

    def hit(self, node: NodeRef, fingerprint: Hashable) -> bool:
        return self.lookup(node, fingerprint) is not None

    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        entry = CacheEntry(fingerprint, value)
        self._entries[node] = entry
        return entry

    def remove(self, node: NodeRef) -> None:
        self._entries.pop(node, None)

    def clear(self) -> None:
        self._entries.clear()


class HistoryMemoryCache:
    """Keep previous results per node and fingerprint until removed or cleared."""

    def __init__(self)->None:
        self._entries: dict[
            NodeRef, 
            dict[Hashable, CacheEntry]
        ] = {}

    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        return self._entries.get(node, {}).get(fingerprint)

    def hit(self, node: NodeRef, fingerprint: Hashable) -> bool:
        return fingerprint in self._entries.get(node, {})

    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        entry = CacheEntry(fingerprint, value)
        self._entries.setdefault(node, {})[fingerprint] = entry
        return entry

    def remove(self, node: NodeRef) -> None:
        self._entries.pop(node, None)

    def clear(self) -> None:
        self._entries.clear()


class DummyCache:
    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        return None

    def hit(self, node: NodeRef, fingerprint: Hashable) -> bool:
        return False

    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        return CacheEntry(fingerprint, value)

    def remove(self, node: NodeRef) -> None:
        pass

    def clear(self) -> None:
        pass



def freeze(value, active=None) -> tuple:
    """Preserve built-in types and values; identify opaque objects by identity.

    The cache retains NodeData so objects identified by id() stay alive.
    """
    # todo: consider moving freeze alongside with fingerprinting to the cache, 
    #       or? a utility class? 
    #       Figure out where fingerprinting and freeze belongs. 
    #       to the memory or to the graph, or a third party component.

    kind = type(value)
    if kind in (type(None), bool, int, str, bytes):
        return kind, value
    
    if kind is float:
        return kind, value.hex()  # Includes the sign of zero.
    
    if kind is complex:
        return kind, value.real.hex(), value.imag.hex()
    
    if kind is bytearray:
        return kind, bytes(value)

    if active is None:
        active = set()

    if kind in (tuple, list, dict, set, frozenset) and id(value) not in active:
        active.add(id(value))
        try:
            if kind is dict:
                items = tuple((freeze(k, active), freeze(v, active)) for k, v in value.items())
            else:
                items = tuple(freeze(item, active) for item in value)
            return kind, items
        finally:
            active.remove(id(value))
            
    return kind, id(value)

@dataclass
class NodeExecution:
    node: NodeRef
    result: Any
    error: Exception | None = None



class GraphExecutorRT(QObject):
    executed = Signal(dict) # dict[NodeRef, Any]
    def __init__(self, graph: GraphStateRT, cache: MemoryCache|HistoryMemoryCache|None=None):
        super().__init__()
        self._graph: GraphStateRT = graph
        self._profiler = Profiler()
        self._cache = cache if cache is not None else DummyCache()
        self._graph.nodes_removed.connect(self._on_nodes_removed)

    def _on_nodes_removed(self, removed_nodes: list[NodeRef]):    
        for node_ref in removed_nodes:
            del self._cache[node_ref]

    def _build_fingerprints(self, sorted_nodes: list[NodeRef]) -> dict[NodeRef, int]:
        fingerprints: dict[NodeRef, int] = {}
        for node_ref in sorted_nodes:
            node_data = self._graph._nodes[node_ref]
            args, kwargs = node_data.get_inputs()
            operator_ref = node_data.get_operator()

            assert isinstance(operator_ref, (OperatorRef, type(None))), f"operator_ref must be an instance of OperatorRef, got: {operator_ref}"
            if operator_ref is None:
                signature = ("no_operator",)
            else:
                signature = (
                    operator_ref.fingerprint(),
                    tuple(
                        (
                            "node", value, fingerprints[value]) if isinstance(value, NodeRef) else ("literal", freeze(value)
                        )
                        for value in args
                    ),
                    tuple(
                        (
                            key, 
                            ("node", value, fingerprints[value]) if isinstance(value, NodeRef) else ("literal", freeze(value))
                        ) 
                        for key, value in kwargs.items()
                    ),
                )
            # Dependencies already have hashes because this is topological order.
            fingerprints[node_ref] = hash(signature)
        return fingerprints
        
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
        fingerprints = self._build_fingerprints(sorted_ancestors)
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
                            raise GraphExecutionError(str(error), node_ref) from error
                    else:
                        raise GraphExecutionError("Node cannot be executed because its operator is missing.", node_ref)

                ancestors_output[node_ref] = value
                entry = self._cache.save(node_ref, fingerprints[node_ref], value)

        self.executed.emit({node_ref: ancestors_output[node_ref] for node_ref in ancestors})
        return ancestors_output[root]

