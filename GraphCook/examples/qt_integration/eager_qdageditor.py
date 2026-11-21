import builtins
import inspect
from textwrap import dedent
from typing import Callable, Iterable, Any, Protocol, TypedDict, cast


from graphcook.eager_engine import (
    InletSignature,
    OperatorHandle, 
    OperatorSignature, 
    NodeStatus,
    ProviderStatus,
    GraphChange
)

from graphcook.eager_engine import EagerEngine
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

from qtpy.QtCore import QPointF, Qt, QAbstractListModel, QSignalBlocker
from qtpy.QtWidgets import QApplication, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListView, QMainWindow, QPlainTextEdit, QSizePolicy, QSpinBox, QSplitter, QStatusBar, QVBoxLayout, QWidget
from graphcook.eager_engine import (
    NodeId, EagerEngineChange, DirtyStatus, RunningStatus, SucceededStatus, FailedStatus,
)

from myqtx.selection_dialog_view import SelectionDialog
from myqtx.widgets.displaywidget import DisplayWidget
from QtScriptEditorAdvanced import ScriptEditAdvanced
from qtpy.QtCore import SignalInstance


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
    def mapFromSource(self, node: 'NodeId')->NodeName:
        return node

    def mapToSource(self, node: NodeName) -> 'NodeId':
        return node

    def _handle_engine_change(self, engine_change: EagerEngineChange):
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
        operator_signature: OperatorSignature = self._engine.operator_signature(operator_handle)
        
        for inlet in operator_signature.inlets:
            yield inlet

        # Yield inlets that are connected but not defined in the operator signature
        for src, dst, inlet in self._engine.in_links(self.mapToSource(node)):
            if inlet not in operator_signature.inlets.keys():
                yield inlet

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        return inlet

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
    def addLinks(self, links:Iterable[DirectionalLinkId]) -> bool:
        for link in links:
            src, outlet, dst, inlet = link
            source = self.mapToSource(src)
            target = self.mapToSource(dst)
            try:
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
        self.list_view = QListView()
        layout.addWidget(self.list_view, 0, 1)
        self._statusbar = QStatusBar()
        self._statusbar.setSizeGripEnabled(False)
        layout.addWidget(self._statusbar, 1, 0, 1, 2)
        self.model = OperatorListModel(self._engine)
        self.list_view.setModel(self.model)
        self.list_view.setSizePolicy(
            QSizePolicy.Policy.Minimum, 
            QSizePolicy.Policy.Expanding
        )
        self.list_view.setFixedWidth(120)

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


class InspectorView(QFrame):
    def __init__(self, engine: EagerEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self._engine = engine
        self._current_node: NodeId | None = None
        self._editors: dict[str, QWidget] = {}
        self._connections: list[tuple[SignalInstance, Callable[..., None]]] = []
        self._form = QFormLayout(self)
        engine.listen(self._handle_engine_change)

    def setCurrentNode(self, node: NodeId | None) -> None:
        if node == self._current_node:
            return

        self._clear_form()
        self._current_node = node

        if node is None:
            return

        attributes = self._engine.attributes(node)
        signature = self._engine.operator_signature(attributes["__operator__"])
        parameters = signature.inlets if signature is not None else {}

        inputs = {
            name: value
            for name, value in attributes.items()
            if name != "__operator__"
        }
        linked_sources = {
            inlet: source
            for source, _, inlet in self._engine.in_links(node)
        }
        inlet_names = dict.fromkeys((*parameters, *inputs, *linked_sources))

        for name in inlet_names:
            if name in linked_sources:
                self._form.addRow(QLabel(name), QLabel("(Linked)"))
                continue

            editor = self.createEditor(node, name)
            user_property = editor.metaObject().userProperty()

            # Initialize before connecting signals.
            if name in inputs:
                if isinstance(editor, QLabel):
                    editor.setText(str(inputs[name]))
                elif user_property.isValid():
                    user_property.write(editor, inputs[name])
            else:
                parameter = parameters.get(name)
                if (
                    isinstance(editor, QLineEdit)
                    and parameter is not None
                    and parameter.default is not inspect.Parameter.empty
                ):
                    editor.setPlaceholderText(str(parameter.default))

            self._editors[name] = editor
            self._form.addRow(QLabel(name), editor)

            if not user_property.isValid() or not user_property.hasNotifySignal():
                continue

            signal_name = bytes(user_property.notifySignal().name()).decode()
            signal = getattr(editor, signal_name)

            def handle_change(
                *args: Any,
                node: NodeId = node,
                key: str = name,
                widget: QWidget = editor,
            ) -> None:
                self.setEngineData(node, key, widget)

            signal.connect(handle_change)
            self._connections.append((signal, handle_change))

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

        nodes_change = change.get("nodes", {})
        if node in nodes_change.get("removed", {}):
            self.setCurrentNode(None)
            return

        attributes_change = nodes_change.get("updated", {}).get(node)
        if attributes_change is None:
            return

        changed_keys = (
            set(attributes_change.get("added", {}))
            | set(attributes_change.get("removed", {}))
            | set(attributes_change.get("updated", {}))
        )
        for key in changed_keys:
            if key in self._editors:
                self.setEditorData(node, key, self._editors[key])

    def setEditorData(self, node: NodeId, key: str, widget: QWidget) -> None:
        attributes = self._engine.attributes(node)
        with QSignalBlocker(widget):
            if key not in attributes:
                if isinstance(widget, (QLineEdit, QSpinBox, QLabel)):
                    widget.clear()
                return
            current_value = attributes[key]
            meta_object = widget.metaObject()
            if meta_object is None:
                user_property = meta_object.userProperty()
                if user_property.isValid() and user_property.hasNotifySignal():
                    if user_property.read(widget) != current_value:
                        user_property.write(widget, current_value)

    def setEngineData(self, node: NodeId, key: str, widget:QWidget) -> None:
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
        signature = self._engine.operator_signature(attributes["__operator__"])
        parameter = signature.inlets.get(inlet) if signature is not None else None
        

        inlet_type = (
            parameter.type
            if parameter is not None
            else inspect.Parameter.empty
        )

        # Infer a type only when the operator does not specify one.
        if inlet_type is inspect.Parameter.empty or inlet_type is Any:
            if inlet in attributes:
                inlet_type = type(attributes[inlet])

        if inlet_type is str:
            return QLineEdit()

        if inlet_type is int:
            editor = QSpinBox()
            editor.setRange(-(2**31), 2**31 - 1)
            editor.clear()
            return editor

        return QLabel()


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

        self.engine = _create_hello_world_engine()

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
