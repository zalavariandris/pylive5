from typing import Callable

from qtpy.QtWidgets import (
    QVBoxLayout, 
    QWidget
)
from qtpy.QtCore import (
    Qt, 
    Signal, 
    SignalInstance,
)

from myqtx.widgets import DisplayWidget

from ..models.abstract_dag_model import AbstractDAGModel, NodeName, InletName
from ..models.graph_selection_model import GraphSelectionModel


class NodeDataViewer(QWidget):
    def __init__(self, parent=None)->None:
        super().__init__(parent)
        self.setWindowTitle("Node Output Viewer")
        self.setMinimumSize(400, 300)

        self._model: AbstractDAGModel | None = None
        self._selection_model: GraphSelectionModel | None = None
        self._model_connections: list[tuple[SignalInstance, Callable]] = []
        self._selection_connections: list[tuple[SignalInstance, Callable]] = []

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        self._display_widget = DisplayWidget()
        main_layout.addWidget(self._display_widget)
        self._column = 0

    def setDisplayColumn(self, column: int) -> None:
        if column == self._column:
            return

        self._column = column
        current = (
            self._selection_model.currentNode()
            if self._selection_model is not None
            else None
        )
        self._refresh_display_widget(current)

    def displayColumn(self) -> int:
        return self._column

    def setModel(self, model: AbstractDAGModel | None) -> None:
        if model is self._model:
            return

        for signal, slot in self._model_connections:
            signal.disconnect(slot)

        self._model_connections.clear()
        self._model = model

        if model is not None:
            self._model_connections.append(
                (model.nodesDataChanged, self._handle_node_data_changed)
            )
            for signal, slot in self._model_connections:
                signal.connect(slot)

        self.setSelectionModel(
            GraphSelectionModel(model, parent=self) if model is not None else None
        )

    def model(self) -> AbstractDAGModel | None:
        return self._model

    def selectionModel(self) -> GraphSelectionModel | None:
        return self._selection_model

    def setSelectionModel(self, selection_model: GraphSelectionModel | None) -> None:
        if selection_model is self._selection_model:
            return

        if selection_model is not None and (
            self._model is None or selection_model.model() is not self._model
        ):
            raise ValueError("The selection model must use the inspector's model")

        if selection_model is self._selection_model:
            return

        for signal, slot in self._selection_connections:
            signal.disconnect(slot)
            
        self._selection_connections.clear()
        self._selection_model = selection_model

        if selection_model is not None:
            self._selection_connections = [
                (selection_model.currentNodeChanged, self._handle_current_node_changed)
            ]
            for signal, slot in self._selection_connections:
                signal.connect(slot)

        # Refresh the display widget with the current node of the new selection model.
        current = (
            selection_model.currentNode()
            if selection_model is not None
            else None
        )
        self._refresh_display_widget(current)

    def _handle_current_node_changed(self, node: NodeName | None, previous: NodeName | None) -> None:
        self._refresh_display_widget(node)

    def _handle_node_data_changed(self, nodes, columns:list[int], roles: list[Qt.ItemDataRole]) -> None:
        if self._selection_model is None:
            return
        current = self._selection_model.currentNode()
        if current in nodes and self._column in columns:
            self._refresh_display_widget(current)

    def _refresh_display_widget(self, node: NodeName | None) -> None:
        if node is None:
            self._display_widget.display("- no selection -")
            return
        data = self._model.nodeData(node, self._column, Qt.ItemDataRole.DisplayRole) if self._model is not None else None
        self._display_widget.display(data)
