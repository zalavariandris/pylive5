from enum import StrEnum



from pyflow5.pygraphrt_dag_model import PyFlowRTModel
from pygraphrt.graph_executor import ExecutionFailure, ExecutionSuccess
from qdageditor5.adapters.nodes_list_model_adapter import NodesListModelAdapter
from qdageditor5.adapters.nodes_list_selection_model_adapter import NodesListSelectionModelAdapter
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qtpy.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    Qt,
    Signal,
    Slot
)

from qtpy.QtWidgets import (
    QCheckBox,
    QLabel,
    QHBoxLayout,
    QVBoxLayout, 
    QWidget
)


import myqtx
import pygraphrt as rt


class DetailsView(QWidget):
    class SelectionBehaviour(StrEnum):
        FirstSelected = "first"
        LastSelected = "last"
        Current = "current"
        
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._selection_behaviour: DetailsView.SelectionBehaviour = DetailsView.SelectionBehaviour.FirstSelected
        layout = QVBoxLayout(self)
        self.setLayout(layout)
        header = QHBoxLayout()
        self._viewer_lock_switch = QCheckBox("-node-", self)
        header.addWidget(self._viewer_lock_switch)
        layout.addLayout(header)
        self._body: QWidget|None = QLabel("Details will be shown here.")
        layout.addWidget(self._body)

        self._model: QAbstractItemModel|None = None

    def setBodyWidget(self, widget: QWidget):
        self._body = widget

    def setModel(self, model: QAbstractItemModel|None):
        self._model = model

    def setSelecitonModel(self, selection_model: GraphSelectionModel|None):
        self._selection_model = selection_model

    def selectionModel(self):
        return self._selection_model

    def selectionBehaviour(self):
        return self._selection_behaviour

    def setSelectionBehaviour(self, behaviour: SelectionBehaviour):
        self._selection_behaviour = behaviour

    def showCurrentEvent(self):
        pass


class Viewer(QWidget):
    def __init__(self, parent=None)->None:
        super().__init__(parent)
        viewer_layout = QVBoxLayout(self)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_header = QHBoxLayout()
        viewer_header.addWidget(QLabel("Viewer", self))
        viewer_header.addStretch()
        self._viewer_lock_switch = QCheckBox("-node-", self)
        self._viewer_lock_switch.setToolTip("Keep viewing this output when the selection changes.")
        self._viewer_lock_switch.setChecked(False)
        self._viewer_lock_switch.toggled.connect(lambda checked: None)
        viewer_header.addWidget(self._viewer_lock_switch)
        viewer_layout.addLayout(viewer_header)

        self._display_widget = myqtx.DisplayWidget(self)
        viewer_layout.addWidget(self._display_widget)

        self._model: NodesListModelAdapter|None = None
        self._model_connections: list[tuple[Signal, Slot]] = []
        self._nodes_selection_model: GraphSelectionModel|None = None
        self._selection_model_connections: list[tuple[Signal, Slot]] = []
        self._current_node_index:QModelIndex = QModelIndex()

        self._watcher:rt.Watcher|None = None



    def model(self):
        return self._model

    def setModel(self, model: NodesListModelAdapter|None):
        assert isinstance(model, NodesListModelAdapter) or model is None

        if self._model:
            # Disconnect previous connections
            for signal, slot in self._model_connections:
                try:
                    signal.disconnect(slot)
                except TypeError as err:
                    print(f"Failed to disconnect signal {signal} from slot {slot} due to {err}")
            self._model_connections.clear()
            
        if model:
            # Connect new model signals
            self._model_connections = [
                (model.modelReset, self._on_model_reset),
                (model.dataChanged, self._on_data_changed),
                (model.rowsRemoved, self._on_rows_removed)
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)
        
        self._model = model
        self._setCurrentIndex(QModelIndex())

    def currentNodeName(self):
        return self._current_node_index

    def _setCurrentIndex(self, node_index:QModelIndex)->bool:
        assert isinstance(node_index, QModelIndex), f"Expected QModelIndex, got {node_index}"
        if self._viewer_lock_switch.isChecked():
            print("- Lock is checked, cant set current node")
            # todo: i dont ike this api design.
            # either the Viewer should listen to the selection model directly, or
            # create a wrapper reusable widget with eg a breadcrump, that 
            # has controls to update on selection or not. This would be useful 
            # in other widgets detail-views as well.
            return False

        self._current_node_index = node_index
        self._update_display()
        return True

    def setSelectionModel(self, nodes_selection_model: NodesListSelectionModelAdapter):
        assert isinstance(nodes_selection_model, NodesListSelectionModelAdapter) or nodes_selection_model is None

        if nodes_selection_model is self._nodes_selection_model:
            return
        
        if self._nodes_selection_model:
            for signal, slot in self._selection_model_connections:
                signal.disconnect(slot)
            self._selection_model_connections = []
            self._nodes_selection_model = None

        if nodes_selection_model:
            self._selection_model_connections = [
                (
                    nodes_selection_model.selectionChanged, 
                    lambda selected, deselected: self._setCurrentIndex(
                        selected.indexes()[0] if selected.indexes() else QModelIndex()
                    )
                )
            ]
            for signal, slot in self._selection_model_connections:
                signal.connect(slot)
            self._nodes_selection_model = nodes_selection_model

    def _on_model_reset(self):
        self._setCurrentIndex(QModelIndex())

    def _on_data_changed(self, topLeft, bottomRight, roles):
        columns = range(topLeft.column(), bottomRight.column() + 1)

        if 0 not in columns:
            return

        rows = range(topLeft.row(), bottomRight.row() + 1)

        if self._current_node_index.row() in rows:
            self._update_display()

    def _on_rows_removed(self, parent:QModelIndex, first: int, last: int):
        if self._current_node_index.row() >= first and self._current_node_index.row() <= last:
            self._setCurrentIndex(QModelIndex())

    def _update_display(self):
        print(f"Viewer->_update_display {{current_nodename={self._current_node_index}}}")
        if self._current_node_index.isValid() is False:
            self._viewer_lock_switch.setText("-no node selected-")
            self._display_widget.clear()
            return
        
        if self._model is None: 
            self._viewer_lock_switch.setText("! no model !")
            self._display_widget.clear()
            return

        result = self._model.data(self._current_node_index, PyFlowRTModel.ExecutionRole)
        self._viewer_lock_switch.setText(f"{self._current_node_index}")
        self._display_widget.display(result)
        # match result:
        #     case ExecutionFailure() as failure:
        #         self._display_widget.display(failure.reason)
        #     case ExecutionSuccess() as success:
        #         self._display_widget.display(success.result)
        #     case None:
        #         self._display_widget.display("Node has not been executed yet.")
        #     case _:
        #         self._display_widget.clear()
        #         assert False, f"Unexpected execution state got: {execution}"
                
        # self._display_widget.display(execution)
        # match data:
        #     case Exception():
        #         self._display_widget.display(data)
        #     case ExecutionSuccess():
        #         self._display_widget.display(data)
        #     case _:
        #         self._display_widget.clear()

