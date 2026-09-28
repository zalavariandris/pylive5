import json
import os
from textwrap import dedent
import traceback
from typing import TYPE_CHECKING


from pyflow5.pygraphrt_model import PyFlowRTModel
from pygraphrt.errors import GraphExecutionError
from pygraphrt.graph_executor import ExecutionFailure, ExecutionSuccess, NodeExecution
from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import (
    QAbstractItemModel,
    QObject,
    QPoint,
    QPointF,
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
    def __init__(self, parent=None):
        super().__init__(parent)
        viewer_layout = QVBoxLayout(self)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_header = QHBoxLayout()
        viewer_header.addWidget(QLabel("Viewer", self))
        viewer_header.addStretch()
        self._viewer_lock_switch = QCheckBox("Lock", self)
        self._viewer_lock_switch.setToolTip("Keep viewing this output when the selection changes.")
        self._viewer_lock_switch.setChecked(False)
        self._viewer_lock_switch.toggled.connect(lambda checked: None)
        viewer_header.addWidget(self._viewer_lock_switch)
        viewer_layout.addLayout(viewer_header)

        self._display_widget = myqtx.DisplayWidget(self)
        viewer_layout.addWidget(self._display_widget)

        self._model:PyFlowRTModel|None = None
        self._model_connections = []
        self._current_nodename:NodeName|None = None

        self._watcher:rt.Watcher|None = None

    def _update_display(self):
        if self._current_nodename is None:
            self._display_widget.clear()
        else:
            data = self._model.nodeData(self._current_nodename, self._model.ResultsRole) if self._model else None
            self._display_widget.display(data)

    def model(self):
        return self._model

    def setModel(self, model: PyFlowRTModel|None):
        if self._model:
            # Disconnect previous connections
            for connection in self._model_connections:
                connection.disconnect()
            self._model_connections.clear()
            
        if model:
            # Connect new model signals
            self._model_connections = [
                (model.modelReset, self._on_model_reset),
                (model.nodeDataChanged, self._on_node_data_changed),
                (model.nodesRemoved, self._on_nodes_removed)
            ]
        
        self._model = model
        self.setCurrentNodeName(None)

    def currentNodeName(self):
        return self._current_nodename

    def setCurrentNodeName(self, node_name:NodeName|None):
        assert node_name is None or isinstance(node_name, str)
        self._current_nodename = node_name
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        if self._model and self._current_nodename is not None:
            node_ref = self._model.getNode(self._current_nodename)
            self._watcher = rt.watch(
                self._model._graph, 
                node_ref, 
                self._on_watch_triggered
            )

        self._on_watch_triggered()
        self._update_display()

    def _on_watch_triggered(self):
        try:
            node_ref = self._model.getNode(self._current_nodename)
            if node_ref is not None:
                result = self._model._executor.execute(node_ref)
                self._model.setNodeData(self._current_nodename, self._model.ResultsRole, result)

        except GraphExecutionError as err:
            traceback.print_exc()
            self._model.setNodeData(self._current_nodename, self._model.ResultsRole, err)

    def _on_model_reset(self):
        self.setCurrentNodeName(None)

    def _on_node_data_changed(self, nodes):
        if self._current_nodename in nodes:
            self._update_display()

    def _on_nodes_removed(self, nodes):
        if self._current_nodename in nodes:
            self.setCurrentNodeName(None)

    def _update_display(self):
        if self._current_nodename is None:
            self._display_widget.clear()
        if self._model is None: 
            self._display_widget.clear()

        data:NodeExecution = self._model.nodeData(self._current_nodename, self._model.ResultsRole)
        match data:
            case ExecutionFailure():
                self._display_widget.display(data.reason)
            case ExecutionSuccess():
                self._display_widget.display(data.result)
            case _:
                self._display_widget.clear()

