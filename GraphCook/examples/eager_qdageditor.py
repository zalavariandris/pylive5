import builtins
import inspect
from textwrap import dedent
from typing import Callable, Iterable, Any, Protocol, TypedDict, cast

from graphcook.observable_graph import ObservableGraph, GraphChange
from graphcook.eager_engine import OperatorHandle, OperatorSignature
from graphcook.eager_engine import EagerEngine
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

from graphcook.core.base_engine import (
    OperatorHandle
)

from qtpy.QtCore import QPointF, Qt, QAbstractListModel, QSignalBlocker
from qtpy.QtWidgets import QApplication, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QMainWindow, QPlainTextEdit, QSizePolicy, QSpinBox, QSplitter, QVBoxLayout, QWidget
from graphcook.eager_engine import (
    NodeId, EagerEngineChange, DirtyState, RunningState, SucceededState, FailedState,
)

from myqtx.selection_dialog_view import SelectionDialog
from myqtx.widgets.displaywidget import DisplayWidget
from QtScriptEditorAdvanced import ScriptEditAdvanced
from qtpy.QtCore import SignalInstance

# define engine contracts for the view
class InletSignatureProtocol(TypedDict):
    type: Any
    default: Any


class NodeSignatureProtocol(TypedDict):
    __operator__: OperatorSignature


class EngineGraphProtocol(Protocol):
    # read
    def nodes(self) -> Iterable['NodeId']:
        ...

    def attributes(self, node: 'NodeId') -> NodeSignatureProtocol:
        ...

    def in_links(self, node: 'NodeId') -> Iterable[tuple['NodeId', 'NodeId', str]]:
        ...

    def out_links(self, node: 'NodeId') -> Iterable[tuple['NodeId', 'NodeId', str]]:
        ...

    def links(self) -> Iterable[tuple['NodeId', 'NodeId', str]]:
        ...

    # update
    def add_link(self, src: 'NodeId', dst: 'NodeId', inlet: str) -> None:
        ...

    def remove_link(self, source: 'NodeId', target: 'NodeId', inlet: str) -> None: ...
    # # observe
    # def listen(self, callback: callable[[GraphChange], None]) -> None:
    #     ...


class ProviderProtocol(Protocol):
    # read
    def operators(self) -> Iterable['OperatorHandle']:
        ...


class ObservableProtocol(Protocol):
    def listen(
        self, callback: Callable[[EagerEngineChange], None]
    ) -> Callable[[], None]:
        ...


class EagerEngineProtocol(EngineGraphProtocol, ProviderProtocol, ObservableProtocol, Protocol):
    def set(self, node: NodeId, **attributes: object) -> None: ...
    def unset(self, node: NodeId, name: str) -> None: ...
    def script(self) -> str: ...
    def set_script(self, script: str) -> None: ...
    def invalidate(self, *nodes: NodeId) -> None: ...
    def evaluate(self, *nodes: NodeId) -> None: ...
    def effect(self, node: 'NodeId') -> None: ...
    def remove_effect(self, node: 'NodeId') -> None: ...


# implement models
class EagerGraphModel(AbstractDAGModel):
    def __init__(self, engine: EagerEngineProtocol, parent=None):
        super().__init__(parent=parent)
        self._engine = engine

    def mapFromSource(self, node: 'NodeId')->NodeName:
        return node

    def mapToSource(self, node: NodeName) -> 'NodeId':
        return node

    # READ
    def nodes(self) -> Iterable[NodeName]:
        for node in self._engine.nodes():
            yield node

    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                node_signature = self._engine.attributes(node_name)
                match role:
                    case Qt.ItemDataRole.DisplayRole:
                        op:OperatorSignature = node_signature['__operator__']
                        return op['name']
                    
        return None

    def nodeCellCount(self, node: NodeName) -> int:
        return 0

    def nodeCellData(self, node: NodeName, column: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        node_signature = self._engine.attributes(node)
        operator_handle = node_signature['__operator__']

        for inlet in node_signature['__operator__']['inlets']:
            yield inlet

        # Yield inlets that are connected but not defined in the operator signature
        for src, dst, inlet in self._engine.in_links(node):
            if inlet not in (inlet for inlet in node_signature['__operator__']['inlets']):
                yield inlet

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        return inlet

    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        return ['out']

    def outletData(self, node: NodeName, outlet: OutletName, role:int) -> Any:
        return None

    def inLinks(self, target_node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        for src, dst, linked_inlet in self._engine.in_links(target_node):
            if linked_inlet == inlet:
                yield (src, 'out', dst, linked_inlet)

    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        for src, dst, inlet in self._engine.out_links(source_node):
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
    def removeLinks(self, links) -> bool:
        for link in links:
            src, outlet, dst, inlet = link
            source_nodeid = self.mapToSource(src)
            target_nodeid = self.mapToSource(dst)
            inlet_id = str(inlet)
            self._engine.remove_link(source_nodeid, target_nodeid, inlet_id)
        return True


class OperatorListModel(QAbstractListModel):
    def __init__(self, engine: EagerEngineProtocol, parent=None):
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


class ProviderView(QWidget):
    def __init__(self, engine: EagerEngineProtocol, parent=None):
        super().__init__(parent=parent)
        self._engine = engine
        layout = QHBoxLayout()
        self.setLayout(layout)

        self.script_view = ScriptEditAdvanced()
        self.script_view.setPlainText(self._engine.script())
        self.script_view.textChanged.connect(self._handle_editor_text_changed)

        engine.listen(self._handle_engine_change)
        layout.addWidget(self.script_view)
        self.list_view = QListView()
        layout.addWidget(self.list_view)
        self.model = OperatorListModel(self._engine)
        self.list_view.setModel(self.model)
        self.list_view.setSizePolicy(
            QSizePolicy.Policy.Minimum, 
            QSizePolicy.Policy.Expanding
        )
        self.list_view.setFixedWidth(120)

    def _handle_engine_change(self, engine_change:EagerEngineChange):
        if engine_change.script is not None:
            if self.script_view.toPlainText() != engine_change.script.new:
                self.script_view.setPlainText(engine_change.script.new)

    def _handle_editor_text_changed(self) -> None:
        new_text = self.script_view.toPlainText()
        if new_text != self._engine.script():
            try:
                self._engine.set_script(new_text)
            except Exception as exc:
                self.script_view.setToolTip(str(exc))
            else:
                self.script_view.setToolTip("")


class OutputViewer(QWidget):
    def __init__(self, engine: EagerEngineProtocol, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._engine = engine
        layout = QVBoxLayout()
        self.setLayout(layout)
        self._display = DisplayWidget()
        layout.addWidget(self._display)
        self._current_node: NodeId|None = None
        engine.listen(self._handle_engine_change)
        self._display.display("No current node selected")

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

        try:
            self._engine.effect(node)
            self._engine.evaluate(node) #TODO: when adding an effect isnt it supposed to do an initial evaluation? we have to decide this.
        except Exception as exc:
            self._display.display(exc)

    def _handle_engine_change(self, change: EagerEngineChange) -> None:
        node = self._current_node
        if node is None or change.graph is None:
            return
        if node in change.graph.nodes.removed:
            self.setCurrentNode(None)
            return

        attributes = change.graph.attributes.get(node)
        if attributes is None:
            return
        state_change = attributes.changed.get("state")
        if state_change is None:
            return

        match state_change.new:
            case SucceededState(value=value):
                self._display.display(value)
            case FailedState(reason=reason):
                self._display.display(reason)
            case RunningState():
                self._display.display("Evaluating…")
            case DirtyState():
                self._display.display("Waiting for evaluation")


class InspectorView(QFrame):
    def __init__(self, engine: EagerEngineProtocol, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self._engine = engine
        self._current_node: NodeId | None = None
        self._editors: dict[str, QWidget] = {}
        self._connections: list[tuple[SignalInstance, Callable[..., None]]] = []
        self._form = QFormLayout(self)
        engine.listen(self._handle_engine_change)

    def setCurrentNode(self, node: NodeId | None) -> None:
        if node == self._current_node:
            return

        if self._current_node is not None:
            self._clear_form()

        if node is not None:
            # build form
            linked_sources = {
                inlet: source
                for source, _, inlet in self._engine.in_links(node)
            }
            inlets = self._engine.attributes(node)['__operator__']['inlets']
            inputs = self._engine.attributes(node)
            for inlet_key, inlet_signature in inlets.items():
                if inlet_key in linked_sources:
                    source = linked_sources[inlet_key]
                    label = QLabel(inlet_key)
                    editor = QLabel(f"(Linked)")
                    # editor.setReadOnly(True)
                    self._form.addRow(label, editor)
                else:
                    editor = self.createEditor(node, inlet_key)
                    user_property = editor.metaObject().userProperty()
                    if user_property.isValid() and user_property.hasNotifySignal():
                        signal_name = bytes(user_property.notifySignal().name()).decode('utf-8')
                        signal = getattr(editor, signal_name)

                        def handle_change(*args: Any, node: NodeId = node, key: str = inlet_key, widget: QWidget = editor) -> None:
                            # note: this captures closure values for node, key, and widget
                            self._set_engine_data(node, key, widget)

                        signal.connect(handle_change)
                        self._connections.append((signal, handle_change))

                    if inlet_key in inputs:
                        value = inputs[inlet_key]
                        user_property.write(editor, value)

                    elif inlet_signature['default'] is not inspect.Parameter.empty:
                        if isinstance(editor, QLineEdit):
                            editor.setPlaceholderText(inlet_signature['default'])
                    else:
                        pass

                    self._editors[inlet_key] = editor
                    self._form.addRow(QLabel(inlet_key), editor)

        self._current_node = node

    def _clear_form(self) -> None:
        for signal, handler in self._connections:
            signal.disconnect(handler)
        self._connections.clear()
        self._editors.clear()
        while self._form.rowCount():
            self._form.removeRow(0)

    def _handle_engine_change(self, change: EagerEngineChange) -> None:
        node = self._current_node
        if node is None:
            return

        if change.graph:
            if node in change.graph.attributes:
                attributes_change = change.graph.attributes[node]
                for key, value_change in attributes_change.changed.items():
                    if key in self._editors:
                        editor = self._editors[key]
                        self._set_editor_data(node, key, editor)
    
    def _set_editor_data(self, node: NodeId, key: str, widget: QWidget) -> None:
        if key not in self._engine.attributes(node):
            return
        current_value = self._engine.attributes(node)[key]
        metaobject = widget.metaObject()
        if metaobject:
            user_property = metaobject.userProperty()
            if user_property.isValid() and user_property.hasNotifySignal():
                if user_property.read(widget) != current_value:
                    user_property.write(widget, current_value)

    def _set_engine_data(self, node: NodeId, key: str, widget:QWidget) -> None:
        metaobject = widget.metaObject()
        if metaobject is None:
            return
        
        user_property = metaobject.userProperty()
        if not user_property.isValid():
            return
        
        new_value = user_property.read(widget)
        if key not in self._engine.attributes(node):
            # this input is currently unset. set it
            self._engine.set(node, **{key: new_value})
        else:
            # this input is currently set. check ifs value actually changed
            current_value = self._engine.attributes(node)[key]
            if new_value != current_value:
                self._engine.set(node, **{key: new_value})

    def createEditor(self, node: NodeId, inlet: str) -> QWidget:
        attributes = self._engine.attributes(node)
        signature = attributes['__operator__']['inlets'][inlet]
        editor: QWidget
        match signature['type']:
            case builtins.str:
                editor = QLineEdit()
            case builtins.int:
                editor = QSpinBox()
                editor.setRange(-(2**31), 2**31 - 1)
            case _:
                editor = QLabel()

        return editor


class EngineWindow(QMainWindow):
    def __init__(self, engine: EagerEngineProtocol):
        super().__init__()
        self.setWindowTitle("Eager QDAG Editor")
        self._statusbar = self.statusBar() # ensure statusbar
        self.engine = engine

        self.engine.listen(self._handle_engine_change)

        # layout widgets
        self.provider_pane = ProviderView(self.engine)
        self.operator_list = QListView()
        self.editor = DirectionalGraphView5()
        
        self.editor.requestNode.connect(lambda scene_pos, source: 
            self._handle_node_request(scene_pos=scene_pos, source=source)
        )
        self.editor.requestLink.connect(lambda source, outlet, target, inlet:
            self._handle_link_request(source, outlet, target, inlet)
        )
        # self.editor2 = DirectionalGraphView5()
        # self.editor2.requestNode.connect(lambda scene_pos, source:
        #         self._handle_node_request(scene_pos=scene_pos, source=source)
        #     )
        # self.editor2.requestLink.connect(lambda source, outlet, target, inlet:
        #     self._handle_link_request(source, outlet, target, inlet)
        # )

        self.viewer = OutputViewer(self.engine)

        # graph setup
        self.model = EagerGraphModel(self.engine)
        self.graphselection = GraphSelectionModel(self.model)
        def refresh_viewer(current, prev):
            nodeid = self.model.mapToSource(current)
            print("Current node changed:", current, nodeid)
            self.viewer.setCurrentNode(nodeid)

        self.inspector = InspectorView(self.engine)
        def refresh_inspector(current, prev):
            nodeid = self.model.mapToSource(current)
            print("Current node changed:", current, nodeid)
            self.inspector.setCurrentNode(nodeid)
        self.graphselection.currentNodeChanged.connect(refresh_inspector)
        
        self.graphselection.currentNodeChanged.connect(refresh_viewer)

        self.editor.setModel(self.model)
        self.editor.setSelectionModel(self.graphselection)
        splitter = QSplitter()
        splitter.addWidget(self.provider_pane)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.inspector)
        splitter.addWidget(self.viewer)
        splitter.setSizes([500,500,200, 500])
        self.resize(1800, 650)
        self.setCentralWidget(splitter)
        
        self.editor.fitNodes()

        self.operator_list_model = OperatorListModel(self.engine)
        self.operator_list.setModel(self.operator_list_model)

    def _handle_engine_change(self, change: EagerEngineChange):
        self._statusbar.showMessage("Engine changed", 2000)

    def _handle_node_request(self, *, scene_pos:QPointF|None=None, source:NodeName|None=None) -> None:
        if scene_pos is None:
            viewport_center = QPointF(self.editor.contentsRect().center())
            scene_pos = self.editor.mapToScene(viewport_center)

        dialog = SelectionDialog(self.operator_list_model, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                operator_name = selected_index.data(Qt.ItemDataRole.DisplayRole)
                new_node = self.engine.node(operator_name)
                self.editor.setNodePosition(new_node, scene_pos)

        finally:
            dialog.deleteLater()

    def _handle_link_request(
        self, source: NodeName, outlet: OutletName, target: NodeName, inlet: InletName,
    ) -> None:
        try:
            self.engine.add_link(source, target, inlet)
        except ValueError as error:
            self.statusBar().showMessage(f"Cannot connect: {error}", 5000)
        else:
            self.statusBar().clearMessage()


if __name__ == "__main__":
    app = QApplication([])
    engine = EagerEngine(dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello_world(name:str, greeting:str="Hello"):
            return f"{greeting}, {name}!"
    """))
    the_name = engine.node("the_name")
    the_greeting = engine.node("the_greeting")
    hello_world = engine.node("hello_world")
    engine.add_link(the_name, hello_world, 'name')
    engine.effect(hello_world)
    window = EngineWindow(engine)
    window.show()
    app.exec()
