import json
import os
from textwrap import dedent
import traceback
from typing import TYPE_CHECKING


from pyflow5.pygraphrt_model import PyFlowRTModel

from pygraphrt.graph_executor import ExecutionFailure, ExecutionSuccess
from qdageditor5.models.abstract_dag_model import NodeName
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qtpy.QtCore import (
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

        self._model:PyFlowRTModel|None = None
        self._model_connections: list[tuple[Signal, Slot]] = []
        self._selection_model: GraphSelectionModel|None = None
        self._selection_model_connections: list[tuple[Signal, Slot]] = []
        self._current_nodename:NodeName|None = None

        self._watcher:rt.Watcher|None = None

    def _update_display(self):
        if self._current_nodename is None:
            self._display_widget.clear()
        else:
            data = self._model.nodeData(self._current_nodename, self._model.ExecutionRole) if self._model else None
            self._display_widget.display(data)

    def model(self):
        return self._model

    def setModel(self, model: PyFlowRTModel|None):
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
                (model.nodesDataChanged, self._on_node_data_changed),
                (model.nodesRemoved, self._on_nodes_removed)
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)
        
        self._model = model
        self.setCurrentNodeName(None)

    def currentNodeName(self):
        return self._current_nodename

    def setCurrentNodeName(self, node_name:NodeName|None)->bool:
        assert node_name is None or isinstance(node_name, str)
        if self._viewer_lock_switch.isChecked():
            print("- Lock is checked, cant set current node")
            # todo: i dont ike this api design.
            # either the Viewer should listen to the selection model directly, or
            # create a wrapper reusable widget with eg a breadcrump, that 
            # has controls to update on selection or not. This would be useful 
            # in other widgets detail-views as well.
            return False

        self._current_nodename = node_name
        self._update_display()
        return True

    def setSelectionModel(self, graphselection: GraphSelectionModel):
        if graphselection is self._selection_model:
            return
        
        if self._selection_model:
            for signal, slot in self._selection_model_connections:
                signal.disconnect(slot)
            self._selection_model_connections = []
            self._selection_model = None

        if graphselection:
            self._selection_model_connections = [
                (
                    graphselection.nodesSelectionChanged, 
                    lambda selected, deselected: 
                    self.setCurrentNodeName(next(iter(selected)) if selected else None)
                )
            ]
            for signal, slot in self._selection_model_connections:
                signal.connect(slot)
            self._selection_model = graphselection

    def _on_model_reset(self):
        self.setCurrentNodeName(None)

    def _on_node_data_changed(self, nodes, roles):
        print(f"Viewer->_on_node_data_changed {{nodes={nodes}, roles={roles}}}")
        if self._current_nodename in nodes:
            self._update_display()

    def _on_nodes_removed(self, nodes):
        if self._current_nodename in nodes:
            self.setCurrentNodeName(None)

    def _update_display(self):
        print(f"Viewer->_update_display {{current_nodename={self._current_nodename}}}")
        if self._current_nodename is None:
            self._viewer_lock_switch.setText("-no node selected-")
            self._display_widget.clear()
            return
        
        if self._model is None: 
            self._viewer_lock_switch.setText("! no model !")
            self._display_widget.clear()
            return

        result = self._model.nodeData(self._current_nodename, self._model.ExecutionRole)
        self._viewer_lock_switch.setText(f"{self._current_nodename}")
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

