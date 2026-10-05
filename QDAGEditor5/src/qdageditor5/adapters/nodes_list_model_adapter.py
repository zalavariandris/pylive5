from typing import Callable, override

from ..models.abstract_dag_model import AbstractDAGModel, NodeName
from qtpy.QtCore import (
    QAbstractItemModel,
    QAbstractListModel, 
    QModelIndex,
    Qt, 
    Signal, 
    Slot
)

from myutils.bilist import BiList
    

class NodesListModelAdapter(QAbstractListModel):
    def __init__(self, source_graph: AbstractDAGModel, parent=None):
        super().__init__(parent)
        self._source_graph:AbstractDAGModel|None = None
        self._source_connections: list[tuple[Signal, Callable]] = []

        self._nodelist: BiList[NodeName] = BiList()

        self.setSourceGraph(source_graph)

    def setSourceGraph(self, source_graph: AbstractDAGModel|None):
        if self._source_graph:
            for signal, slot in self._source_connections:
                signal.disconnect(slot)
            self._source_connections.clear()
            self._source_graph = None

        if source_graph:
            self._source_connections = [
                (source_graph.modelReset, self._on_model_reset),
                # (source_graph.nodesAboutToBeAdded, self._onNodesAboutToBeAdded),
                (source_graph.nodesAdded, self._on_nodes_added),
                # (source_graph.nodesAboutToBeRemoved, self._onNodesAboutToBeRemoved),
                (source_graph.nodesRemoved, self._on_nodes_removed),
                # (source_graph.nodesDataChanged, self._onNodesDataChanged)
            ]
            for signal, slot in self._source_connections:
                signal.connect(slot)

            self._source_graph = source_graph


        self._on_model_reset()

    def _on_model_reset(self):
        self.beginResetModel()
        self._nodelist.clear()
        if self._source_graph is not None:
            for node_name in self._source_graph.nodes():
                self._nodelist.append(node_name)
        self.endResetModel()

    def _on_nodes_added(self, node_names: list[NodeName]):
        if not node_names:
            return
        
        first = len(self._nodelist)
        last = first + len(node_names) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        for node_name in node_names:
            self._nodelist.append(node_name)
        self.endInsertRows()

    def _on_nodes_removed(self, node_names: list[NodeName]):
        for node_name in node_names:
            #todo: find contiguous idx ranges and 
            # emit a single beginRemoveRows/endRemoveRows for each range
            if node_name in self._nodelist:
                idx = self._nodelist.inverse[node_name]
                self.beginRemoveRows(QModelIndex(), idx, idx)
                self._nodelist.pop(idx)
                self.endRemoveRows()

    def mapFromSource(self, node_name: NodeName) -> QModelIndex:
        if self._source_graph is None:
            return QModelIndex()

        row = self._nodelist.inverse.get(node_name)
        if row is None:
            return QModelIndex()

        return self.createIndex(row, 0)

    def mapToSource(self, node_index: QModelIndex) -> NodeName | None:
        if (
            not node_index.isValid()
            or node_index.model() is not self
            or not 0 <= node_index.row() < len(self._nodelist)
        ):
            return None

        return self._nodelist[node_index.row()]

    def sourceGraph(self) -> AbstractDAGModel|None:
        return self._source_graph

    @override
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if (
            self._source_graph is None
            or not index.isValid()
            or index.model() is not self
            or not 0 <= index.row() < len(self._nodelist)
        ):
            return None

        key = self._nodelist[index.row()]
        return self._source_graph.nodeData(key, role)

    @override
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._nodelist)
    