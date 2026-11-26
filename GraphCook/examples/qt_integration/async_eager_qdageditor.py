import asyncio
from copy import copy
from inspect import Parameter
from textwrap import dedent
from typing import Iterable, Any, cast
from typing import Any, Callable, Iterable, Mapping
from threading import Thread
from queue import Queue
import concurrent.futures
import logging

from graphcook.core.changes import ObservableValue
from qasync import QEventLoop, asyncSlot

from qtpy.QtCore import QAbstractListModel, QModelIndex, QPointF, Qt, QObject
from qtpy.QtCore import QStringListModel
from qtpy.QtCore import Qt
from qtpy.QtCore import Signal, Slot
from qtpy.QtWidgets import QAbstractScrollArea, QDialog, QListView, QSizePolicy, QSplitter, QWidget
from qtpy.QtWidgets import QDockWidget, QMainWindow, QSplitter
from qtpy.QtWidgets import QPlainTextEdit

from qdageditor5.core.item_data_roles import NodeDataRole
from qdageditor5.core.inspector_roles import InspectorRoles
from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel, 
    NodeName,
    CellIdx,
    InletName,
    OutletName,
    DirectionalLinkId
)

from qdageditor5.views.node_inspector_view import NodeInspectorView
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5

from myqtx.widgets.displaywidget import DisplayWidget
from myqtx.selection_dialog_view import SelectionDialog
from QtScriptEditorAdvanced import ScriptEditAdvanced

from graphcook.observable_graph import GraphChange, ObservableGraph
from graphcook.core.cache import MemoryCache
from graphcook.core.graph import Graph, Link
from graphcook.core.execution_status import (
    ExecutionStatus, 
    DirtyStatus, 
    RunningStatus, 
    SucceededStatus, 
    FailedStatus
)
from graphcook.eager_observable_engine import (
    OperatorHandle,
    NodeId,
    OPERATOR_ATTRIBUTE,
    _execute_provider, 
    _execute_graph,
    NodeStatus,
    ProviderStatus,
    NodeExecutionError,
    ExecutionResult
)
from graphcook.eager_observable_engine import OperatorSignature
from myutils.source_diff import ast_functions_diff, FunctionsDiff

worker_logger = logging.getLogger("graphcook.worker")
from myutils.source_diff import ast_functions_diff, FunctionsDiff
from qtpy.QtGui import QContextMenuEvent

class LogWidget(QPlainTextEdit):
    message_received = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.message_received.connect(
            self.append_message,
            Qt.ConnectionType.QueuedConnection,
        )

    @Slot(str)
    def append_message(self, message: str) -> None:
        self.appendPlainText(message)

    def contextMenuEvent(self, event: QContextMenuEvent | None) -> None:
        if event is None:
            return

        menu = self.createStandardContextMenu()
        if menu is None:
            return

        menu.addSeparator()
        menu.addAction("Clear", self.clear)
        menu.exec(event.globalPos())
        menu.deleteLater()


class QtLogHandler(logging.Handler):
    def __init__(self, send_message: Callable[[str], None]) -> None:
        super().__init__()
        self._send_message = send_message

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._send_message(self.format(record))
        except Exception:
            self.handleError(record)

from concurrent.futures import Future
class Worker(Thread):
    def __init__(self):
        super().__init__()
        self._tasks = Queue()
        self._resolved_functions: dict[OperatorHandle, Callable|None] = {}
        self._source: str = ""
        self._signatures: dict[OperatorHandle, OperatorSignature] = {}
        self.cache = MemoryCache[NodeId, Any]()

    def run(self) -> None:
        while True:
            task = self._tasks.get()

            if task is None:
                break

            message, future, payload = task

            if not future.set_running_or_notify_cancel():
                continue

            self.process(message, future, payload)

    async def submit(self, message: str, payload: Any) -> Any:
        
        future = Future()
        self._tasks.put((message, future, payload))
        return await asyncio.wrap_future(future)

    def process(self, 
        message: str, 
        future: concurrent.futures.Future, 
        payload: Any
    ) -> None:
        worker_logger.info(f"{message}...")
        match message:
            case "execute_script":
                assert isinstance(payload, str)
                new_script: str = payload
                try:
                    ast_diff: FunctionsDiff = ast_functions_diff(self._source, new_script)
                    operators: dict[OperatorHandle, Callable] = _execute_provider(new_script)
                    signatures: dict[OperatorHandle, OperatorSignature] = {}
                    for handle, func in operators.items():
                        previous = self._signatures.get(handle)
                        revision = previous.revision if previous is not None else 0
                        if previous is not None and handle.name in ast_diff.changed:
                            revision += 1
                        signatures[handle] = OperatorSignature.from_func(func, revision=revision)
                except BaseException as exc:
                    worker_logger.exception("Script execution failed")
                    future.set_exception(exc)
                else:
                    worker_logger.info("Loaded %d operators", len(operators))
                    # Only successful submissions become the next comparison baseline.
                    self._source = new_script
                    self._resolved_functions = operators
                    self._signatures = signatures
                    future.set_result(signatures)

            case 'execute_graph':
                G = cast(Graph[NodeId], payload)
                def callback(node_id: NodeId, status: NodeStatus) -> None:
                    worker_logger.info("Node %s status: %s", node_id, status)
                
                try:
                    results = _execute_graph(
                        G, 
                        self._resolved_functions, 
                        cache=self.cache, 
                        callback=callback
                    )
                except Exception as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(results)

            case "invalidate":
                nodes = payload
                for node in nodes:
                    # Invalidate logic here, e.g., mark nodes as dirty and clear cache
                    if node in self.cache:
                        self.cache.remove(node)
                future.set_result(None)

        if exc:=future.exception():
            worker_logger.error(f"{message} failed with exception: {exc}")
        elif future.done():
            worker_logger.info(f"{message} succeeded with result: {future.result()}")
        else:
            worker_logger.info(f"{message} {future}")

    def close(self):
        # signal the thread to exit
        self._tasks.put(None)
        self.join()

class Executor:
    def __init__(self):
        # internal state?
        self.operators: dict[OperatorHandle, Callable] = dict()
        self.signatures: dict[OperatorHandle, OperatorSignature] = dict()
        self.cache = MemoryCache[NodeId, Any]()

        # computed
        self.node_statuses = dict()

    def execute_script(self, script: str) -> dict[OperatorHandle, tuple[Callable, int]]:
        ...

    def execute_subgraph(self, subgraph: Graph[NodeId]) -> dict[NodeId, NodeStatus]:
        ...

from graphcook.core.graph import descendants
class Invalidator:
    def __init__(self, graph: ObservableGraph[NodeId]) -> None:
        self.graph = graph
        self._subscribers: list[Callable[[list[NodeId]], None]] = []
        self._unsubscribe_graph: Callable[[], None] | None = graph.listen(self._handle_graph_change)

    def close(self) -> None:
        """Stop observing the graph. Safe to call more than once."""
        if self._unsubscribe_graph is not None:
            self._unsubscribe_graph()
            self._unsubscribe_graph = None

    def _handle_graph_change(self, change: GraphChange) -> None:
        nodes_to_invalidate: set[NodeId] = set()
        if nodes_change:=change.get("nodes"):
            for node_id in nodes_change.get("added", []):
                nodes_to_invalidate.add(node_id)

            for node_id in nodes_change.get("removed", []):
                ...

            for node_id in nodes_change.get("updated", []):
                nodes_to_invalidate.add(node_id)
                for dep in descendants(self.graph, node_id):
                    nodes_to_invalidate.add(dep)

        if links_change:=change.get("links"):
            for link in links_change.get("added", []):
                src, dst, inlet = link
                nodes_to_invalidate.add(dst)
                for dep in descendants(self.graph, dst):
                    nodes_to_invalidate.add(dep)

            for link in links_change.get("removed", []):
                src, dst, inlet = link
                if dst not in self.graph.nodes():
                    continue
                nodes_to_invalidate.add(dst)
                for dep in descendants(self.graph, dst):
                    nodes_to_invalidate.add(dep)

        if nodes_to_invalidate:
            self._notify_subscribers(nodes_to_invalidate)

    def _notify_subscribers(self, nodes: set[NodeId]) -> None:
        for subscriber in tuple(self._subscribers):
            subscriber(list(nodes))

    def invalidate(self, *nodes: NodeId) -> None:
        """manually trigger invalidation for the given nodes and their descendants"""
        nodes_to_invalidate: set[NodeId] = set(nodes)
        for node in nodes:
            for dep in descendants(self.graph, node):
                nodes_to_invalidate.add(dep)

        if nodes_to_invalidate:
            self._notify_subscribers(nodes_to_invalidate)

    def listen(self, callback: Callable[[Iterable[NodeId]], None]) -> Callable[[], None]:
        """listen for nodes invalidated"""
        self._subscribers.append(callback)
        def unsubscribe():
            self._subscribers.remove(callback)
        return unsubscribe


class Engine:
    def __init__(self):
        self.script:ObservableValue[str] = ObservableValue("")
        self.graph:ObservableGraph[NodeId] = ObservableGraph()
        self.invalidator: Invalidator = Invalidator(self.graph)
        self.invalidator.listen(lambda nodes: self._handle_invalidation(nodes))
        self.executor: Executor = Executor()
        self._operators: dict[OperatorHandle, object] = dict()
        self._status: dict[NodeId, Any] = dict() # consider using an ObservableDict?

    def _handle_script_change(self, new_script: str) -> None:
        """ Handle script changes here """
        # - notify connected clients
        ...

        # - execute operators and update relevant nodes with the changed oprators
        ...

    def _handle_invalidation(self, nodes: Iterable[NodeId]) -> None:
        """ Handle invalidated nodes here """
        # - notify connected clients about the invalidated nodes
        ...

        # - execute nodes that have been invalidated and update their state accordingly using the executor
        ...

        # notify clients about the new status
        self._handle_status_change({node: self._status.get(node) for node in nodes})

    def _handle_status_change(self, changes: dict[NodeId, NodeStatus]) -> None:
        """ Handle state changes here """
        # notify connected clients about the state changes
        ...

class EngineClient(Thread):
    def __init__(self):
        super().__init__()
        self._tasks: Queue[tuple[Future, Callable[[Engine], Any]]] = Queue()

    def run(self):
        engine = Engine()
        while True:
            future, task = self._tasks.get()
            if task is None:
                break
            try:
                response = task(engine)
            except Exception as exc:
                worker_logger.error("Task failed with exception: %s", exc)
                future.set_exception(exc)
            else:
                future.set_result(response)

    def submit(self, process: Callable[[Engine], Any])->Future:
        future = Future()
        self._tasks.put((future, process))
        return future

    def request_get_script(self) -> Future[str]:
        return self.submit(lambda server: server.script.get())

    def request_execute_script(self) -> Future[None]:
        return self.submit(lambda server: server.executor.execute_script(server.script.get()))

    def request_get_graph(self) -> Future[Graph[NodeId]]:
        def map_graph_to_view(engine_graph: Graph[NodeId]) -> Graph[NodeId]:
            view_graph:Graph[NodeId] = Graph()
            for node_id in engine_graph.nodes():
                attributes = engine_graph.attributes(node_id)
                view_attributes = dict(**attributes)
                func = attributes[OPERATOR_ATTRIBUTE]
                assert callable(func)
                view_attributes[OPERATOR_ATTRIBUTE] = OperatorSignature.from_func(func, 0)
                view_graph.add_node(node_id, **attributes)
            return view_graph

        return self.submit(lambda server: map_graph_to_view(server.graph))

    def request_execute_graph(self, subgraph: Graph[NodeId]) -> Future[dict[NodeId, NodeStatus]]:
        return self.submit(lambda server: server.executor.execute_subgraph(subgraph))

##########
# MODELS #
##########

class AsyncEagerGraphModel(AbstractDAGModel):
    def __init__(
        self,
        graph: ObservableGraph[NodeId],
        operator_signature: Callable[[OperatorHandle], OperatorSignature | None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._config_graph = graph
        self._operator_signature = operator_signature
        self._node_status: dict[NodeName, NodeStatus] = dict()

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

    # READ
    def nodes(self) -> Iterable[NodeName]:
        for node in self._config_graph.nodes():
            yield node

    def addNode(self, operator: OperatorHandle | None = None) -> NodeName:
        from unique_names_generator import get_random_name
        node_id = NodeId(get_random_name())
        self._beginAddNodes([node_id])
        self._config_graph.add_node(node_id, 
            __operator__ = operator
        )
        self._endAddNodes()
        return node_id

    def operatorSignature(self, node: NodeName) -> OperatorSignature | None:
        """Resolve a node's handle against the current operator registry."""
        node_data = self._config_graph.attributes(self.mapToSource(node))
        handle = node_data.get(OPERATOR_ATTRIBUTE)
        if handle is None:
            return None
        assert isinstance(handle, OperatorHandle)
        return self._operator_signature(handle)

    def refreshOperatorSignatures(self, operators: Iterable[OperatorHandle]) -> None:
        """Refresh ports and inspector editors after the registry changes."""
        changed = set(operators)
        for node in self.nodes():
            node_data = self._config_graph.attributes(self.mapToSource(node))
            if node_data.get(OPERATOR_ATTRIBUTE) in changed:
                self._beginResetInlets(node)
                self._endResetInlets()

    def nodeHeaderData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return f"{node_name}"
        return None

    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node_data: Mapping[str, Any] = self._config_graph.attributes(self.mapToSource(node_name))
        node_status = self._node_status.get(self.mapToSource(node_name), None)
        match role:
            case Qt.ItemDataRole.DisplayRole:
                operator_handle = node_data.get(OPERATOR_ATTRIBUTE)
                return operator_handle.name if operator_handle is not None else '-no op-'

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

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        node_id = self.mapToSource(node)
        node_data = self._config_graph.attributes(node_id)
        signature = self.operatorSignature(node)
        parameters = signature.inlets if signature is not None else {}
        inputs = [name for name in node_data if not name.startswith('_')]
        linked_inlets = [link.inlet for link in self._config_graph.in_links(node_id)]
        yield from dict.fromkeys((*parameters, *inputs, *linked_inlets))

    def inletHeaderData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return str(inlet)
            case _:
                return None

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        node_data: Mapping[str, Any] = self._config_graph.attributes(self.mapToSource(node))
        signature = self.operatorSignature(node)
        inlet_signature = signature.inlets.get(inlet) if signature is not None else None
        match role:
            case Qt.ItemDataRole.DisplayRole:
                if inlet in node_data:
                    return str(node_data[inlet])
                else:
                    return self.EMPTY

            case Qt.ItemDataRole.EditRole:
                # Preserve explicitly assigned values, including None.
                if inlet in node_data:
                    return node_data[inlet]

                if inlet_signature is None:
                    return self.EMPTY

                default = inlet_signature.default
                if default is not Parameter.empty:
                    return default

                annotation = inlet_signature.annotation
                if annotation in (str, int, float, bool):
                    return annotation()

                return self.EMPTY

            case InspectorRoles.DataTypeRole:
                return inlet_signature.annotation if inlet_signature is not None else None

            case InspectorRoles.DefaultValueRole:
                return inlet_signature.default if inlet_signature is not None else Parameter.empty
            
            case _:
                return None

    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        return ['out']

    def outletData(self, node: NodeName, outlet: OutletName, role:int) -> Any:
        return None

    def inLinks(self, target_node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._config_graph.in_links(target_node):
            if key == inlet:
                yield (src, 'out', dst, key)

    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._config_graph.out_links(source_node):
            if outlet == 'out':
                yield (src, 'out', dst, key)

    def links(self) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._config_graph.links():
            yield (src, 'out', dst, key)

    # update
    def removeNodes(self, nodes: Iterable[NodeName]) -> bool:
        self._beginRemoveNodes(nodes)
        for node in nodes:
            node_id = self.mapToSource(node)
            self._config_graph.remove_node(node_id)
        self._endRemoveNodes()
        return True

    def addLinks(self, links:Iterable[DirectionalLinkId]) -> bool:
        self._beginAddLinks(links)
        for src, out_, dst, in_ in links:
            src_id = self.mapToSource(src)
            dst_id, inlet = self.mapToSource(dst, in_)
            self._config_graph.add_link(src_id, dst_id, inlet)
        self._endAddLinks()
        return True

    def removeLinks(self, links) -> bool:
        self._beginRemoveLinks(links)
        for link in links:
            src, outlet, dst, inlet = link
            src_id = self.mapToSource(src)
            dst_id, inlet = self.mapToSource(dst, inlet)
            self._config_graph.remove_edge(src_id, dst_id, inlet)
        self._endRemoveLinks()
        return True

    def setInletData(self, node: NodeName, inlet: InletName, value: Any, role: int) -> bool:
        if role == Qt.ItemDataRole.EditRole:
            if value is self.EMPTY:
                node_id, inlet_id = self.mapToSource(node, inlet)
                self._config_graph.unset(node_id, inlet_id)
                self.inletDataChanged.emit(node, tuple([inlet]), [])
                return True
            else:
                node_id, inlet_id = self.mapToSource(node, inlet)
                self._config_graph.set(node_id, inlet_id, value)
                self.inletDataChanged.emit(node, tuple([inlet]), [])
                return True

        return False

    def setNodeData(self, node: NodeName, value: Any, role: int=Qt.ItemDataRole.EditRole) -> bool:
        return False

    def updateNodeStatus(self, node: NodeName, status: NodeStatus) -> bool:
        self._node_status[node] = status
        self.nodesDataChanged.emit((node,), [])
        return True

    def closeEvent(self, event):
        self._unsubscribe()
        super().closeEvent(event)

from dataclasses import dataclass

@dataclass
class _OperatorShadow:
    handle: OperatorHandle
    signature: OperatorSignature

class OperatorsModel(QAbstractListModel):
    def __init__(self, client: EngineClient, parent:QObject|None=None):
        super().__init__(parent=parent)
        self._client = client
        self._operators: list[_OperatorShadow] = []

        client.listen(self._handle_client_changes)

    def _handle_client_changes(self, changes):
        if operator_changes:=changes.get("operators", dict):
            ...
        
    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._operators)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            operators = self._client.get_operators()
            if 0 <= index.row() < len(operators):
                return operators[index.row()]
        return None

class Window(QMainWindow):
    def __init__(self):
        super().__init__()

        self._client = EngineClient()

        self._config_graph = ObservableGraph[NodeId]()
        self._operator_signatures: dict[OperatorHandle, OperatorSignature] = {}

        # MODELS
        self.operator_list_model = QStringListModel([])
        self.model = AsyncEagerGraphModel(self._config_graph, self._operator_signatures)

        # 
        self.selection = GraphSelectionModel(self.model)

        splitter = QSplitter()
        self.setCentralWidget(splitter)
        self.script_editor = ScriptEditAdvanced()
        script_document = self.script_editor.document()
        assert script_document is not None
        script_document.setPlainText(dedent("""\
        def the_name():
            return 'Mása'
        def the_greeting():
            return 'Hey'

        def hello_world(name:str, greeting:str="Hello"):
            return f"{greeting}, {name}!"
        """))
        
        script_document.contentsChanged.connect(self.submit_execute_script)
        splitter.addWidget(self.script_editor)
        self.operator_list_view = QListView()
        self.operator_list_view.setSizePolicy(
            QSizePolicy.Policy.Minimum, 
            QSizePolicy.Policy.Expanding
        )
        # self.operator_list.setFixedWidth(180)
        self.operator_list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.operator_list_view.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents);
        self.operator_list_view.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding);
        self.operator_list_view.setModel(self.operator_list_model)
        splitter.addWidget(self.operator_list_view)
        self.editor1 = DirectionalGraphView5()
        splitter.addWidget(self.editor1)

        self.inspector = NodeInspectorView()
        dockwidget = QDockWidget()
        dockwidget.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dockwidget)

        self._output_viewer = DisplayWidget()
        splitter.addWidget(self._output_viewer)

        self.editor1.setModel(self.model)
        self.editor1.setSelectionModel(self.selection)
        self.editor1.requestNode.connect(lambda pos, source, editor=self.editor1: 
            self.new_node(pos, source, editor))
        self.editor1.requestLink.connect(lambda src, outlet, dst, inlet: 
            self.model.addLinks([(src, outlet, dst, inlet)]))
        self.inspector.setModel(self.model)
        self.selection.currentNodeChanged.connect(
            lambda current, previous: self.inspector.setCurrentNode(current))

        self.worker = Worker()

        self.log_widget = LogWidget()
        log_dock = QDockWidget("Worker logs", self)
        log_dock.setWidget(self.log_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, log_dock)
        
        self.log_handler = QtLogHandler(self.log_widget.message_received.emit)
        self.log_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        worker_logger.setLevel(logging.INFO)
        worker_logger.addHandler(self.log_handler)
        self.worker.start()

        def on_config_graph_changed(change:GraphChange):
            if 'nodes' in change:
                event_nodes = change['nodes']
                for node_id, value in event_nodes.get('updated', dict()).items():
                    self.submit_invalidate_node(node_id)

            worker_logger.info("Config graph changed: %s", change)
            self.submit_execute_graph()

        self._config_graph.listen(on_config_graph_changed)
        self.selection.currentNodeChanged.connect(self.submit_execute_graph)

    def operator_signature(self, handle: OperatorHandle) -> OperatorSignature | None:
        return self._operator_signatures.get(handle)

    @asyncSlot()
    async def submit_invalidate_node(self, node_id: NodeId) -> None:
        # nodes_invalidated = await self.worker.invalidate_node(node_id)
        await self.worker.submit('invalidate_node', [node_id])

    @asyncSlot()
    async def submit_execute_script(self) -> None:
        document = self.script_editor.document()
        if document is None:
            return

        script_text = document.toPlainText()

        try:
            new_signatures:dict[OperatorHandle, OperatorSignature] = await self.worker.submit('execute_script', script_text)
        except Exception as exc:
            return

        # Ignore this result if the script changed while we were waiting.
        if document.toPlainText() != script_text:
            return

        self.operator_list_model.setStringList(
            [handle.name for handle in new_signatures.keys()]
        )

        # collect dirty nodes affected by operator changes
        dirty_operators: set[OperatorHandle] = set()
        for operator_handle, signature in new_signatures.items():
            if self._operator_signatures.get(operator_handle)!=signature:
                dirty_operators.add(operator_handle)

        for operator_handle, signature in self._operator_signatures.items():
            if operator_handle not in new_signatures:
                dirty_operators.add(operator_handle)

        self._operator_signatures = new_signatures
        self.model.refreshOperatorSignatures(dirty_operators)
        # find dirty nodes affected by operator change
        worker_logger.info("Dirty operators: %s", dirty_operators)
        dirty_nodes: set[NodeId] = set()
        for node_id in self._config_graph.nodes():
            operator_handle = self._config_graph.attributes(node_id).get(OPERATOR_ATTRIBUTE)
            if operator_handle in dirty_operators:
                dirty_nodes.add(node_id)

        # update the view node statuses
        worker_logger.info("Dirty nodes: %s", dirty_nodes)
        for node_id in dirty_nodes:
            self.model.updateNodeStatus(
                self.model.mapFromSource(node_id),
                DirtyStatus(),
            )

    @asyncSlot()
    async def submit_execute_graph(self) -> None:
        # get relevant subgraph from the editor
        current_name = self.selection.currentNode()
        current_node_id = self.model.mapToSource(current_name)
        G = self.model._config_graph
        # prepare subgraph
        resolved_subgraph = Graph[NodeId]()
        for node in G.nodes():
            operator_handle = G.attributes(node)[OPERATOR_ATTRIBUTE]
            assert isinstance(operator_handle, OperatorHandle)
            resolved_subgraph.add_node(
                node,
                __operator__=operator_handle,
                kwargs={
                    k: v
                    for k, v in G.attributes(node).items()
                    if k != "__operator__"
                }
            )
        for node in G.nodes():
            for link in G.in_links(node):
                resolved_subgraph.add_link(link.source, link.target, link.inlet)

        # send the subgraph to the worker for execution
        try:
            # outputs = await self.worker.execute_graph(resolved_subgraph)
            outputs = await self.worker.submit('execute_graph', resolved_subgraph)
        except NodeExecutionError as exc:
            node_name = self.model.mapFromSource(exc.node)
            if node_name in self.model.nodes():
                self.model.updateNodeStatus(
                    node_name,
                    FailedStatus(reason=exc.reason),
                )
            if self.selection.currentNode() == node_name:
                self._output_viewer.display(exc.reason)
        else:
            for node_id, output in outputs.items():
                node_name = self.model.mapFromSource(node_id)
                if node_name in self.model.nodes():
                    self.model.updateNodeStatus(
                        node_name,
                        SucceededStatus(value=output),
                    )
                node_name = self.model.mapFromSource(node_id)
                if self.selection.currentNode() == node_name:
                    self._output_viewer.display(output)

    def new_node(self, scene_pos, source, editor):
        if scene_pos is None:
            viewport_center = QPointF(editor.contentsRect().center())
            scene_pos = editor.mapToScene(viewport_center)

        dialog = SelectionDialog(self.operator_list_model, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                operator_name = selected_index.data(Qt.ItemDataRole.EditRole)
                operator_handle = OperatorHandle(operator_name)
                new_node = self.model.addNode(operator_handle)
                editor.setNodePosition(new_node, scene_pos)

        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    import sys
    from qtpy.QtWidgets import QApplication

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    editor = Window()
    editor.show()
    loop.call_soon(editor.submit_execute_script)

    with loop:
        try:
            loop.run_forever()
        finally:
            editor.worker.close()
            worker_logger.removeHandler(editor.log_handler)
            editor.log_handler.close()
