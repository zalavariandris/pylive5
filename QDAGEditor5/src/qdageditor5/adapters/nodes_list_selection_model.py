from qtpy.QtCore import QModelIndex
from qtpy.QtGui import QStandardItemModel
from qtpy.QtWidgets import QItemSelectionModel
from .nodes_list_model import NodesListModel

from ..models.abstract_dag_model import AbstractDAGModel, NodeName
from ..models.graph_selection_model import GraphSelectionModel


class NodesListSelectionModelAdapter(QItemSelectionModel):
    def __init__(self, model: NodesListModel, parent=None):
        super().__init__(model, parent)
        self._model = model
        self._source_selection: GraphSelectionModel|None = None
        self._source_selection_connections = []

    def setSourceSelection(self, source_selection: GraphSelectionModel):
        ...



