
from typing import  Generic, Mapping, Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from dataclasses import dataclass, field
from .core.graph import Graph, NodeT, Link


from .core.changes import (
    SetChanges,
    ValueChange,
    MappingChanges
)

@dataclass(frozen=True)
class GraphChange(Generic[NodeT]):
    """
    Independent changes to graph membership and per-node attributes.
    """
    nodes: SetChanges[NodeT] = field(default_factory=lambda: SetChanges[NodeT]())
    links: SetChanges[tuple[NodeT, NodeT, str]] = field(default_factory=lambda: SetChanges[NodeT]())
    attributes: Mapping[NodeT, MappingChanges[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

        
class ObservableGraph(Graph[NodeT]):
    """Observable graph whose events describe completed mutations.
    Node-removal events include all incident links removed with the node.
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

    def add_node(self, node: NodeT, **attributes: object) -> None:
        super().add_node(node, **attributes)
        self._notify(GraphChange(
            nodes=SetChanges(added=set([node]))
        ))

    def remove_node(self, node: NodeT) -> None:
        removed_links = set(self.in_links(node)).union(self.out_links(node))
        super().remove_node(node)

        self._notify(GraphChange(
            nodes=SetChanges(removed=set([node])),
            links=SetChanges(removed=removed_links)
        ))

    def set(self, node: NodeT, **attributes: object) -> None:
        old = self.attributes(node)
        updates = attributes

        if not updates:
            return

        added = {
            key: value
            for key, value in updates.items()
            if key not in old
        }

        changed = {
            key: ValueChange(old[key], value)
            for key, value in updates.items()
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
            links=SetChanges(
                added=set([Link(source, target, inlet)])
            )
        ))

    def remove_link(
        self, source: NodeT, target: NodeT, inlet: str
    ) -> None:
        super().remove_link(source, target, inlet)

        self._notify(GraphChange(
            links=SetChanges(
                removed=set([Link(source, target, inlet)])
            )
        ))
        