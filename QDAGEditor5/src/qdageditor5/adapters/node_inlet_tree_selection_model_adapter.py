from collections.abc import Callable

from qtpy.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    SignalInstance,
)

from .node_inlet_tree_model_adapter import NodeInletTreeModelAdapter
from ..models.abstract_dag_model import NodeName
from ..models.graph_selection_model import GraphSelectionModel


def _is_node_index(index: QModelIndex) -> bool:
    return index.isValid() and not index.parent().isValid()


class NodeInletTreeSelectionModelAdapter(QItemSelectionModel):
    """Synchronize the node rows of a node/inlet tree with a graph selection.

    Inlets are never selected and never forwarded to the graph.
    """

    def __init__(
        self, model: NodeInletTreeModelAdapter, parent: QObject | None = None
    ) -> None:
        super().__init__(model, parent)
        self._model = model
        self._source_selection: GraphSelectionModel | None = None
        self._source_selection_connections: list[tuple[SignalInstance, Callable[..., None]]] = []
        self._syncing = False

        self.selectionChanged.connect(self._sync_to_source_selection)
        self.currentChanged.connect(self._sync_to_source_current)
        model.modelReset.connect(self._sync_from_source)
        model.rowsInserted.connect(self._sync_from_source)

    def sourceSelection(self) -> GraphSelectionModel | None:
        return self._source_selection

    def setSourceSelection(self, source_selection: GraphSelectionModel | None) -> None:
        """Adopt the source's state, or clear local state when detached."""
        if source_selection is self._source_selection:
            return

        for signal, slot in self._source_selection_connections:
            signal.disconnect(slot)
        self._source_selection_connections.clear()

        self._source_selection = source_selection
        if source_selection is not None:
            self._source_selection_connections = [
                (source_selection.nodesSelectionChanged, self._sync_from_source_selection),
                (source_selection.currentNodeChanged, self._sync_from_source_current),
                (source_selection.modelChanged, self._sync_from_source),
            ]
            for signal, slot in self._source_selection_connections:
                signal.connect(slot)

        self._sync_from_source_selection()
        self._sync_from_source_current()

    def select(
        self,
        selection: QItemSelection | QModelIndex,
        command: QItemSelectionModel.SelectionFlag,
    ) -> None:
        # A click on an inlet would otherwise clear the selected nodes.
        indexes = selection.indexes() if isinstance(selection, QItemSelection) else [selection]
        if indexes and not any(_is_node_index(index) for index in indexes):
            return
        super().select(selection, command)

    def _sync_from_source(self, *args: object) -> None:
        if self._source_selection is None:
            return
        self._sync_from_source_selection()
        self._sync_from_source_current()

    def _sync_from_source_selection(self, *args: object) -> None:
        if self._syncing:
            return

        selection = QItemSelection()
        if self._source_selection is not None:
            last_column = self._model.columnCount() - 1
            for node in self._source_selection.selectedNodes():
                index = self._model.mapFromSource(node)
                if index.isValid():
                    selection.select(index, index.siblingAtColumn(last_column))

        self._syncing = True
        try:
            self.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        finally:
            self._syncing = False

    def _sync_from_source_current(self, *args: object) -> None:
        if self._syncing:
            return

        index = QModelIndex()
        if self._source_selection is not None:
            node = self._source_selection.currentNode()
            if node is not None:
                index = self._model.mapFromSource(node)

        self._syncing = True
        try:
            self.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        finally:
            self._syncing = False

    def _sync_to_source_selection(
        self, selected: QItemSelection, deselected: QItemSelection,
    ) -> None:
        if self._syncing or self._source_selection is None:
            return

        nodes: set[NodeName] = set()
        for index in self.selectedIndexes():
            if not _is_node_index(index):
                continue
            node = self._model.mapToSource(index)
            if node is not None:
                nodes.add(node)

        # Suppress the echo so Qt retains its interactive selection layer.
        self._syncing = True
        try:
            self._source_selection.selectNodes(nodes)
        finally:
            self._syncing = False

    def _sync_to_source_current(self, current: QModelIndex, previous: QModelIndex) -> None:
        # An inlet may be current for editing, but must not change the graph's current node.
        if self._syncing or self._source_selection is None or not _is_node_index(current):
            return

        self._syncing = True
        try:
            self._source_selection.setCurrentNode(self._model.mapToSource(current))
        finally:
            self._syncing = False
