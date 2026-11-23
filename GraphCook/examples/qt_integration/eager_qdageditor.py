import builtins
from enum import IntEnum
import inspect
from textwrap import dedent
from typing import Callable, Iterable, Any, Protocol, TypedDict, cast


import bidict
from graphcook.eager_observable_engine import (
    InletSignature,
    OperatorHandle, 
    OperatorSignature, 
    NodeStatus,
    ProviderStatus,
    GraphChange
)

from graphcook.eager_observable_engine import EagerEngine
from qdageditor5.core.item_data_roles import NodeDataRole
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5
from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel, 
    CellIdx,
    DirectionalLinkId, 
    NodeName, 
    InletName,
    OutletName
)

from qtpy.QtCore import QPointF, QTimer, Qt, QAbstractListModel, QSignalBlocker, Signal, Property
from qtpy.QtWidgets import QAbstractScrollArea, QApplication, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QGraphicsColorizeEffect, QGraphicsEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListView, QMainWindow, QMenu, QMenuBar, QPlainTextEdit, QSizePolicy, QSpinBox, QSplitter, QStackedLayout, QStatusBar, QVBoxLayout, QWidget
from graphcook.eager_observable_engine import (
    NodeId, EagerEngineChange, DirtyStatus, RunningStatus, SucceededStatus, FailedStatus,
)

from myqtx.selection_dialog_view import SelectionDialog
from myqtx.widgets.displaywidget import DisplayWidget
from QtScriptEditorAdvanced import ScriptEditAdvanced
from qtpy.QtCore import SignalInstance, QObject


############
# CONTRACT #
############


# class NodeSignatureProtocol(TypedDict):
#     __operator__: OperatorSignature


# class NodeStatusProtocol(TypedDict):
#     status: NodeStatus


# class EngineGraphProtocol(Protocol):
#     # read
#     def nodes(self) -> Iterable['NodeId']:
#         ...

#     def attributes(self, node: 'NodeId') -> NodeSignatureProtocol:
#         ...

#     def nodes_status(self, node: 'NodeId') -> NodeStatus:
#         ...

#     def in_links(self, node: 'NodeId') -> Iterable[tuple['NodeId', 'NodeId', str]]:
#         ...

#     def out_links(self, node: 'NodeId') -> Iterable[tuple['NodeId', 'NodeId', str]]:
#         ...

#     def links(self) -> Iterable[tuple['NodeId', 'NodeId', str]]:
#         ...

#     # update
#     def add_link(self, src: 'NodeId', dst: 'NodeId', inlet: str) -> None:
#         ...

#     def remove_link(self, source: 'NodeId', target: 'NodeId', inlet: str) -> None: ...

#     # observe
#     def listen(self, callback: Callable[[GraphChange], None]) -> None:
#         ...


# class ProviderProtocol(Protocol):
#     # read
#     def operators(self) -> Iterable['OperatorHandle']:
#         ...



# class EagerEngineProtocol(
#     EngineGraphProtocol, 
#     ProviderProtocol, 
#     ObservableProtocol, 
#     Protocol
# ):
#     def set(self, node: NodeId, **attributes: object) -> None: ...
#     def unset(self, node: NodeId, name: str) -> None: ...
#     def script(self) -> str: ...
#     def set_script(self, script: str) -> None: ...
#     def invalidate(self, *nodes: NodeId) -> None: ...
#     def evaluate_node(self, *nodes: NodeId) -> None: ...
#     def effect(self, node: 'NodeId') -> None: ...
#     def remove_effect(self, node: 'NodeId') -> None: ...


##########
# MODELS #
##########
class EagerGraphModel(AbstractDAGModel):
    def __init__(self, engine: EagerEngine, parent=None):
        super().__init__(parent=parent)
        self._engine = engine
        self._unsubscribe = self._engine.listen(self._handle_engine_change)

    # Adapter
    def mapFromSource(self, node: 'NodeId', inlet: InletName|None = None)->NodeName|tuple[NodeName, InletName]:
        # note: right now mapping is straightforward. if the DAGModel will use 
        # its own datastructure to represent nodes and inlets, this will become a bit more
        # complex
        if inlet is not None:
            return node, inlet
        else:
            return node

    def mapToSource(self, node: NodeName, inlet: InletName|None=None) -> 'NodeId|tuple[NodeId, str]':
        # note: right now mapping is straightforward. if the DAGModel will use 
        # its own datastructure to represent nodes and inlets, this will become a bit more
        # complex
        if inlet is not None:
            return node, inlet
        else:
            return node

    def _handle_engine_change(self, engine_change: EagerEngineChange) -> None:
        if nodes_change := engine_change.get("nodes"):
            removed = tuple(self.mapFromSource(node) for node in nodes_change.get("removed", {}))
            if removed:
                self.nodesRemoved.emit(removed)

            for node, attributes_change in nodes_change.get("updated", {}).items():
                node_name = self.mapFromSource(node)
                changed_keys = dict.fromkeys((
                    *attributes_change.get("added", {}),
                    *attributes_change.get("removed", {}),
                    *attributes_change.get("updated", {}),
                ))
                attributes = self._engine.attributes(node)
                signature = self._engine.operator_signature(attributes["__operator__"])
                declared_inlets = signature.inlets if signature is not None else {}
                linked_inlets = {inlet for _, _, inlet in self._engine.in_links(node)}
                structural_keys = (
                    set(attributes_change.get("added", {}))
                    | set(attributes_change.get("removed", {}))
                ) - set(declared_inlets) - linked_inlets
                if "__operator__" in changed_keys or structural_keys:
                    self.inletsReset.emit(node_name)
                else:
                    self.inletDataChanged.emit(
                        node_name,
                        tuple(changed_keys),
                        [Qt.ItemDataRole.EditRole, Qt.ItemDataRole.DisplayRole],
                    )

        if links_change := engine_change.get("links"):
            for src, dst, inlet in links_change.get("added", {}):
                self.inletDataChanged.emit(
                    self.mapFromSource(dst),
                    (inlet,),
                    [Qt.ItemDataRole.EditRole, Qt.ItemDataRole.DisplayRole],
                )
            for src, dst, inlet in links_change.get("removed", {}):
                self.inletDataChanged.emit(
                    self.mapFromSource(dst),
                    (inlet,),
                    [Qt.ItemDataRole.EditRole, Qt.ItemDataRole.DisplayRole],
                )

        if status_change := engine_change.get('nodes_status'):
            for node, new_value in status_change.get('added', {}).items():
                print(f"node status added for {node}({new_value})")
                node_name = self.mapFromSource(node)
                self.nodesDataChanged.emit(tuple([node_name]), tuple())

            for node, value_change in status_change.get('updated', {}).items():
                print(f"node status updated for {node}({value_change.get('old')}->{value_change.get('new')})")
                node_name = self.mapFromSource(node)
                self.nodesDataChanged.emit(tuple([node_name]), tuple())

            for node, old_value in status_change.get('removed', {}).items():
                if node not in self._engine.nodes():
                    continue
                print(f"node status removed for {node}({old_value})")
                node_name = self.mapFromSource(node)
                self.nodesDataChanged.emit(tuple([node_name]), tuple())

    # READ
    def nodes(self) -> Iterable[NodeName]:
        for node in self._engine.nodes():
            yield node

    def nodeHeaderData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return f"{self.mapToSource(node_name)}"
        return None

    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node_data = self._engine.attributes(self.mapToSource(node_name))
        node_status = self._engine.nodes_status(self.mapToSource(node_name))
        match role:
            case Qt.ItemDataRole.DisplayRole:
                op:OperatorSignature = node_data['__operator__']
                return op.name
            
            case Qt.ItemDataRole.ForegroundRole:
                match node_status:
                    case FailedStatus():
                        return Qt.GlobalColor.red
                    case RunningStatus():
                        return Qt.GlobalColor.yellow
                    case SucceededStatus():
                        return None
                    case DirtyStatus():
                        return None
                    case _:
                        return None
                    
            case NodeDataRole.TrailingRole:
                match node_status:
                    case FailedStatus() as failed:
                        return f"💥{type(failed.reason).__name__}: {failed.reason}"
                    case RunningStatus():
                        return "🧠 running..."
                    case SucceededStatus() as success:
                        return f"✨" + (f" {success.duration_seconds}s" if success.duration_seconds is not None else "")
                    case DirtyStatus():
                        return "🕸️"
                    case _:
                        return None
                    
        return None

    def nodeCellCount(self, node: NodeName) -> int:
        return 0

    def nodeCellData(self, node: NodeName, column: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        node_data = self._engine.attributes(self.mapToSource(node))
        operator_handle: OperatorHandle = node_data['__operator__']
        operator_signature = self._engine.operator_signature(operator_handle)
        parameters = operator_signature.inlets if operator_signature is not None else {}
        inputs = {name: value for name, value in node_data.items() if name != "__operator__"}
        linked_inlets = [inlet for _, _, inlet in self._engine.in_links(self.mapToSource(node))]
        yield from dict.fromkeys((*parameters, *inputs, *linked_inlets))

    def inletHeaderData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return str(inlet)
            case _:
                return None

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                node_id = self.mapToSource(node)
                inputs = self._engine.attributes(node_id)
                return str(inputs.get(inlet, EMPTY))

            case Qt.ItemDataRole.EditRole:
                node_id = self.mapToSource(node)
                inputs = self._engine.attributes(node_id)
                return inputs.get(inlet, EMPTY)
            
            case InspectorRoles.DataTypeRole:
                node_data = self._engine.attributes(self.mapToSource(node))
                operator_handle: OperatorHandle = node_data['__operator__']
                operator_signature: OperatorSignature = self._engine.operator_signature(operator_handle)
                parameter = operator_signature.inlets.get(inlet) if operator_signature is not None else None
                return parameter.type if parameter is not None else EMPTY
            case _:
                return None

    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        return ['out']

    def outletData(self, node: NodeName, outlet: OutletName, role:int) -> Any:
        return None

    def inLinks(self, target_node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        for src, dst, linked_inlet in self._engine.in_links(self.mapToSource(target_node)):
            if linked_inlet == inlet:
                yield (src, 'out', dst, linked_inlet)

    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        for src, dst, inlet in self._engine.out_links(self.mapToSource(source_node)):
            if outlet == 'out':
                yield (src, 'out', dst, inlet)

    def links(self) -> Iterable[DirectionalLinkId]:
        for src, dst, inlet in self._engine.links():
            yield (src, 'out', dst, inlet)

    def linkSource(self, link: DirectionalLinkId) -> tuple[NodeName,OutletName]:
        src, outlet, dst, inlet = link
        return (src, outlet)

    def linkTarget(self, link: DirectionalLinkId) -> tuple[NodeName,InletName]:
        src, outlet, dst, inlet = link
        return (dst, inlet)

    # update
    def removeNodes(self, nodes: Iterable[NodeName]) -> bool:
        print("remove ndoes")
        self._beginRemoveNodes(nodes)
        for node in nodes:
            self._engine.delete(self.mapToSource(node))
        self._endRemoveNodes()
        return True

    def addLinks(self, links:Iterable[DirectionalLinkId]) -> bool:
        for link in links:
            src, outlet, dst, inlet = link
            source = self.mapToSource(src)
            target = self.mapToSource(dst)
            try:
                # note add_link raises an error.
                self._engine.add_link(source, target, str(inlet))
            except ValueError as error:
                return False

        return True

    def removeLinks(self, links) -> bool:
        for link in links:
            src, outlet, dst, inlet = link
            source_nodeid = self.mapToSource(src)
            target_nodeid = self.mapToSource(dst)
            inlet_id = str(inlet)
            self._engine.remove_link(source_nodeid, target_nodeid, inlet_id)
        return True

    def setInletData(self, node: NodeName, inlet: InletName, value: Any, role: int) -> bool:
        if role == Qt.ItemDataRole.EditRole:
            try:
                if value is EMPTY:
                    self._engine.unset(self.mapToSource(node), str(inlet))
                    return True
                else:
                    self._engine.set(self.mapToSource(node), **{str(inlet): value})
                    return True
            except ValueError as error:
                return False
        return False

    def closeEvent(self, event):
        self._unsubscribe()
        super().closeEvent(event)


class OperatorListModel(QAbstractListModel):
    def __init__(self, engine: EagerEngine, parent=None):
        super().__init__(parent=parent)
        self._engine = engine

    def rowCount(self, parent=None) -> int:
        return len(list(self._engine.operators()))

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            all_operators = list(self._engine.operators())
            return all_operators[index.row()].name
        return None

    def _handle_engine_change(self, engine_change: EagerEngineChange):
        if operators_change:=engine_change.get('operators'):
            operators_change.get('added', {})
            operators_change.get('removed', {})
            operators_change.get('updated', {})

# class AttributeListModel(QAbstractListModel):
#     def __init__(self, engine: EagerEngine, node: NodeId, parent=None):
#         super().__init__(parent=parent)
#         self._engine = engine
#         self._node = node

#     def rowCount(self, parent=None) -> int:
#         return len(list(self._engine.attributes(self._node).items()))

#     def data(self, index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
#         if not index.isValid():
#             return None
#         if role == Qt.ItemDataRole.DisplayRole:
#             all_attributes = list(self._engine.attributes(self._node).items())
#             key, value = all_attributes[index.row()]
#             return f"{key}: {value}"
#         return None

#########
# VIEWS #
#########

class InspectorRoles(IntEnum):
    DataTypeRole = Qt.ItemDataRole.UserRole + 100
    DefaultValueRole = Qt.ItemDataRole.UserRole + 101

from typing import Any

from qtpy.QtCore import Property, Signal
from qtpy.QtWidgets import QLineEdit
from qtpy.QtWidgets import QVBoxLayout, QWidget

from qtpy.QtGui import QContextMenuEvent

from qtpy.QtCore import QEvent, QObject
from qtpy.QtGui import QContextMenuEvent
from qtpy.QtGui import QAction

import inspect
EMPTY = inspect.Parameter.empty

from qtpy.QtWidgets import QGraphicsOpacityEffect
class GraphInspectorDelegate(QObject):
    def __init__(self, parent:QObject|None=None):
        super().__init__(parent=parent)
        self._model = None

    def createEditor(self, model:AbstractDAGModel, node: NodeName, inlet: InletName) -> QWidget:
        inlet_value = model.inletData(node, inlet, Qt.ItemDataRole.EditRole)
        is_connected = bool(list(model.inLinks(node, inlet)))

        # if is_connected:
        #     return QLabel("(Linked)")
        
        datatype = model.inletData(node, inlet, InspectorRoles.DataTypeRole)

        # fallback
        if datatype is EMPTY or datatype is Any:
            datatype = type(inlet_value)

        # match editor based on datatype
        editor:QWidget|None = None
        if datatype is str:
            editor = QLineEdit()

        if datatype is int:
            editor = QSpinBox()
            editor.setRange(-(2**31), 2**31 - 1)
            editor.clear()

        if datatype is float:
            editor = QDoubleSpinBox()
            editor.setRange(-999, 999)
            editor.clear()

        if editor is None:
            # fallback to display the data
            editor = QLineEdit()
            editor.setReadOnly(True)

        # add the dim effect to the editors
        opacity_effect = QGraphicsOpacityEffect(editor)
        opacity_effect.setOpacity(0.15)
        opacity_effect.setEnabled(False)
        colorize_effect = QGraphicsColorizeEffect(editor)
        colorize_effect.setColor(Qt.GlobalColor.gray)
        colorize_effect.setStrength(0.5)
        colorize_effect.setEnabled(False)
        editor.setGraphicsEffect(colorize_effect)
        return editor

    def setEditorData(self, model:AbstractDAGModel, node: NodeName, inlet: InletName, widget: QWidget) -> None:
        value = model.inletData(node, inlet, Qt.ItemDataRole.EditRole)
        is_connected = bool(list(model.inLinks(node, inlet)))
        is_empty = value is EMPTY
        effect = widget.graphicsEffect()
        assert isinstance(effect, QGraphicsEffect)
        effect.setEnabled(is_connected or is_empty)

        with QSignalBlocker(widget):
            metaobject = widget.metaObject()
            if metaobject is None:
                return

            user_property = metaobject.userProperty()
            if not user_property.isValid():
                return

            if is_connected:
                widget.setEnabled(False)
            else:
                widget.setEnabled(True)

            if is_empty:
                try:
                    widget.clear()
                except AttributeError:
                    pass
            else:
                # write the value to the widget's user property
                user_property.write(widget, value)

    def setModelData(self, model:AbstractDAGModel, node: NodeName, key: InletName, widget: QWidget) -> None:
        metaobject = widget.metaObject()
        if metaobject is None:
            return
        
        user_property = metaobject.userProperty()
        if not user_property.isValid():
            return
        
        new_value = user_property.read(widget)
        model.setInletData(node, key, new_value, Qt.ItemDataRole.EditRole)


from bidict import bidict
class GraphInspectorView(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self._model: AbstractDAGModel | None = None
        self._current_node: NodeName | None = None
        self._model_connections: list[tuple[SignalInstance, Callable[..., None]]] = []
        self._editor_connections: list[tuple[SignalInstance, Callable[..., None]]] = []
        self._delegate = GraphInspectorDelegate(self)
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
        self._form = QFormLayout(self)
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
            is_set = self._model.inletData(node_name, inlet_name, Qt.ItemDataRole.EditRole) != EMPTY
            unset_action = QAction("Unset", menu)
            unset_action.setEnabled(is_set)
            def set_inlet_empty():
                assert self._model is not None
                self._model.setInletData(node_name, inlet_name, EMPTY, Qt.ItemDataRole.EditRole)
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
        
        if not roles or InspectorRoles.DataTypeRole in roles:
            self._handle_inlets_reset(node)

        elif Qt.ItemDataRole.EditRole in roles:
            for inlet in inlets:
                self.__set_label_data(node, inlet, Qt.ItemDataRole.EditRole)
                if inlet in self._editors:
                    self._delegate.setEditorData(self._model, node, inlet, self._editors[inlet])

    def __set_label_data(self, node, inlet, role:Qt.ItemDataRole):
        if inlet in self._labels:
            is_empty = self._model.inletData(node, inlet, Qt.ItemDataRole.EditRole) == EMPTY
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

class ProviderView(QWidget):
    def __init__(self, engine: EagerEngine, parent=None):
        super().__init__(parent=parent)
        self._engine = engine
        layout = QGridLayout()
        self.setLayout(layout)

        self.script_view = ScriptEditAdvanced()
        self.script_view.setPlainText(self._engine.script())
        self.script_view.textChanged.connect(self._handle_editor_text_changed)

        layout.addWidget(self.script_view, 0, 0)

        self._statusbar = QStatusBar()
        self._statusbar.setSizeGripEnabled(False)
        layout.addWidget(self._statusbar, 1, 0, 1, 2)
        self.model = OperatorListModel(self._engine)


        engine.listen(self._handle_engine_change)

    def _handle_editor_text_changed(self) -> None:
        new_text = self.script_view.toPlainText()
        if new_text != self._engine.script():
            self._engine.set_script(new_text)

    def show_status(self, status: ProviderStatus) -> None:
        print("show status: ", status)
        match status:
            case FailedStatus() as failed:
                self.script_view._linter.lintException(failed.reason, 'underline')
                self._statusbar.setStyleSheet("color: red;")
                self._statusbar.showMessage(f"{type(failed.reason).__name__}: {failed.reason}")
                import traceback
                traceback.print_exc()
                return
            case SucceededStatus():
                self._statusbar.setStyleSheet("color: green")
                self._statusbar.showMessage("Provider succeeded")
                return

    def _handle_engine_change(self, engine_change:EagerEngineChange):
        if engine_change.get('script'):
            if self.script_view.toPlainText() != engine_change['script'].get('new'):
                self.script_view.setPlainText(engine_change['script'].get('new'))

        if status_change:=engine_change.get('provider_status'):
            self.show_status(status_change.get('new'))


class OutputViewer(QWidget):
    def __init__(self, engine: EagerEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._engine = engine
        layout = QVBoxLayout()
        self.setLayout(layout)
        self._display = DisplayWidget()
        layout.addWidget(self._display)
        self._current_node: NodeId|None = None
        self._display.display("No current node selected")
        engine.listen(self._handle_engine_change)

    def setCurrentNode(self, node: NodeId|None) -> None:
        if node == self._current_node:
            return

        previous = self._current_node
        self._current_node = node
        if previous is not None:
            self._engine.remove_effect(previous)

        if node is None:
            self._display.display("No current node selected")
            return

        # try:
        self._engine.effect(node)
        self._engine.evaluate_node(node) #TODO: when adding an effect isnt it supposed to do an initial evaluation? we have to decide this.
        # except Exception as exc:
        #     self._display.display(exc)

    def _handle_engine_change(self, change: EagerEngineChange) -> None:
        node = self._current_node
        if nodes_change:=change.get('nodes'):
            if node in nodes_change.get('removed', []):
                self.setCurrentNode(None)
                return
        
        if node is None:
            return

        statuses = change.get("nodes_status")
        if statuses is None:
            return

        added = statuses.get("added", {})
        status: NodeStatus

        if node in added:
            status = added[node]
        else:
            update = statuses.get("updated", {}).get(node)
            if update is None:
                return
            status = update["new"]

        match status:
            case SucceededStatus(value=value):
                self._display.display(value)
            case FailedStatus(reason=reason):
                self._display.display(reason)
            case RunningStatus():
                self._display.display("Evaluating…")
            case DirtyStatus():
                self._display.display("Waiting for evaluation")



import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, TypeVar, Protocol
import queue
from qtpy.QtCore import QObject, Signal, Slot, Qt


R = TypeVar("R")

# class _EngineWorker(threading.Thread):
#     def __init__(
#         self,
#         script: str,
#         on_change: Callable[[EagerEngineChange], None],
#     ):
#         super().__init__(daemon=False)
#         self._script = script
#         self._on_change = on_change
#         self._tasks = queue.Queue()

#     def run(self):
#         # init
#         engine = EagerEngine(self._script)
#         engine.listen(self._on_change)

#         # process tasks
#         try:
#             while True:
#                 # wait for the next task
#                 task = self._tasks.get()

#                 if task is None:
#                     break

#                 operation, future = task

#                 if not future.set_running_or_notify_cancel():
#                     continue

#                 try:
#                     future.set_result(operation(engine))
#                 except BaseException as exc:
#                     future.set_exception(exc)
#         finally:
#             engine.close()

#     def submit(
#         self, operation: Callable[[EagerEngine], R]
#     ) -> Future[R]:
#         future = Future()
#         self._tasks.put((operation, future))
#         return future

#     def stop(self):
#         self._tasks.put(None)


# class EngineBridge(QObject):
#     changed = Signal(object)
#     _engine_changed = Signal(object)

#     def __init__(self, parent=None):
#         super().__init__(parent)

#         self._graph: ObservableGraph[NodeId] = ObservableGraph()

#         self._engine_changed.connect(
#             self._apply_change,
#             Qt.ConnectionType.QueuedConnection,
#         )

#         self._worker = _EngineWorker(
#             script=script,
#             on_change=self._engine_changed.emit,
#         )
#         self._worker.start()

#     def submit(
#         self, operation: Callable[[EagerEngine], R]
#     ) -> Future[R]:
#         return self._worker.submit(operation)

#     @Slot(object)
#     def _apply_change(self, change: EagerEngineChange):
#         ...

#         self.changed.emit(change)

#     # Read interface
#     def nodes(self):
#         return self._graph.nodes()

#     def links(self):
#         return self._graph.links()

#     # Lifecycle
#     def close(self) -> None:
#         self._worker.stop()
    
# init default engine
def _create_hello_world_engine():
    engine = EagerEngine(dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello_world(name:str, greeting:str="Hello"):
            return f"{greeting}, {name}!"
    """))
    the_name = engine.create_node("the_name")
    the_greeting = engine.create_node("the_greeting")
    hello_world = engine.create_node("hello_world")
    engine.add_link(the_name, hello_world, 'name')
    engine.effect(hello_world)
    return engine

class EngineWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Eager QDAG Editor")
        self._statusbar = self.statusBar() # ensure statusbar
        splitter = QSplitter()

        self.engine = _create_hello_world_engine()

        # model
        self.model = EagerGraphModel(self.engine)
        self.graphselection = GraphSelectionModel(self.model)

        # - script
        self.provider_pane = ProviderView(self.engine)
        splitter.addWidget(self.provider_pane)

        # - operator list
        self.operator_list = QListView()
        self.operator_list.setSizePolicy(
            QSizePolicy.Policy.Minimum, 
            QSizePolicy.Policy.Expanding
        )
        # self.operator_list.setFixedWidth(180)
        self.operator_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.operator_list.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents);
        self.operator_list.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding);
        self.operator_list_model = OperatorListModel(self.engine)
        self.operator_list.setModel(self.operator_list_model)
        splitter.addWidget(self.operator_list)

        # - graph
        self.editor = DirectionalGraphView5()
        self.editor.requestNode.connect(lambda scene_pos, source: 
            self._handle_node_request(scene_pos=scene_pos, source=source)
        )
        self.editor.requestLink.connect(lambda source, outlet, target, inlet:
            self._handle_link_request(source, outlet, target, inlet)
        )
        self.editor.setModel(self.model)
        self.editor.setSelectionModel(self.graphselection)
        splitter.addWidget(self.editor)

        # - inspector
        self.inspector = GraphInspectorView()
        self.inspector.setModel(self.model)
        self.graphselection.currentNodeChanged.connect(lambda current, prev: 
            self.inspector.setCurrentNode(self.model.mapToSource(current)))
        splitter.addWidget(self.inspector)

        # - viewer
        self.viewer = OutputViewer(self.engine)
        splitter.addWidget(self.viewer)
        def refresh_viewer(current, prev):
            nodeid = self.model.mapToSource(current)
            print("Current node changed:", current, nodeid)
            self.viewer.setCurrentNode(nodeid)
        self.graphselection.currentNodeChanged.connect(refresh_viewer)

        # - finalize layout
        splitter.setSizes([300,180, 500, 180, 300])
        self.resize(1800, 650)
        self.setCentralWidget(splitter)
        
        self.setupMenubar()

        # set focus to the graph
        self.editor.setFocus()

        # initial node fitting
        QTimer.singleShot(0, 
            lambda: self.editor.fitNodes(limit_zoom=True)
        )

    def setupMenubar(self) -> None:
        # Bound callbacks and panel actions must belong to the current editor.
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        edit_menu = QMenu("Edit", menubar)
        menubar.addMenu(edit_menu)
        edit_menu.addAction("Delete Nodes", 
            lambda: self.model.removeNodes(self.graphselection.selectedNodes())
        ).setShortcut("Del")
        menubar.addMenu(edit_menu)

    def _handle_node_request(self, *, scene_pos:QPointF|None=None, source:NodeName|None=None) -> None:
        if scene_pos is None:
            viewport_center = QPointF(self.editor.contentsRect().center())
            scene_pos = self.editor.mapToScene(viewport_center)

        dialog = SelectionDialog(self.operator_list_model, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                operator_name = selected_index.data(Qt.ItemDataRole.DisplayRole)
                new_node = self.engine.create_node(operator_name)
                self.editor.setNodePosition(new_node, scene_pos)

        finally:
            dialog.deleteLater()

    def _handle_link_request(
        self, source: NodeName, outlet: OutletName, target: NodeName, inlet: InletName,
    ) -> None:
        success = self.model.addLinks([(source, outlet, target, inlet)])
        if not success:
            self.statusBar().showMessage("Cannot connect link", 5000)
        else:
            self.statusBar().clearMessage()



if __name__ == "__main__":
    app = QApplication([])

    window = EngineWindow()
    window.show()
    app.exec()
