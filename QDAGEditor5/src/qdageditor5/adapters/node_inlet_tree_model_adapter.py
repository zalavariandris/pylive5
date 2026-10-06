from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from qtpy.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt, SignalInstance

from ..models.abstract_dag_model import (
    AbstractDAGModel,
    DirectionalLinkId,
    InletName,
    NodeName,
)


@dataclass(eq=False)
class _NodeShadow:
    node_name: NodeName
    inlets: list[_InletShadow] = field(default_factory=list)


@dataclass(eq=False)
class _InletShadow:
    parent_node: _NodeShadow
    inlet_name: InletName


class NodeInletTreeModelAdapter(QAbstractItemModel):
    """Project a graph as a tree of nodes and their inlets.

    Subclasses can add columns; only column zero can have children.
    """

    def __init__(
        self,
        source_graph: AbstractDAGModel | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_graph: AbstractDAGModel | None = None
        self._source_connections: list[
            tuple[SignalInstance, Callable[..., None]]
        ] = []
        self._nodes: list[_NodeShadow] = []
        self.setSourceGraph(source_graph)

    def sourceGraph(self) -> AbstractDAGModel | None:
        return self._source_graph

    def setSourceGraph(self, source_graph: AbstractDAGModel | None) -> None:
        if source_graph is self._source_graph:
            return

        for signal, slot in self._source_connections:
            signal.disconnect(slot)
        self._source_connections.clear()

        self._source_graph = source_graph

        if source_graph is not None:
            self._source_connections = [
                (source_graph.modelReset, self._on_model_reset),
                (source_graph.nodesAdded, self._on_nodes_added),
                (source_graph.nodesRemoved, self._on_nodes_removed),
                (source_graph.nodesDataChanged, self._on_nodes_data_changed),
                (source_graph.inletsChanged, self._on_inlets_changed),
                (source_graph.inletDataChanged, self._on_inlet_data_changed),
                (source_graph.linksAdded, self._on_links_changed),
                (source_graph.linksRemoved, self._on_links_changed),
                (source_graph.linksReset, self._on_links_reset),
            ]
            for signal, slot in self._source_connections:
                signal.connect(slot)

        self._on_model_reset()

    def _make_node_shadow(self, node_name: NodeName) -> _NodeShadow:
        assert self._source_graph is not None

        node = _NodeShadow(node_name)
        node.inlets = [
            _InletShadow(node, inlet_name)
            for inlet_name in self._source_graph.inlets(node_name)
        ]
        return node

    def _shadow(
        self, index: QModelIndex
    ) -> _NodeShadow | _InletShadow | None:
        if not index.isValid() or index.model() is not self:
            return None
        shadow = index.internalPointer()
        if isinstance(shadow, (_NodeShadow, _InletShadow)):
            return shadow
        return None

    # Source mapping

    def _inlet_source(
        self, index: QModelIndex
    ) -> tuple[NodeName, InletName] | None:
        """Give subclasses an inlet identity without exposing shadow storage."""
        shadow = self._shadow(index)
        if isinstance(shadow, _InletShadow):
            return shadow.parent_node.node_name, shadow.inlet_name
        return None

    def mapFromSource(self, node_name: NodeName) -> QModelIndex:
        for row, node in enumerate(self._nodes):
            if node.node_name == node_name:
                return self.createIndex(row, 0, node)
        return QModelIndex()

    def mapToSource(self, index: QModelIndex) -> NodeName | None:
        """Return the owning node for either a node or an inlet index."""
        shadow = self._shadow(index)
        if isinstance(shadow, _InletShadow):
            return shadow.parent_node.node_name
        if isinstance(shadow, _NodeShadow):
            return shadow.node_name
        return None

    # Tree structure

    def index(
        self,
        row: int,
        column: int = 0,
        parent: QModelIndex = QModelIndex(),
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            return self.createIndex(row, column, self._nodes[row])

        node = self._shadow(parent)
        if isinstance(node, _NodeShadow):
            return self.createIndex(row, column, node.inlets[row])

        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        shadow = self._shadow(index)
        if isinstance(shadow, _InletShadow):
            return self.mapFromSource(shadow.parent_node.node_name)
        return QModelIndex()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._nodes)
        if parent.column() != 0:
            return 0

        shadow = self._shadow(parent)
        if isinstance(shadow, _NodeShadow):
            return len(shadow.inlets)

        return 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Nodes are selectable; inlets are not, as the graph cannot select them."""
        if not index.isValid() or index.model() is not self:
            return Qt.ItemFlag.NoItemFlags

        flags = Qt.ItemFlag.ItemIsEnabled
        if not index.parent().isValid():
            flags |= Qt.ItemFlag.ItemIsSelectable
        return flags

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        graph = self._source_graph
        if graph is None or index.column() != 0:
            return None

        shadow = self._shadow(index)
        if isinstance(shadow, _NodeShadow):
            return graph.nodeData(shadow.node_name, role)

        if isinstance(shadow, _InletShadow):
            value = graph.inletData(
                shadow.parent_node.node_name,
                shadow.inlet_name,
                role,
            )
            if value is None and role == Qt.ItemDataRole.DisplayRole:
                return str(shadow.inlet_name)
            return value

        return None

    # Source notifications

    def _on_model_reset(self) -> None:
        nodes: list[_NodeShadow] = []
        if self._source_graph is not None:
            nodes = [
                self._make_node_shadow(node_name)
                for node_name in self._source_graph.nodes()
            ]

        self.beginResetModel()
        self._nodes = nodes
        self.endResetModel()

    def _on_nodes_added(self, node_names: Sequence[NodeName]) -> None:
        for node_name in node_names:
            if self.mapFromSource(node_name).isValid():
                continue

            node = self._make_node_shadow(node_name)
            row = len(self._nodes)
            self.beginInsertRows(QModelIndex(), row, row)
            self._nodes.append(node)
            self.endInsertRows()

    def _on_nodes_removed(self, node_names: Sequence[NodeName]) -> None:
        for node_name in node_names:
            index = self.mapFromSource(node_name)
            if not index.isValid():
                continue

            row = index.row()
            self.beginRemoveRows(QModelIndex(), row, row)
            self._nodes.pop(row)
            self.endRemoveRows()

    def _on_nodes_data_changed(
        self,
        node_names: Sequence[NodeName],
        _roles: Sequence[int],
    ) -> None:
        for node_name in node_names:
            index = self.mapFromSource(node_name)
            if index.isValid():
                self._emit_rows_changed(QModelIndex(), index.row(), index.row())

    def _on_inlets_changed(self, node_name: NodeName) -> None:
        graph = self._source_graph
        parent = self.mapFromSource(node_name)
        node = self._shadow(parent)
        if graph is None or not isinstance(node, _NodeShadow):
            return

        old_names = [inlet.inlet_name for inlet in node.inlets]
        new_names = list(graph.inlets(node_name))

        # Keep unchanged items at either end, preserving their indexes.
        first = 0
        old_end = len(old_names)
        new_end = len(new_names)
        while (
            first < min(old_end, new_end)
            and old_names[first] == new_names[first]
        ):
            first += 1

        while (
            old_end > first
            and new_end > first
            and old_names[old_end - 1] == new_names[new_end - 1]
        ):
            old_end -= 1
            new_end -= 1

        if first < old_end:
            self.beginRemoveRows(parent, first, old_end - 1)
            del node.inlets[first:old_end]
            self.endRemoveRows()

        if first < new_end:
            new_inlets = [
                _InletShadow(node, name)
                for name in new_names[first:new_end]
            ]
            self.beginInsertRows(parent, first, new_end - 1)
            node.inlets[first:first] = new_inlets
            self.endInsertRows()

        self._emit_inlets_changed(parent)

    def _emit_inlets_changed(self, parent: QModelIndex) -> None:
        count = self.rowCount(parent)
        if count:
            self._emit_rows_changed(parent, 0, count - 1)

    def _emit_rows_changed(
        self, parent: QModelIndex, first: int, last: int
    ) -> None:
        # Subclasses may derive values and roles in any column from source data.
        self.dataChanged.emit(
            self.index(first, 0, parent),
            self.index(last, self.columnCount(parent) - 1, parent),
            [],
        )

    def _on_inlet_data_changed(
        self,
        node_name: NodeName,
        inlet_names: Sequence[InletName],
        _roles: Sequence[int],
    ) -> None:
        parent = self.mapFromSource(node_name)
        node = self._shadow(parent)
        if not isinstance(node, _NodeShadow):
            return

        changed = set(inlet_names)
        for row, inlet in enumerate(node.inlets):
            if inlet.inlet_name in changed:
                self._emit_rows_changed(parent, row, row)

    def _on_links_changed(
        self, links: Sequence[DirectionalLinkId]
    ) -> None:
        targets = {
            (target_node, target_inlet)
            for _, _, target_node, target_inlet in links
        }
        for node_name, inlet_name in targets:
            self._on_inlet_data_changed(node_name, (inlet_name,), ())

    def _on_links_reset(self) -> None:
        for row in range(len(self._nodes)):
            self._emit_inlets_changed(self.index(row, 0))
