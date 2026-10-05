from collections.abc import Callable

from qtpy.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    SignalInstance,
)

from .nodes_list_model_adapter import NodesListModelAdapter
from ..models.abstract_dag_model import NodeName
from ..models.graph_selection_model import GraphSelectionModel


class NodesListSelectionModelAdapter(QItemSelectionModel):
    """Synchronize a node list's selection and current item with a graph selection."""

    def __init__(self, model: NodesListModelAdapter, parent: QObject | None = None) -> None:
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
            for node in self._source_selection.selectedNodes():
                index = self._model.mapFromSource(node)
                if index.isValid():
                    selection.select(index, index)

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
        if self._syncing or self._source_selection is None:
            return

        self._syncing = True
        try:
            self._source_selection.setCurrentNode(self._model.mapToSource(current))
        finally:
            self._syncing = False
