from ..models.abstract_dag_model import AbstractDAGModel, NodeName
from qtpy.QtCore import (
    QAbstractItemModel, 
    QModelIndex, 
    Signal, 
    Slot
)


class NodesListModel(QAbstractItemModel):
    def __init__(self, source_graph: AbstractDAGModel, parent=None):
        super().__init__(parent)
        self._source_graph:AbstractDAGModel|None = source_graph
        self._source_connections: list[tuple[Signal, Slot]] = []

    def setSourceGraph(self, source_graph: AbstractDAGModel):
        if self._source_graph:
            for signal, slot in self._source_connections:
                signal.disconnect(slot)
            self._source_connections.clear()
            self._source_graph = None

        if source_graph:
            self._source_connections = [
                (source_graph.modelAboutToBeReset, self.modelAboutToBeReset.emit),
                (source_graph.modelReset, self.modelReset.emit),
                (source_graph.nodesAboutToBeAdded, self._onNodesAboutToBeAdded),
                (source_graph.nodesAdded, self._onNodesAdded),
                (source_graph.nodesAboutToBeRemoved, self._onNodesAboutToBeRemoved),
                (source_graph.nodesRemoved, self._onNodesRemoved),
                (source_graph.nodesDataChanged, self._onNodesDataChanged)
            ]
            for signal, slot in self._source_connections:
                signal.connect(slot)

            self._source_graph = source_graph

    def mapFromSource(self, node_name:NodeName)->QModelIndex:
        if self._source_graph is None:
            return QModelIndex()
        all_nodes = list(self._source_graph.nodes()) # todo: this is a performance horror
        row = all_nodes.index(node_name)
        return self.createIndex(row, 0)

    def mapToSource(self, node_index: QModelIndex)->NodeName|None:
        if not node_index.isValid() or self._source_graph is None:
            return None
        all_nodes = list(self._source_graph.nodes()) # todo: this is a performance horror
        row = node_index.row()
        if 0 <= row < len(all_nodes):
            return all_nodes[row]
        return None

    def sourceGraph(self) -> AbstractDAGModel:
        return self._source_graph