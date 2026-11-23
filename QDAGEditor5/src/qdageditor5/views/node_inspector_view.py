from typing import Callable, cast, Any
from bidict import bidict

from qtpy.QtWidgets import (
    QFormLayout, 
    QFrame, 
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
    Slot
)

from qtpy.QtGui import (
    QContextMenuEvent, 
    QAction
)

from ..core.inspector_roles import InspectorRoles
from ..models.abstract_dag_model import AbstractDAGModel, NodeName, InletName
from ..views.node_inspector_delegate import NodeInspectorDelegate

class NodeInspectorView(QFrame):
    EMPTY = None
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self._model: AbstractDAGModel | None = None
        self._current_node: NodeName | None = None
        self._model_connections: list[tuple[Signal, Callable]] = []
        self._editor_connections: list[tuple[Signal, Callable]] = []
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
        if model is self._model:
            return
        for signal, slot in self._model_connections:
            signal.disconnect(slot)
        self._model_connections.clear()
        self._clear_form()
        self._current_node = None
        self._model = model

        if model is not None:
            self._model_connections = [
                (model.nodesRemoved, self._handle_nodes_removed),
                (model.inletsReset, self._handle_inlets_reset),
                (model.inletDataChanged, self._handle_inlet_data_change),
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)

    def setCurrentNode(self, node: NodeName | None) -> None:
        if node == self._current_node:
            return
        
        self._clear_form()
        self._current_node = node

        if node is not None:
            assert self._model is not None
            self._title.setText(self._model.nodeHeaderData(node, Qt.ItemDataRole.DisplayRole))
            self._subtitle.setText(self._model.nodeData(node, Qt.ItemDataRole.DisplayRole))
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
            self._labels[inlet_name] = label
            label.installEventFilter(self)

            # create editor
            editor = self._delegate.createEditor(self._model, node, inlet_name)
            self._editors[inlet_name] = editor
            self._form.addRow(label, editor)

            # Initialize before connecting signals.
            self.__set_label_data(node, inlet_name, Qt.ItemDataRole.EditRole)
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
        assert self._model is not None
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
        
        # if not roles or InspectorRoles.DataTypeRole in roles:
        #     self._handle_inlets_reset(node)

        # elif Qt.ItemDataRole.EditRole in roles:
        for inlet in inlets:
            self.__set_label_data(node, inlet, Qt.ItemDataRole.EditRole)
            if inlet in self._editors:
                self._delegate.setEditorData(self._model, node, inlet, self._editors[inlet])

    def __set_label_data(self, node, inlet, role:Qt.ItemDataRole):
        if inlet in self._labels:
            is_empty = self._model.inletData(node, inlet, Qt.ItemDataRole.EditRole) is self.EMPTY
            is_connected = bool(list(self._model.inLinks(node, inlet)))
            # Update the label to reflect the inlet's state
            # icons = '✏️', '🌫️','🔗'
            icons = '🔵', '⚪','🔗'
            # icons = '◯','●','🔗'
            # icons = "-", "+", "/"
            # icons = '🔵', '⚪', '🔘'
            # icons = '■', '□', '▣'
            # icons = '■', '▧', '▰'
            # icons = '◈', '◇', '↔'
            # icons = '⬤', '◯', '◉'

            label = cast(QLabel, self._labels[inlet])
            if is_connected:
                label.setText(f"{icons[2]} {inlet}")
            elif is_empty:
                label.setText(f"{icons[1]} {inlet}")
            else:
                label.setText(f"{icons[0]} {inlet}")
