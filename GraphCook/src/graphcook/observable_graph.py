
from collections.abc import Callable, Hashable, Mapping
from typing import TypedDict
from .core.graph import Graph, NodeKeyT, NodeValueT, Link


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


class ObservableGraph(Graph[NodeKeyT, NodeValueT]):
    """Observable graph whose events describe completed mutations.
    Node-removal events include all incident links removed with the node.
    """
    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[Callable[[GraphChange[NodeKeyT]], None]] = []

    def listen(self, callback: Callable[[GraphChange[NodeKeyT]], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        def unsubscribe() -> None:
            self._listeners.remove(callback)
        return unsubscribe

    def _notify(self, change: GraphChange[NodeKeyT]) -> None:
        for callback in tuple(self._listeners):
            callback(change)

    def add_node(self, node: NodeKeyT, **attributes: object) -> None:
        super().add_node(node, **attributes)
        self._notify(GraphChange(
            nodes=MappingChanges(kind="map", added={node: dict(attributes)}),
        ))

    def remove_node(self, node: NodeKeyT) -> None:
        attributes = dict(self.attributes(node))
        removed_links = set(self.in_links(node)).union(self.out_links(node))
        super().remove_node(node)

        self._notify(GraphChange(
            nodes=MappingChanges(kind="map", removed={node: attributes}),
            links=SetChanges(kind="set", removed=removed_links)
        ))

    def update_attributes(self, node: NodeKeyT, /, **attributes: object) -> None:
        """Merge attributes and emit one notification after the mutation."""
        old = self.attributes(node)

        if not attributes:
            return

        added = {key: value for key, value in attributes.items() if key not in old}
        updated = {
            key: ValueChange(kind="value", old=old[key], new=value)
            for key, value in attributes.items()
            if key in old
        }
        super().update_attributes(node, **attributes)

        self._notify(GraphChange(
            nodes=MappingChanges(
                kind="map",
                updated={node: MappingChanges(kind="map", added=added, updated=updated)},
            ),
        ))

    def unset_attribute(self, node: NodeKeyT, name: str) -> None:
        attributes = self.attributes(node)
        if name not in attributes:
            return # Attribute not present, nothing to unset #todo: consider raising an error
        old = attributes[name]

        super().unset_attribute(node, name)

        self._notify(GraphChange(
            nodes=MappingChanges(
                kind="map",
                updated={node: MappingChanges(kind="map", removed={name: old})},
            ),
        ))

    def add_link(
        self, source: NodeKeyT, target: NodeKeyT, inlet: str
    ) -> None:
        super().add_link(source, target, inlet)

        self._notify(GraphChange(
            links=SetChanges(
                kind="set",
                added=set([Link(source, target, inlet)])
            )
        ))

    def remove_link(
        self, source: NodeKeyT, target: NodeKeyT, inlet: str
    ) -> None:
        super().remove_link(source, target, inlet)

        self._notify(GraphChange(
            links=SetChanges(
                kind="set",
                removed=set([Link(source, target, inlet)])
            )
        ))
