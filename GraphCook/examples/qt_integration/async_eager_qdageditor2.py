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
from qtpy.QtWidgets import QAbstractScrollArea, QDialog, QHBoxLayout, QListView, QSizePolicy, QSplitter, QWidget
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
                view_graph.add_node(node_id, **attributes)
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
    node_id: NodeId
    operator: OperatorHandle | None = None
    status: NodeStatus | None = None


class AsyncEagerGraphModel(AbstractDAGModel):
    def __init__(
        self,
        client: EngineClient,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._graph: ObservableGraph[NodeId, _NodeShadow] = ObservableGraph()
        self._client = client
        # sync the observable graph with the engine client
        def _sync_client(change: GraphChange) -> None:
            # handle changes from the engine client and update the observable graph
            if link_change := change.get("links"):
                for link_id in link_change.get('added', []):
                    self._client.submit(lambda engine, link_id=link_id: 
                        engine.graph.add_link(link_id))

                for link_id in link_change.get('removed', []):
                    self._client.submit(lambda engine, link_id=link_id: 
                        engine.graph.remove_link(link_id))
                    
            if nodes_change := change.get("nodes"):
                for node_id in nodes_change.get('added', []):
                    self._client.submit(lambda engine, node_id=node_id: 
                        engine.graph.add_node(node_id))

                for node_id in nodes_change.get('removed', []):
                    self._client.submit(lambda engine, node_id=node_id: 
                        engine.graph.remove_node(node_id))

                for node_id in nodes_change.get('updated', []):
                    ...

        self._graph.listen(_sync_client)

        def _sync_local(change: EngineChange) -> None:
            # handle changes from the engine client and update the observable graph
            pass

        client.listen(_sync_local)

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
        for node in self._graph.nodes():
            yield node

    def addNode(self, operator: OperatorHandle | None = None) -> NodeName:
        from unique_names_generator import get_random_name
        node_id = NodeId(get_random_name())
        self._beginAddNodes([node_id])
        self._graph.add_node(node_id, 
            __operator__ = operator
        )
        self._endAddNodes()
        return node_id

    def operatorSignature(self, node: NodeName) -> OperatorSignature | None:
        """Resolve a node's handle against the current operator registry."""
        node_data = self._graph.attributes(self.mapToSource(node))
        handle = node_data.get(OPERATOR_ATTRIBUTE)
        if handle is None:
            return None
        assert isinstance(handle, OperatorHandle)
        return self._operator_signature(handle)

    def refreshOperatorSignatures(self, operators: Iterable[OperatorHandle]) -> None:
        """Refresh ports and inspector editors after the registry changes."""
        changed = set(operators)
        for node in self.nodes():
            node_data = self._graph.attributes(self.mapToSource(node))
            if node_data.get(OPERATOR_ATTRIBUTE) in changed:
                self._beginResetInlets(node)
                self._endResetInlets()

    def nodeHeaderData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return f"{node_name}"
        return None

    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node_data: Mapping[str, Any] = self._graph.attributes(self.mapToSource(node_name))
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
        node_data = self._graph.attributes(node_id)
        signature = self.operatorSignature(node)
        parameters = signature.inlets if signature is not None else {}
        inputs = [name for name in node_data if not name.startswith('_')]
        linked_inlets = [link.inlet for link in self._graph.in_links(node_id)]
        yield from dict.fromkeys((*parameters, *inputs, *linked_inlets))

    def inletHeaderData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return str(inlet)
            case _:
                return None

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        node_data: Mapping[str, Any] = self._graph.attributes(self.mapToSource(node))
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
        for src, dst, key in self._graph.in_links(target_node):
            if key == inlet:
                yield (src, 'out', dst, key)

    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._graph.out_links(source_node):
            if outlet == 'out':
                yield (src, 'out', dst, key)

    def links(self) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._graph.links():
            yield (src, 'out', dst, key)

    # update
    def removeNodes(self, nodes: Iterable[NodeName]) -> bool:
        self._beginRemoveNodes(nodes)
        for node in nodes:
            node_id = self.mapToSource(node)
            self._graph.remove_node(node_id)
        self._endRemoveNodes()
        return True

    def addLinks(self, links:Iterable[DirectionalLinkId]) -> bool:
        self._beginAddLinks(links)
        for src, out_, dst, in_ in links:
            src_id = self.mapToSource(src)
            dst_id, inlet = self.mapToSource(dst, in_)
            self._graph.add_link(src_id, dst_id, inlet)
        self._endAddLinks()
        return True

    def removeLinks(self, links) -> bool:
        self._beginRemoveLinks(links)
        for link in links:
            src, outlet, dst, inlet = link
            src_id = self.mapToSource(src)
            dst_id, inlet = self.mapToSource(dst, inlet)
            self._graph.remove_edge(src_id, dst_id, inlet)
        self._endRemoveLinks()
        return True

    def setInletData(self, node: NodeName, inlet: InletName, value: Any, role: int) -> bool:
        if role == Qt.ItemDataRole.EditRole:
            if value is self.EMPTY:
                node_id, inlet_id = self.mapToSource(node, inlet)
                self._graph.unset(node_id, inlet_id)
                self.inletDataChanged.emit(node, tuple([inlet]), [])
                return True
            else:
                node_id, inlet_id = self.mapToSource(node, inlet)
                self._graph.set(node_id, inlet_id, value)
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


from qtpy.QtGui import QTextDocument

class EngineModel(QObject):
    scriptStatusChanged = Signal(str, bool)
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
        self.script.contentsChanged.connect(
            lambda: self._client.request_set_script(
                self.script.toPlainText()
            )
        )
        self.operators = QStringListModel(self)

        self._client.start()
        self.graph = AsyncEagerGraphModel(self._client)

    def close(self) -> None:
        self._client.close()

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
            self._client.request_set_script(self.script.toPlainText())
            signatures = await asyncio.wrap_future(
                self._client.request_execute_script()
            )
        except Exception as exc:
            self._operator_signatures.clear()
            self.operators.setStringList([])
            self.scriptStatusChanged.emit(
                f"{type(exc).__name__}: {exc}", True
            )
        else:
            self._operator_signatures = signatures
            self.operators.setStringList(
                sorted(handle.name for handle in signatures)
            )
            self.scriptStatusChanged.emit(
                "Script evaluated successfully", False
            )
        finally:
            self._executing = False

    @asyncSlot()
    async def execute_graph(self) -> None:
        ...


from qdageditor5.views.node_inspector_view import NodeInspectorView
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        #model
        self._engine_model = EngineModel()
        self.graphselection = GraphSelectionModel(self._engine_model.graph)

        self._engine_model.scriptStatusChanged.connect(
            self._show_script_status
        )

        # main menubar
        self.menu_bar = self.menuBar()

        # edit menu
        self.edit_menu = self.menu_bar.addMenu("Edit")
        execute_script_action = self.edit_menu.addAction("execute script")
        execute_script_action.triggered.connect(self._engine_model.execute_script)

        # views
        self.script_edit = ScriptEditAdvanced()
        self.script_edit.setDocument(self._engine_model.script)

        self.operators_view = QListView()
        self.operators_view.setModel(self._engine_model.operators)

        self.graph_edit = DirectionalGraphView5()
        self.graph_edit.setModel(self._engine_model.graph)
        self.graph_edit.setSelectionModel(self.graphselection)

        self.inspector = NodeInspectorView()
        self.inspector.setModel(self._engine_model.graph)
        self.inspector.setSelectionModel(self.graphselection)

        # layout views
        main_layout = QHBoxLayout()
        main_layout.addWidget(self.script_edit)
        main_layout.addWidget(self.operators_view)
        main_layout.addWidget(self.graph_edit)
        main_layout.addWidget(self.inspector)
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    @Slot(str, bool)
    def _show_script_status(self, message: str, is_error: bool) -> None:
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


