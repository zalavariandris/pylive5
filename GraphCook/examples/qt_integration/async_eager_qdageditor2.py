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

from qtpy.QtCore import QAbstractListModel, QModelIndex, QPointF, QTimer, Qt, QObject
from qtpy.QtCore import QStringListModel
from qtpy.QtCore import Qt
from qtpy.QtCore import Signal, Slot
from qtpy.QtWidgets import QAbstractScrollArea, QDialog, QHBoxLayout, QListView, QSizePolicy, QSplitter, QVBoxLayout, QWidget
from qtpy.QtWidgets import QDockWidget, QMainWindow, QSplitter
from qtpy.QtWidgets import QPlainTextEdit

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
        self._tasks: Queue[
            tuple[Future, Callable[[Engine], Any] | None]
        ] = Queue()
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
        self._source: str = "" # hold the current script to compare against new submissions
        self.operators: dict[OperatorHandle, Callable] = dict()
        self.signatures: dict[OperatorHandle, OperatorSignature] = dict()
        self.cache = MemoryCache[NodeId, Any]()

        # computed
        self.node_statuses = dict()

    def execute_script(
        self, script: str
    ) -> dict[OperatorHandle, OperatorSignature]:
        try:
            operators = _execute_provider(script)
            changes = ast_functions_diff(self._source, script)
            signatures: dict[OperatorHandle, OperatorSignature] = {}

            for handle, func in operators.items():
                previous = self.signatures.get(handle)
                revision = previous.revision if previous is not None else 0

                if previous is not None and handle.name in changes.changed:
                    revision += 1

                signatures[handle] = OperatorSignature.from_func(
                    func, revision=revision
                )
        except Exception:
            self.operators.clear()
            self.signatures.clear()
            raise

        self._source = script
        self.operators = operators
        self.signatures = signatures

        return {
            handle: (func, signatures[handle].revision)
            for handle, func in operators.items()
        }

    def execute_subgraph(
        self,
        subgraph: Graph[NodeId],
    ) -> dict[NodeId, NodeStatus]:
        statuses: dict[NodeId, NodeStatus] = {
            node: DirtyStatus() for node in subgraph.nodes()
        }

        # Recompute each manual run until invalidation is connected.
        self.cache.clear()

        def record_status(node: NodeId, status: NodeStatus) -> None:
            statuses[node] = status

        try:
            _execute_graph(
                subgraph,
                self.operators,
                cache=self.cache,
                callback=record_status,
            )
        except NodeExecutionError:
            # The callback already recorded FailedStatus.
            # Nodes not reached remain DirtyStatus.
            pass

        self.node_statuses = statuses
        return statuses


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

    def operator_handle(self, node: NodeId) -> OperatorHandle|None:
        attributes = self.graph.attributes(node)
        handle: OperatorHandle|None = attributes.get('operator', None)
        return handle

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
        self._listeners: list[Callable[[Any], None]] = []

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

    def request_get_signatures(self) -> Future[dict[OperatorHandle, OperatorSignature]]:
        return self.submit(lambda server: {
            handle: OperatorSignature.from_func(func, revision=revision)
            for handle, (func, revision) in server.executor.get_signatures().items()
        })

    def request_get_script(self) -> Future[str]:
        return self.submit(lambda server: server.script.get())

    def request_set_script(self, new_script: str) -> Future[None]:
        return self.submit(lambda server: server.script.set(new_script))

    def request_execute_script(
        self,
    ) -> Future[dict[OperatorHandle, OperatorSignature]]:
        def execute(
            engine: Engine,
        ) -> dict[OperatorHandle, OperatorSignature]:
            operators = engine.executor.execute_script(engine.script.get())
            return {
                handle: OperatorSignature.from_func(func, revision=revision)
                for handle, (func, revision) in operators.items()
            }

        return self.submit(execute)

    def request_get_graph(self) -> Future[Graph[NodeId]]:
        def map_graph_to_view(engine_graph: Graph[NodeId]) -> Graph[NodeId]:
            view_graph:Graph[NodeId] = Graph()
            for node_id in engine_graph.nodes():
                attributes = engine_graph.attributes(node_id)
                view_attributes = dict(**attributes)
                func = attributes[OPERATOR_ATTRIBUTE]
                assert callable(func)
                view_attributes[OPERATOR_ATTRIBUTE] = OperatorSignature.from_func(func, 0)
                view_graph.add_node(node_id, **view_attributes)
            return view_graph

        return self.submit(lambda server: map_graph_to_view(server.graph))

    def request_execute_graph(self, subgraph: Graph[NodeId]) -> Future[dict[NodeId, NodeStatus]]:
        return self.submit(lambda server: server.executor.execute_subgraph(subgraph))

    def listen(self, callback: Callable[[Any], None]) -> Callable[[Any], None]:
        self._listeners.append(callback)
        def unsubscribe(callback: Callable[[Any], None]) -> None:
            self._listeners.remove(callback)
        return unsubscribe

    def _notify(self, result: Any) -> None:
        for listener in self._listeners:
            listener(result)

    def close(self) -> None:
        self._tasks.put((Future(), None))
        self.join()

##########
# MODELS #
##########
from typing import TypedDict

class _NodeShadow(TypedDict):
    operator_handle: OperatorHandle
    operator: OperatorSignature
    inputs: dict[InletName, object|None]
    status: NodeStatus


class AsyncEagerGraphModel(AbstractDAGModel):
    def __init__(
        self,
        client: EngineClient,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._local_graph: Graph[NodeName] = Graph() # with OperatorHandles and Signatures
        self._client = client
        # sync the observable graph with the engine client


        # def _sync_local(change: EngineChange) -> None:
        #     # handle changes from the engine client and update the observable graph
        #     pass

        # client.listen(_sync_local)

    # # Adapter
    # def mapFromSource(self, node: 'NodeId', inlet: InletName|None = None)->NodeName|tuple[NodeName, InletName]:
    #     # note: right now mapping is straightforward. if the DAGModel will use 
    #     # its own datastructure to represent nodes and inlets, this will become a bit more
    #     # complex
    #     if inlet is not None:
    #         return node, inlet
    #     else:
    #         return node

    # def mapToSource(self, node: NodeName, inlet: InletName|None=None) -> 'NodeId|tuple[NodeId, str]':
    #     # note: right now mapping is straightforward. if the DAGModel will use 
    #     # its own datastructure to represent nodes and inlets, this will become a bit more
    #     # complex
    #     if inlet is not None:
    #         return node, inlet
    #     else:
    #         return node

    # READ
    def nodes(self) -> Iterable[NodeName]:
        for node in self._local_graph.nodes():
            yield node

    def addNode(self, 
            handle: OperatorHandle | None = None, 
            operator: OperatorSignature | None = None
        ) -> NodeName:
        from unique_names_generator import get_random_name
        node_id = NodeId(get_random_name())
        self._beginAddNodes([node_id])
        self._local_graph.add_node(
            node_id, 
            operator_handle=handle,
            operator = operator,
            inputs={},
            status=DirtyStatus()
        )
        self._endAddNodes()
        return node_id

    def setNodeOperator(
        self,
        node: NodeName,
        operator: OperatorSignature | None,
    ) -> None:
        if self._local_graph.attributes(node).get("operator") == operator:
            return

        self._beginResetInlets(node)
        self._local_graph.update(
            node,
            operator=operator,
            status=DirtyStatus(),
        )
        self._endResetInlets()
        self.nodesDataChanged.emit([node],[0, 1], [])

    def refreshOperatorSignatures(
        self,
        signatures: Mapping[OperatorHandle, OperatorSignature],
    ) -> None:
        for node in self.nodes():
            handle = self._local_graph.attributes(node).get("operator_handle")
            operator = (
                signatures.get(handle)
                if isinstance(handle, OperatorHandle)
                else None
            )
            self.setNodeOperator(node, operator)

    def nodeHeaderData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return f"{node_name}"
        return None

    def nodeColumnCount(self, node: NodeName) -> int:
        return 2 # Two columns: operator and status

    def nodeData(self, node_name: NodeName, column:int, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node_data: _NodeShadow = self._local_graph.attributes(node_name)
        match column:
            case 0:
                match role:
                    case Qt.ItemDataRole.DisplayRole:
                        operator_handle = node_data.get('operator')
                        return operator_handle.name if operator_handle is not None else '-no op-'
                    
            case 1:
                match role:
                    case Qt.ItemDataRole.DisplayRole:
                        match node_data.get('status'):
                            case FailedStatus() as failed:
                                return f"💥{type(failed.reason).__name__}: {failed.reason}"
                            case RunningStatus():
                                return "🧠 running..."
                            case SucceededStatus() as success:
                                return f"✨ {success.value!r}"
                                return f"✨" + (f" {success.duration_seconds}s" if success.duration_seconds is not None else "")
                            case DirtyStatus():
                                return "🕸️"
                            case _:
                                return None
                            
                    case Qt.ItemDataRole.ForegroundRole:
                        match node_data.get('status'):
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
                    
        return None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        node_data: _NodeShadow = self._local_graph.attributes(node)
        signature:OperatorSignature | None = node_data.get('operator')
        parameters = signature.inlets if signature is not None else {}
        inputs = node_data.get("inputs", {})
        linked_inlets = [link.inlet for link in self._local_graph.in_links(node)]
        yield from dict.fromkeys((*parameters, *inputs, *linked_inlets))

    def inletHeaderData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return str(inlet)
            case _:
                return None

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        node_data: _NodeShadow = self._local_graph.attributes(node)
        signature: OperatorSignature | None = node_data.get('operator')
        inlet_signature = signature.inlets.get(inlet) if signature is not None else None
        inputs = node_data.get('inputs', dict())
        match role:
            case Qt.ItemDataRole.DisplayRole:
                if inlet in inputs:
                    return str(inputs.get(inlet))
                else:
                    return self.EMPTY

            case Qt.ItemDataRole.EditRole:
                # Preserve explicitly assigned values, including None.
                if inlet in inputs:
                    return inputs[inlet]

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
        for src, dst, key in self._local_graph.in_links(target_node):
            if key == inlet:
                yield (src, 'out', dst, key)

    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._local_graph.out_links(source_node):
            if outlet == 'out':
                yield (src, 'out', dst, key)

    def links(self) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._local_graph.links():
            yield (src, 'out', dst, key)

    # update
    def removeNodes(self, nodes: Iterable[NodeName]) -> bool:
        self._beginRemoveNodes(nodes)
        for node in nodes:
            self._local_graph.remove_node(node)
        self._endRemoveNodes()
        return True

    def addLinks(self, links:Iterable[DirectionalLinkId]) -> bool:
        self._beginAddLinks(links)
        for src, out_, dst, in_ in links:
            self._local_graph.add_link(src, dst, in_)
        self._endAddLinks()
        return True

    def removeLinks(self, links) -> bool:
        self._beginRemoveLinks(links)
        for link in links:
            src, outlet, dst, inlet = link
            self._local_graph.remove_link(src, dst, inlet)
        self._endRemoveLinks()
        return True

    def setInletData(
        self,
        node: NodeName,
        inlet: InletName,
        value: Any,
        role: int,
    ) -> bool:
        if role != Qt.ItemDataRole.EditRole:
            return False

        data = cast(_NodeShadow, self._local_graph.attributes(node))
        inputs = dict(data["inputs"])

        if value is self.EMPTY:
            inputs.pop(inlet, None)
        else:
            inputs[inlet] = value

        self._local_graph.update(
            node,
            inputs=inputs,
            status=DirtyStatus(),
        )
        self.inletDataChanged.emit(node, (inlet,), [])
        self.nodesDataChanged.emit([node],[1], [])
        return True

    def setNodeData(self, node: NodeName, column: int, value: Any, role: int=Qt.ItemDataRole.EditRole) -> bool:
        return False

    def updateNodeStatus(self, node: NodeName, status: NodeStatus) -> bool:
        self._local_graph.set(node, 'status', status)
        self.nodesDataChanged.emit([node], [1], [])
        return True

    def closeEvent(self, event):
        self._unsubscribe()
        super().closeEvent(event)

from dataclasses import dataclass


from qtpy.QtGui import QTextDocument

class EngineModel(QObject):
    scriptStatusChanged = Signal(str, bool)
    graphStatusChanged = Signal(str, bool)

    def __init__(self, parent: QObject|None = None):
        super().__init__(parent=parent)
        self._executing = False
        self._operator_signatures: dict[
            OperatorHandle, OperatorSignature
        ] = {}


        self._client = EngineClient()
        self._client.listen(self._handle_client_changes)

        # models
        self.script = QTextDocument()
        self.operators = QStringListModel(self)

        self._client.start()
        self.graph = AsyncEagerGraphModel(self._client)

        # Graph Execution Scheduler
        self._script_pending = False
        self._graph_pending = False
        self._draining = False
        self._script_valid = False

        self._execution_timer = QTimer(self)
        self._execution_timer.setSingleShot(True)
        self._execution_timer.setInterval(1000//60)
        self._execution_timer.timeout.connect(self._drain_execution)

        self.script.contentsChanged.connect(self.request_script_execution)
        self.graph.nodesDataChanged.connect(self._on_node_data_changed)

        for signal in (
            self.graph.nodesAdded,
            self.graph.nodesRemoved,
            self.graph.inletDataChanged,
            self.graph.linksAdded,
            self.graph.linksRemoved,
        ):
            signal.connect(self.request_graph_execution)

    def close(self) -> None:
        self._execution_timer.stop()
        self._script_pending = False
        self._graph_pending = False
        self._client.close()

    def create_node(self, handle: OperatorHandle) -> NodeName:
        signature = self._operator_signatures[handle]
        return self.graph.addNode(handle, signature)

    def _handle_client_changes(self, changes):
        if operator_changes:=changes.get("operators", dict):
            fut = self._client.get_operators()
            def refresh_operator_model(oparetos: dict):
                self.operators.setStringList([op["name"] for op in oparetos.values()])

            fut.add_done_callback(lambda f: (
                self._operator_signatures.update({
                    op.handle: op.signature 
                    for op in f.result()
                }),
                refresh_operator_model({op.handle: {"name": op.signature.name} for op in f.result()})
            ))

        if graph_changes:=changes.get("graph", dict):
            if node_changes:=graph_changes.get("nodes", dict):
                print(node_changes)

            if link_changes:=graph_changes.get("links", dict):
                print(link_changes)

    @asyncSlot()
    async def execute_script(self) -> None:
        if self._executing:
            return

        self._executing = True
        self.scriptStatusChanged.emit("Evaluating script...", False)

        try:
            # These requests enter the same FIFO queue.
            await asyncio.wrap_future(
                self._client.request_set_script(self.script.toPlainText())
            )
            signatures:Mapping[OperatorHandle, OperatorSignature] = await asyncio.wrap_future(
                self._client.request_execute_script()
            )
        except Exception as exc:
            if self._script_pending:
                return

            self._script_valid = False
            self._operator_signatures.clear()
            self.operators.setStringList([])
            self.scriptStatusChanged.emit(
                f"{type(exc).__name__}: {exc}", True
            )

            # update graphmodel
            self.graph.refreshOperatorSignatures({})
        else:
            if self._script_pending:
                return

            self._script_valid = True
            self._operator_signatures = signatures
            self.operators.setStringList(
                sorted(handle.name for handle in signatures)
            )
            self.scriptStatusChanged.emit(
                "Script evaluated successfully", False
            )

            # # update graphmodel
            self.graph.refreshOperatorSignatures(signatures)

                
        finally:
            self._executing = False

    @asyncSlot()
    async def execute_graph(self) -> None:
        if self._executing:
            return

        self._executing = True
        self.graphStatusChanged.emit("Executing graph...", False)

        try:
            local_graph = cast(Graph[NodeId], self.graph._local_graph)
            compute_graph = Graph[NodeId]()

            for node in local_graph.nodes():
                data = cast(_NodeShadow, local_graph.attributes(node))
                compute_graph.add_node(
                    node,
                    __operator__=data["operator_handle"],
                    kwargs=dict(data["inputs"]),
                )

            for link in local_graph.links():
                compute_graph.add_link(
                    link.source, link.target, link.inlet
                )

            for node in compute_graph.nodes():
                self.graph.updateNodeStatus(node, DirtyStatus())

            statuses = await asyncio.wrap_future(
                self._client.request_execute_graph(compute_graph)
            )

            # Edits made during execution belong to the next snapshot.
            if self._script_pending or self._graph_pending:
                return

            for node, status in statuses.items():
                if node in self.graph.nodes():
                    self.graph.updateNodeStatus(node, status)

            failure = next(
                (
                    status
                    for status in statuses.values()
                    if isinstance(status, FailedStatus)
                ),
                None,
            )

            if failure is not None:
                self.graphStatusChanged.emit(
                    f"Execution stopped: {failure.reason}", True
                )
            else:
                self.graphStatusChanged.emit(
                    "Graph executed successfully", False
                )

        except Exception as exc:
            if self._script_pending or self._graph_pending:
                return

            self.graphStatusChanged.emit(
                f"{type(exc).__name__}: {exc}", True
            )
        finally:
            self._executing = False

    # Graph scheduling methods
    def _on_node_data_changed(
        self,
        nodes: list[NodeName],
        columns: list[int],
        roles: list[int],
    ) -> None:
        if 0 in columns:
            self.request_graph_execution()

    def request_script_execution(self, *_args: object) -> None:
        self._script_pending = True
        self._graph_pending = True
        self._execution_timer.start()

    def request_graph_execution(self, *_args: object) -> None:
        self._graph_pending = True
        self._execution_timer.start()

    @asyncSlot()
    async def _drain_execution(self) -> None:
        if self._draining:
            return

        self._draining = True
        try:
            while self._script_pending or self._graph_pending:
                if self._script_pending:
                    self._script_pending = False
                    await self.execute_script()

                    if self._script_pending:
                        continue

                if self._graph_pending:
                    self._graph_pending = False
                    if self._script_valid:
                        await self.execute_graph()
        finally:
            self._draining = False

from qdageditor5.views.node_inspector_view import NodeInspectorView
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


from myqtx.selection_dialog_view import SelectionDialog

from qtpy.QtCore import (
    QEvent, 
    QObject, 
    Qt, 
    Signal, 
    SignalInstance,
    Slot
)

class NodeDataViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Node Output Viewer")
        self.setMinimumSize(400, 300)

        self._model: AbstractDAGModel | None = None
        self._selection_model: GraphSelectionModel | None = None
        self._model_connections: list[tuple[SignalInstance, Callable]] = []
        self._selection_connections: list[tuple[SignalInstance, Callable]] = []

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        self._display_widget = DisplayWidget()
        main_layout.addWidget(self._display_widget)
        self._column = 0

    def setDisplayColumn(self, column: int) -> None:
        if column == self._column:
            return

        self._column = column
        current = (
            self._selection_model.currentNode()
            if self._selection_model is not None
            else None
        )
        self._refresh_display_widget(current)

    def displayColumn(self) -> int:
        return self._column

    def setModel(self, model: AbstractDAGModel | None) -> None:
        if model is self._model:
            return

        for signal, slot in self._model_connections:
            signal.disconnect(slot)

        self._model_connections.clear()
        self._model = model

        if model is not None:
            self._model_connections.append(
                (model.nodesDataChanged, self._handle_node_data_changed)
            )
            for signal, slot in self._model_connections:
                signal.connect(slot)

        self.setSelectionModel(
            GraphSelectionModel(model, parent=self) if model is not None else None
        )

    def model(self) -> AbstractDAGModel | None:
        return self._model

    def selectionModel(self) -> GraphSelectionModel | None:
        return self._selection_model

    def setSelectionModel(self, selection_model: GraphSelectionModel | None) -> None:
        if selection_model is self._selection_model:
            return

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
                (selection_model.currentNodeChanged, self._handle_current_node_changed)
            ]
            for signal, slot in self._selection_connections:
                signal.connect(slot)

        # Refresh the display widget with the current node of the new selection model.
        current = (
            selection_model.currentNode()
            if selection_model is not None
            else None
        )
        self._refresh_display_widget(current)

    def _handle_current_node_changed(self, node: NodeName | None, previous: NodeName | None) -> None:
        self._refresh_display_widget(node)

    def _handle_node_data_changed(self, nodes, columns:list[int], roles: list[Qt.ItemDataRole]) -> None:
        if self._selection_model is None:
            return
        current = self._selection_model.currentNode()
        if current in nodes and self._column in columns:
            self._refresh_display_widget(current)

    def _refresh_display_widget(self, node: NodeName | None) -> None:
        if node is None:
            self._display_widget.display("- no selection -")
            return
        data = self._model.nodeData(node, self._column, Qt.ItemDataRole.DisplayRole) if self._model is not None else None
        self._display_widget.display(data)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        dedent("""\
def the_name():
    return "Mása"

def the_greeting():
    return "Hey!"

def hello_world(name:str, greeting:str="Hello"):
    return f"{greeting}, {name}!"
        """)
        # model
        self._engine_model = EngineModel()
        self.graphselection = GraphSelectionModel(self._engine_model.graph)

        self._engine_model.scriptStatusChanged.connect(
            self._show_status
        )
        self._engine_model.graphStatusChanged.connect(
            self._show_status
        )

        # main menubar
        self.menu_bar = self.menuBar()

        # edit menu
        self.edit_menu = self.menu_bar.addMenu("Edit")
        execute_script_action = self.edit_menu.addAction("execute script")
        execute_script_action.triggered.connect(self._engine_model.request_script_execution)

        execute_graph_action = self.edit_menu.addAction("execute graph")
        execute_graph_action.triggered.connect(self._engine_model.request_graph_execution)
        
        # views
        self.script_edit = ScriptEditAdvanced()
        self.script_edit.setDocument(self._engine_model.script)

        self.operators_view = QListView()
        self.operators_view.setModel(self._engine_model.operators)

        self.graph_edit = DirectionalGraphView5()
        self.graph_edit.setModel(self._engine_model.graph)
        self.graph_edit.setSelectionModel(self.graphselection)
        self.graph_edit.requestNode.connect(lambda pos, source, editor=self.graph_edit: 
            self.open_new_node_dialog(pos, source, editor))
        
        self.graph_edit.requestLink.connect(lambda src, outlet, dst, inlet: 
            self._engine_model.graph.addLinks([(src, outlet, dst, inlet)]))

        self.inspector = NodeInspectorView()
        self.inspector.setModel(self._engine_model.graph)
        self.inspector.setSelectionModel(self.graphselection)

        self.output_viewer = NodeDataViewer()
        self.output_viewer.setDisplayColumn(1)
        self.output_viewer.setModel(self._engine_model.graph)
        self.output_viewer.setSelectionModel(self.graphselection)

        # layout views
        main_layout = QHBoxLayout()
        main_layout.addWidget(self.script_edit)
        main_layout.addWidget(self.operators_view)
        main_layout.addWidget(self.graph_edit)
        main_layout.addWidget(self.inspector)
        main_layout.addWidget(self.output_viewer)
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def open_new_node_dialog(self, scene_pos, source, editor):
        dialog = SelectionDialog(self._engine_model.operators, self)
        try:
            if dialog.exec() == SelectionDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                operator_name = selected_index.data(Qt.ItemDataRole.EditRole)
                operator_handle = OperatorHandle(operator_name)
                new_node = self._engine_model.create_node(operator_handle)
                editor.setNodePosition(new_node, scene_pos)
        finally:
            dialog.deleteLater()

    @Slot(str, bool)
    def _show_status(self, message: str, is_error: bool) -> None:
        status_bar = self.statusBar()
        status_bar.setStyleSheet(
            "QStatusBar { color: red; }" if is_error else ""
        )
        status_bar.showMessage(message)


if __name__ == "__main__":
    import sys
    from qtpy.QtWidgets import QApplication

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    editor = Window()
    editor.show()
    # loop.call_soon(editor.submit_execute_script)
    with loop:
        try:
            loop.run_forever()
        finally:
            editor._engine_model.close()
            # editor.worker.close()
            # worker_logger.removeHandler(editor.log_handler)
            # editor.log_handler.close()


