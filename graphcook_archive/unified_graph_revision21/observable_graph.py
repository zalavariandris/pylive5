from contextlib import contextmanager
from typing import  Generic, TypeVar, Hashable, Mapping, Callable
from types import MappingProxyType
from dataclasses import dataclass, field
from .graph import Graph, NodeT, Link

KeyT = TypeVar("KeyT", bound=Hashable)
ValueT = TypeVar("ValueT")


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

        
class ObservableGraph(Graph[NodeT]):
    """
    add observable graph functionality to Graph, notifying listeners of changes
    note: a node removal does not trigger connected link removal signals.
    """
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

    def add(self, node: NodeT, **attributes: object) -> None:
        super().add(node, **attributes)
        self._notify(GraphChange(
            nodes=SetChanges(added=(node,))
        ))

    def remove(self, node: NodeT) -> None:
        super().remove(node)

        self._notify(GraphChange(
            nodes=SetChanges(removed=(node,))
        ))

    def set(self, node: NodeT, **attributes: object) -> None:
        old = self.attributes(node)

        if not attributes:
            return

        added = {
            key: value
            for key, value in attributes.items()
            if key not in old
        }

        changed = {
            key: ValueChange(old[key], value)
            for key, value in attributes.items()
            if key in old
        }

        super().set(node, **attributes)

        self._notify(GraphChange(
            attributes={
                node: MappingChanges(
                    added=added,
                    changed=changed,
                )
            }
        ))

    def unset(self, node: NodeT, name: str) -> None:
        old = self.attributes(node)[name]

        super().unset(node, name)

        self._notify(GraphChange(
            attributes={
                node: MappingChanges(
                    removed={
                        name: old
                    }
                )
            }
        ))

    def add_link(
        self, source: NodeT, target: NodeT, inlet: str
    ) -> None:
        super().add_link(source, target, inlet)

        self._notify(GraphChange(
            links=SetChanges(added=(Link(source, target, inlet),))
        ))

    def remove_link(
        self, source: NodeT, target: NodeT, inlet: str
    ) -> None:
        super().remove_link(source, target, inlet)

        self._notify(GraphChange(
            links=SetChanges(removed=(Link(source, target, inlet),))
        ))
        
