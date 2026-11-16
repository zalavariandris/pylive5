import inspect
from textwrap import dedent
from typing import Callable, Iterable, Any, Protocol, TypedDict

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

from qtpy.QtCore import QPointF, Qt, QAbstractListModel
from qtpy.QtWidgets import QApplication, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QMainWindow, QPlainTextEdit, QSizePolicy, QSpinBox, QSplitter, QVBoxLayout, QWidget
from graphcook.eager_engine import (
    NodeId, EagerEngineChange, DirtyState, RunningState, SucceededState, FailedState,
)

from myqtx.selection_dialog_view import SelectionDialog
from myqtx.widgets.displaywidget import DisplayWidget

# define engine contracts for the view
class InletSignatureProtocol(TypedDict):
    type: Any
    default: Any

class NodeSignatureProtocol(TypedDict):
    operator: OperatorHandle
    inlets: dict[str, InletSignatureProtocol]
    inputs: dict[str, Any]

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
    def script(self) -> str: ...
    def set_script(self, script: str) -> None: ...
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
                        op:OperatorSignature = node_signature['operator']
                        return op['name']
                    
        return None

    def nodeCellCount(self, node: NodeName) -> int:
        return 0

    def nodeCellData(self, node: NodeName, column: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        node_signature = self._engine.attributes(node)
        operator_handle = node_signature['operator']

        for inlet in node_signature['operator']['inlets']:
            yield inlet

        # Yield inlets that are connected but not defined in the operator signature
        for src, dst, inlet in self._engine.in_links(node):
            if inlet not in (inlet for inlet in node_signature['operator']['inlets']):
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

        self.script_view = QPlainTextEdit()
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


from qtpy.QtCore import SignalInstance, Slot

class InspectorView(QFrame):
    def __init__(self, engine: EagerEngineProtocol, parent=None):
        super().__init__(parent=parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self._engine = engine
        self._current_node = None
        layout = QFormLayout()
        self.setLayout(layout)
        engine.listen(self._handle_engine_change)

        self._connections:list[tuple[SignalInstance, Slot]] = []

    def setCurrentNode(self, node: NodeId|None) -> None:
        if node == self._current_node:
            return

        if self._current_node is not None:
            # clear the form layout and disconnect
            while self.layout().count():
                child = self.layout().takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            for signal, handler in self._connections:
                signal.disconnect(handler)
            self._connections.clear()

        if node is not None:
            node_signature = self._engine.attributes(node)
            operator_signature = node_signature['operator']
            inlets = operator_signature['inlets']
            for inlet, inlet_signature in inlets.items():
                label = QLabel(inlet)
                editor = self.createEditor(node, inlet)  # from factory
                
                # Get the user property from any editor widget
                meta_obj = editor.metaObject()
                user_prop = meta_obj.userProperty()
                
                if user_prop.isValid() and user_prop.hasNotifySignal():
                    meta_signal = user_prop.notifySignal()
                    signal_name = bytes(meta_signal.name()).decode("utf-8")
                    signal = getattr(editor, signal_name)

                    def handler(
                        new_value: Any,
                        attr_key: str = inlet,
                        node_id: NodeId = node,
                    ) -> None:
                        self._handle_editor_change(node_id, attr_key, new_value)

                    signal.connect(handler)
                    self._connections.append((signal, handler))
                
                self.layout().addRow(label, editor)

        self._current_node = node

    def _handle_engine_change(self, engine_change:EagerEngineChange):
        # Implement how the inspector should react to engine changes
        print(f"Engine change: {engine_change}")

    def _handle_editor_change(self, node: NodeId, key: str, value: Any) -> None:
        print(f"Editor change - Node: {node}, Key: {key}, Value: {value}")
        self._engine.set(node, key, value)

    def createEditor(self, node: NodeId, inlet: str) -> QWidget:
        node_signature = self._engine.attributes(node)
        operator_signature = node_signature['operator']
        inlet_signature = operator_signature['inlets'][inlet]


        match inlet_signature['type']:
            case str():
                editor = QLineEdit()
                if inlet in node_signature['inputs']:
                    value = node_signature['inputs'][inlet]
                    editor.setText(str(value))
                elif inlet_signature.get('default', inspect.Parameter.empty) != inspect.Parameter.empty:
                    pass
                    # editor.setText(str(inlet_signature['default']))
                else:
                    pass

                return editor
            
            case int():
                editor = QSpinBox()
                if inlet in node_signature['inputs']:
                    value = node_signature['inputs'][inlet]
                    editor.setValue(value)
                elif node_signature['inlets']['inlet']['default'] != inspect.Parameter.empty:
                    pass
                else:
                    pass
                    
                return editor
            
            case _:
                editor = QLabel()
                if inlet in node_signature['inputs']:
                    inlet_signature = node_signature['inputs'][inlet]
                    editor.setText(f"{inlet_signature}")
                elif node_signature['inlets']['inlet']['default'] != inspect.Parameter.empty:
                    editor.setText(f"default: {node_signature['inlets']['inlet']['default']}")
                else:
                    editor.setText("- unset -")

                return editor

        # if inlet not in inputs:
        #     return QLabel("- unset -")
        # else:
        #     value = inputs[inlet]
        #     match value:
        #         case str():
        #             lineedit = QLineEdit()
        #             lineedit.setText(value)
        #             return lineedit
        #         case int():
        #             spinbox = QSpinBox()
        #             spinbox.setValue(value)
        #             return spinbox
        #         case _:
        #             editor = QLineEdit()
        #             editor.setText(str(value))
        #             return editor
        


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
        splitter.setSizes([500,500,500, 500])
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
