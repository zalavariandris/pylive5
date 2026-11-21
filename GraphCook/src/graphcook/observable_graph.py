
from collections.abc import Callable, Hashable, Mapping
from typing import TypedDict
from .core.graph import Graph, NodeT, Link


from .core.changes import (
    SetChanges,
    ValueChange,
    MappingChanges,
    Change,
)

type AttributeChanges = MappingChanges[str, object, Change]


class GraphChange[N: Hashable](TypedDict, total=False):
    nodes: MappingChanges[N, Mapping[Hashable, object], AttributeChanges]
    links: SetChanges[Link[N]]

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
            nodes=MappingChanges(kind="map", added={node: dict(attributes)}),
        ))

    def remove_node(self, node: NodeT) -> None:
        attributes = dict(self.attributes(node))
        removed_links = set(self.in_links(node)).union(self.out_links(node))
        super().remove_node(node)

        self._notify(GraphChange(
            nodes=MappingChanges(kind="map", removed={node: attributes}),
            links=SetChanges(kind="set", removed=removed_links)
        ))

    def set(self, node: NodeT, **attributes: object) -> None:
        old = self.attributes(node)

        if not attributes:
            return

        added = {key: value for key, value in attributes.items() if key not in old}
        updated = {
            key: ValueChange(kind="value", old=old[key], new=value)
            for key, value in attributes.items()
            if key in old
        }
        super().set(node, **attributes)

        self._notify(GraphChange(
            nodes=MappingChanges(
                kind="map",
                updated={node: MappingChanges(kind="map", added=added, updated=updated)},
            ),
        ))

    def unset(self, node: NodeT, name: str) -> None:
        old = self.attributes(node)[name]

        super().unset(node, name)

        self._notify(GraphChange(
            nodes=MappingChanges(
                kind="map",
                updated={node: MappingChanges(kind="map", removed={name: old})},
            ),
        ))

    def add_link(
        self, source: NodeT, target: NodeT, inlet: str
    ) -> None:
        super().add_link(source, target, inlet)

        self._notify(GraphChange(
            links=SetChanges(
                kind="set",
                added=set([Link(source, target, inlet)])
            )
        ))

    def remove_link(
        self, source: NodeT, target: NodeT, inlet: str
    ) -> None:
        super().remove_link(source, target, inlet)

        self._notify(GraphChange(
            links=SetChanges(
                kind="set",
                removed=set([Link(source, target, inlet)])
            )
        ))
