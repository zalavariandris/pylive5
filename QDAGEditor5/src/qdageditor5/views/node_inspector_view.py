from typing import Callable, cast, Any
from bidict import bidict

from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qtpy.QtWidgets import (
    QFormLayout, 
    QFrame, 
    QGraphicsColorizeEffect,
    QLabel,
    QMenu, 
    QVBoxLayout, 
    QWidget
)

from qtpy.QtCore import (
    QEvent, 
    QObject, 
    Qt, 
    Signal, 
    SignalInstance,
    Slot,
)

from qtpy.QtGui import (
    QContextMenuEvent, 
    QAction
)

from ..models.abstract_dag_model import AbstractDAGModel, NodeName, InletName
from ..views.node_inspector_delegate import NodeInspectorDelegate

class NodeInspectorView(QFrame):
    EMPTY = None
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self._model: AbstractDAGModel | None = None
        self._selection_model: GraphSelectionModel | None = None
        self._current_node: NodeName | None = None
        self._model_connections: list[tuple[SignalInstance, Callable]] = []
        self._selection_connections: list[tuple[SignalInstance, Callable]] = []
        self._editor_connections: list[tuple[SignalInstance, Callable]] = []
        self._delegate = NodeInspectorDelegate(self)
        self._delegate.EMPTY = self.EMPTY
        self._editors: dict[InletName, QWidget] = {}
        self._labels: bidict[InletName, QWidget] = bidict()

        # Layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)

        ## heading
        self._heading = QFrame(self)
        self._heading.setFrameShape(QFrame.Shape.NoFrame)
        # self._heading.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        
        heading_layout =QVBoxLayout(self._heading)
        heading_layout.setContentsMargins(0,0,0,0)
        heading_layout.setSpacing(2)
        from qtpy.QtGui import QFont

        self._title = QLabel("- no selection -", self._heading)
        font = self._title.font()
        font.setBold(True)
        font.setPointSize(int(font.pointSize() * 1.25))
        self._title.setFont(font)
        heading_layout.addWidget(self._title)

        self._subtitle = QLabel("- info -", self._heading)
        font = self._subtitle.font()
        font.setPointSize(max(1, font.pointSize() - 1))
        self._subtitle.setFont(font)
        heading_layout.addWidget(self._subtitle)

        main_layout.addWidget(self._heading)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)
        ## Body
        self._form = QFormLayout()
        self._form.setSpacing(8)
        main_layout.addLayout(self._form)

        main_layout.addStretch()

    def setModel(self, model: AbstractDAGModel | None) -> None:
        """Install a model and a fresh selection model; None clears the inspector."""
        if model is self._model:
            return

        for signal, slot in self._model_connections:
            signal.disconnect(slot)

        self._model_connections.clear()
        self._model = model

        if model is not None:
            self._model_connections = [
                (model.nodesRemoved, self._handle_nodes_removed),
                (model.inletsReset, self._handle_inlets_reset),
                (model.inletDataChanged, self._handle_inlet_data_change),
                (model.linksAdded, self._handle_connections_changed),
                (model.linksRemoved, self._handle_connections_changed),
                (model.linksReset, self._handle_connections_changed),
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)

        # Replace rather than retarget the old selection model: other views
        # may still share it. Parent the default selection model to this view.
        self.setSelectionModel(
            GraphSelectionModel(model, parent=self) if model is not None else None
        )

    def model(self) -> AbstractDAGModel | None:
        return self._model

    def selectionModel(self) -> GraphSelectionModel | None:
        return self._selection_model

    def setSelectionModel(self, selection_model: GraphSelectionModel | None) -> None:
        """Use a selection model for this model, preserving the previous one."""
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
                (selection_model.currentNodeChanged, self._on_current_node_changed)
            ]
            for signal, slot in self._selection_connections:
                signal.connect(slot)

        # A shared selection model may already have a current node.
        current = selection_model.currentNode() if selection_model is not None else None
        self._on_current_node_changed(current, self._current_node)

    def setCurrentNode(self, node: NodeName | None) -> None:
        if self._selection_model is None:
            if node is not None:
                raise ValueError("Set a model and selection model before selecting a node")
            return

        self._selection_model.setCurrentNode(node)

    def _on_current_node_changed(self, node: NodeName | None, previous: NodeName | None) -> None:
        self._clear_form()
        self._current_node = node

        if node is None:
            self._title.setText("- no selection -")
            self._subtitle.setText("- info -")
            return

        assert self._model is not None
        self._title.setText(self._model.nodeHeaderData(node, Qt.ItemDataRole.DisplayRole))
        self._subtitle.setText(self._model.nodeData(node, 0, Qt.ItemDataRole.DisplayRole))
        self._build_form()


    def _clear_form(self) -> None:
        for signal, handler in self._editor_connections:
            signal.disconnect(handler)
        self._editor_connections.clear()
        self._editors.clear()
        self._labels.clear()
        while self._form.rowCount():
            self._form.removeRow(0)

    def _build_form(self) -> None:
        node = self._current_node
        assert self._model is not None
        assert node is not None

        for inlet_name in self._model.inlets(node):
            # create label
            label = QLabel(str(inlet_name))
            label.setTextFormat(Qt.TextFormat.PlainText)
            self._labels[inlet_name] = label
            label.installEventFilter(self)

            # create editor
            editor = self._delegate.createEditor(self._model, node, inlet_name)
            effect = QGraphicsColorizeEffect(editor)
            effect.setColor(Qt.GlobalColor.gray)
            effect.setStrength(0.5)
            effect.setEnabled(False)
            editor.setGraphicsEffect(effect)
            self._editors[inlet_name] = editor
            self._form.addRow(label, editor)

            # Initialize before connecting signals.
            self._update_inlet_presentation(node, inlet_name)
            self._delegate.setEditorData(self._model, node, inlet_name, self._editors[inlet_name])

            # bind user property if available
            user_property = editor.metaObject().userProperty()
            if user_property.isValid() and user_property.hasNotifySignal():
                signal_name = bytes(user_property.notifySignal().name()).decode()
                signal = getattr(editor, signal_name)

                def handle_change(
                    *args: Any,
                    node: NodeName = node,
                    inlet: InletName = inlet_name,
                    widget: QWidget = editor,
                ) -> None:
                    self._delegate.setModelData(self._model, node, inlet, widget)

                signal.connect(handle_change)
                self._editor_connections.append((signal, handle_change))

    def eventFilter(self, a0: QObject|None, a1: QEvent|None) -> bool:
        if self._model is None:
            return super().eventFilter(a0, a1)
        watched = a0
        event = a1
        
        if watched is not None and event is not None and event.type() == QEvent.Type.ContextMenu:

            # create context menu
            if watched not in self._labels.inverse:
                return False
            label = cast(QLabel, watched)
            
            menu = QMenu(label)
            inlet_name = self._labels.inverse[label]
            node_name = self._current_node

            # unset
            is_set = self._model.inletData(node_name, inlet_name, Qt.ItemDataRole.EditRole) is not self.EMPTY
            unset_action = QAction("Unset", menu)
            unset_action.setEnabled(is_set)
            def set_inlet_empty():
                assert self._model is not None
                self._model.setInletData(node_name, inlet_name, self.EMPTY, Qt.ItemDataRole.EditRole)
            unset_action.triggered.connect(set_inlet_empty)
            menu.addAction(unset_action)

            # disconnect
            is_connected = bool(list(self._model.inLinks(node_name, inlet_name)))
            disconnect_action = QAction("Disconnect", menu)
            disconnect_action.setEnabled(is_connected)
            def disconnect_inlet():
                assert self._model is not None
                links = list(self._model.inLinks(node_name, inlet_name))
                self._model.removeLinks(links)
            disconnect_action.triggered.connect(disconnect_inlet)
            menu.addAction(disconnect_action)

            # show context menu
            event.accept()
            try:
                menu.exec(event.globalPos())
            finally:
                menu.deleteLater()

            return True

        return super().eventFilter(watched, event)

    def _handle_nodes_removed(self, nodes: tuple[NodeName, ...]) -> None:
        if self._current_node in nodes:
            self.setCurrentNode(None)

    def _handle_inlets_reset(self, node: NodeName) -> None:
        if node == self._current_node:
            self._clear_form()
            self._build_form()

    def _handle_inlet_data_change(
        self, node: NodeName, inlets: tuple[InletName, ...], roles: list[int],
    ) -> None:
        assert self._model is not None

        if node != self._current_node:
            return
        
        for inlet in inlets:
            self._update_inlet_presentation(node, inlet)
            if inlet in self._editors:
                self._delegate.setEditorData(self._model, node, inlet, self._editors[inlet])

    def _handle_connections_changed(self, *_args: object) -> None:
        if self._current_node is not None:
            for inlet in self._editors:
                self._update_inlet_presentation(self._current_node, inlet)

    def _update_inlet_presentation(self, node: NodeName, inlet: InletName) -> None:
        assert self._model is not None
        is_empty = self._model.inletData(node, inlet, Qt.ItemDataRole.EditRole) is self.EMPTY
        is_connected = bool(list(self._model.inLinks(node, inlet)))

        editor = self._editors.get(inlet)
        if editor is not None:
            editor.setEnabled(not is_connected)
            effect = editor.graphicsEffect()
            if effect is not None:
                effect.setEnabled(is_connected or is_empty)
