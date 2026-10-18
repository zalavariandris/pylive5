
from typing import Any, Hashable, Any, override
from dataclasses import dataclass, field

from qtpy.QtCore import (
    QObject, 
    Signal
)

from .abstract_operator import AbstractOperator
from .graph_definition_rt import GraphDefinitionRT, NodeRef


@dataclass(frozen=True)
class CacheEntry:
    fingerprint: Hashable
    value: Any


class DummyCache:
    def __init__(self) -> None:
        pass
    # def __init__(self, graph: GraphDefinitionRT) -> None:
    #     self._graph = graph
    #     self._graph.nodes_removed.connect(self._on_nodes_removed)

    def _on_nodes_removed(self, removed_nodes: list[NodeRef]):    
        for node_ref in removed_nodes:
            del self._cache[node_ref]

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

    def _build_fingerprints(self, sorted_nodes: list[NodeRef]) -> dict[NodeRef, int]:
        fingerprints: dict[NodeRef, int] = {}
        for node_ref in sorted_nodes:
            args, kwargs = node_ref.get_inputs()
            operator = node_ref.get_operator()

            assert isinstance(operator, (AbstractOperator, type(None))), f"operator_ref must be an instance of AbstractOperator or None, got: {operator}"
            if operator is None:
                signature = ("no_operator",)
            else:
                signature = (
                    operator.fingerprint(),
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


class MemoryCache(DummyCache):
    """Keep only the latest saved result for each node."""

    def __init__(self) -> None:
        super().__init__()
        self._entries: dict[NodeRef, CacheEntry] = {}

    @override
    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        entry = self._entries.get(node)
        if entry is not None and entry.fingerprint == fingerprint:
            return entry
        return None

    @override
    def hit(self, node: NodeRef, fingerprint: Hashable) -> bool:
        return self.lookup(node, fingerprint) is not None

    @override
    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        entry = CacheEntry(fingerprint, value)
        self._entries[node] = entry
        return entry

    @override
    def remove(self, node: NodeRef) -> None:
        self._entries.pop(node, None)

    @override
    def clear(self) -> None:
        self._entries.clear()


class HistoryMemoryCache(DummyCache):
    """Keep previous results per node and fingerprint until removed or cleared."""

    def __init__(self)->None:
        super().__init__()
        self._entries: dict[
            NodeRef, 
            dict[Hashable, CacheEntry]
        ] = {}

    @override
    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        return self._entries.get(node, {}).get(fingerprint)

    @override
    def hit(self, node: NodeRef, fingerprint: Hashable) -> bool:
        return fingerprint in self._entries.get(node, {})

    @override
    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        entry = CacheEntry(fingerprint, value)
        self._entries.setdefault(node, {})[fingerprint] = entry
        return entry

    @override
    def remove(self, node: NodeRef) -> None:
        self._entries.pop(node, None)

    @override
    def clear(self) -> None:
        self._entries.clear()


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
