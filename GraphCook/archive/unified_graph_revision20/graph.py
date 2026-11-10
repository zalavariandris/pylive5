"""Generic observable graph. No knowledge of operators or execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Generic, Hashable, Mapping, Protocol, TypeVar

NodeT = TypeVar("NodeT", bound=Hashable)
KeyT = TypeVar("KeyT", bound=Hashable)
ValueT = TypeVar("ValueT")


@dataclass(eq=False, frozen=True)
class Node:
    """Convenient identity-based node. Any hashable object may also be a node."""
    label: str = ""


@dataclass(frozen=True)
class Link(Generic[NodeT]):
    source: NodeT
    target: NodeT
    input: str


@dataclass(frozen=True)
class SetChanges(Generic[ValueT]):
    """Membership changes in an unordered collection."""
    added: tuple[ValueT, ...] = ()
    removed: tuple[ValueT, ...] = ()


@dataclass(frozen=True)
class ValueChange(Generic[ValueT]):
    old: ValueT
    new: ValueT


@dataclass(frozen=True)
class MappingChanges(Generic[KeyT, ValueT]):
    """Key additions/removals and value replacements in a mapping."""
    added: Mapping[KeyT, ValueT] = field(default_factory=dict)
    removed: Mapping[KeyT, ValueT] = field(default_factory=dict)
    changed: Mapping[KeyT, ValueChange[ValueT]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Make snapshots of the delta mappings, not just their dataclass fields.
        for name in ("added", "removed", "changed"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True)
class GraphChange(Generic[NodeT]):
    """Independent changes to graph membership and per-node attributes.

    Adding/removing a node is reported in `nodes`; its initial/final attribute
    dictionary is not repeated in `attributes`.
    """
    nodes: SetChanges[NodeT] = field(default_factory=SetChanges)
    links: SetChanges[Link[NodeT]] = field(default_factory=SetChanges)
    attributes: Mapping[NodeT, MappingChanges[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))


class GraphProtocol(Protocol[NodeT]):
    def nodes(self) -> tuple[NodeT, ...]: ...
    def links(self) -> tuple[Link[NodeT], ...]: ...
    def attributes(self, node: NodeT) -> Mapping[str, object]: ...
    def in_links(self, node: NodeT) -> tuple[Link[NodeT], ...]: ...
    def out_links(self, node: NodeT) -> tuple[Link[NodeT], ...]: ...


class Graph(Generic[NodeT]):
    """Stores node attributes and one incoming link per (target, input)."""

    def __init__(self) -> None:
        self._attributes: dict[NodeT, dict[str, object]] = {}
        self._inputs: dict[tuple[NodeT, str], NodeT] = {}

    def nodes(self) -> tuple[NodeT, ...]:
        return tuple(self._attributes)

    def links(self) -> tuple[Link[NodeT], ...]:
        return tuple(Link(source, target, name)
                     for (target, name), source in self._inputs.items())

    def attributes(self, node: NodeT) -> Mapping[str, object]:
        return MappingProxyType(self._attributes[node])

    def in_links(self, node: NodeT) -> tuple[Link[NodeT], ...]:
        return tuple(Link(source, target, name)
                     for (target, name), source in self._inputs.items()
                     if target == node)

    def out_links(self, node: NodeT) -> tuple[Link[NodeT], ...]:
        return tuple(Link(source, target, name)
                     for (target, name), source in self._inputs.items()
                     if source == node)

    def add(self, node: NodeT, **attributes: object) -> None:
        if node in self._attributes:
            raise ValueError(f"Node already exists: {node!r}")
        self._attributes[node] = dict(attributes)
        self._notify(GraphChange(nodes=SetChanges(added=(node,))))

    def set(self, node: NodeT, **attributes: object) -> None:
        current = self._attributes[node]
        if not attributes:
            return
        added: dict[str, object] = {}
        changed: dict[str, ValueChange[object]] = {}
        for name, value in attributes.items():
            if name in current:
                # Explicit writes are observable even if old == new.
                changed[name] = ValueChange(current[name], value)
            else:
                added[name] = value
        current.update(attributes)
        self._notify(GraphChange(attributes={node: MappingChanges(
            added=added, changed=changed,
        )}))

    def unset(self, node: NodeT, name: str) -> None:
        old = self._attributes[node].pop(name)
        self._notify(GraphChange(attributes={node: MappingChanges(removed={name: old})}))

    def remove(self, node: NodeT) -> None:
        if node not in self._attributes:
            raise KeyError(node)
        removed = tuple(link for link in self.links()
                        if link.source == node or link.target == node)
        for link in removed:
            del self._inputs[(link.target, link.input)]
        del self._attributes[node]
        self._notify(GraphChange(nodes=SetChanges(removed=(node,)),
                               links=SetChanges(removed=removed)))

    def add_link(self, source: NodeT, target: NodeT, input: str) -> None:
        if source not in self._attributes or target not in self._attributes:
            raise KeyError("Both link endpoints must exist")
        key = (target, input)
        if key in self._inputs:
            old = self._inputs[key]
            if old == source:
                return
            removed = (Link(old, target, input),)
        else:
            removed = ()
        self._inputs[key] = source
        self._notify(GraphChange(links=SetChanges(
            added=(Link(source, target, input),), removed=removed)))

    def remove_link(self, target: NodeT, input: str) -> None:
        source = self._inputs.pop((target, input))
        self._notify(GraphChange(links=SetChanges(
            removed=(Link(source, target, input),))))

    def snapshot(self) -> Graph[NodeT]:
        """Copy the graph tables; attribute values and node objects remain shared."""
        copy = Graph[NodeT]()
        copy._attributes = {node: attrs.copy() for node, attrs in self._attributes.items()}
        copy._inputs = self._inputs.copy()
        return copy

    def _notify(self, change: GraphChange[NodeT]) -> None:
        pass


class ObservableGraph(Graph[NodeT]):
    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[Callable[[GraphChange[NodeT]], None]] = []

    def listen(self, callback: Callable[[GraphChange[NodeT]], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        def unsubscribe() -> None:
            self._listeners.remove(callback)
        return unsubscribe

    def _notify(self, change: GraphChange[NodeT]) -> None:
        for callback in tuple(self._listeners):
            callback(change)
