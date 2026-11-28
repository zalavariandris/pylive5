import asyncio
from copy import copy
from inspect import Parameter
from textwrap import dedent
from typing import Any, Callable, Iterable, Mapping, Iterable, Literal, Any, cast

from threading import Thread
from queue import Queue
import concurrent.futures
import logging

from unique_names_generator import get_random_name
from graphcook.core.changes import ObservableValue
from qasync import QEventLoop, asyncSlot

from qtpy.QtCore import QAbstractListModel, QModelIndex, QPointF, QTimer, Qt, QObject
from qtpy.QtCore import QStringListModel
from qtpy.QtCore import Qt
from qtpy.QtCore import Signal, Slot
from qtpy.QtGui import QTextDocument
from qtpy.QtGui import QTextCursor
from qtpy.QtWidgets import QAbstractScrollArea, QDialog, QFrame, QGridLayout, QHBoxLayout, QListView, QMenuBar, QSizePolicy, QSplitter, QStackedLayout, QStackedWidget, QStatusBar, QTabWidget, QVBoxLayout, QWidget
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

from concurrent.futures import Future

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

from rich.console import Console
from rich.markup import escape

console = Console(stderr=True, force_terminal=True)
from typing import TypedDict, Any, Callable

class _NodeConfig(TypedDict):
    __operator__: OperatorHandle
    kwargs: dict[str, Any]


class Executor:
    def __init__(self)->None:
        # internal state?
        self._source: str = "" # hold the current script to compare against new submissions
        self.operators: dict[OperatorHandle, Callable] = dict()
        self.signatures: dict[OperatorHandle, OperatorSignature] = dict()
        self.cache = MemoryCache[NodeId, Any]()

        # computed
        self.node_statuses: dict[NodeId, NodeStatus] = dict()

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
        subgraph: Graph[NodeId, _NodeConfig],
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
# class Invalidator:
#     def __init__(self, graph: ObservableGraph[NodeId]) -> None:
#         self.graph = graph
#         self._subscribers: list[Callable[[list[NodeId]], None]] = []
#         self._unsubscribe_graph: Callable[[], None] | None = graph.listen(self._handle_graph_change)

#     def close(self) -> None:
#         """Stop observing the graph. Safe to call more than once."""
#         if self._unsubscribe_graph is not None:
#             self._unsubscribe_graph()
#             self._unsubscribe_graph = None

#     def _handle_graph_change(self, change: GraphChange) -> None:
#         nodes_to_invalidate: set[NodeId] = set()
#         if nodes_change:=change.get("nodes"):
#             for node_id in nodes_change.get("added", []):
#                 nodes_to_invalidate.add(node_id)

#             for node_id in nodes_change.get("removed", []):
#                 ...

#             for node_id in nodes_change.get("updated", []):
#                 nodes_to_invalidate.add(node_id)
#                 for dep in descendants(self.graph, node_id):
#                     nodes_to_invalidate.add(dep)

#         if links_change:=change.get("links"):
#             for link in links_change.get("added", []):
#                 src, dst, inlet = link
#                 nodes_to_invalidate.add(dst)
#                 for dep in descendants(self.graph, dst):
#                     nodes_to_invalidate.add(dep)

#             for link in links_change.get("removed", []):
#                 src, dst, inlet = link
#                 if dst not in self.graph.nodes():
#                     continue
#                 nodes_to_invalidate.add(dst)
#                 for dep in descendants(self.graph, dst):
#                     nodes_to_invalidate.add(dep)

#         if nodes_to_invalidate:
#             self._notify_subscribers(nodes_to_invalidate)

#     def _notify_subscribers(self, nodes: set[NodeId]) -> None:
#         for subscriber in tuple(self._subscribers):
#             subscriber(list(nodes))

#     def invalidate(self, *nodes: NodeId) -> None:
#         """manually trigger invalidation for the given nodes and their descendants"""
#         nodes_to_invalidate: set[NodeId] = set(nodes)
#         for node in nodes:
#             for dep in descendants(self.graph, node):
#                 nodes_to_invalidate.add(dep)

#         if nodes_to_invalidate:
#             self._notify_subscribers(nodes_to_invalidate)

#     def listen(self, callback: Callable[[Iterable[NodeId]], None]) -> Callable[[], None]:
#         """listen for nodes invalidated"""
#         self._subscribers.append(callback)
#         def unsubscribe():
#             self._subscribers.remove(callback)
#         return unsubscribe


class Engine:
    def __init__(self)->None:
        # self.script:ObservableValue[str] = ObservableValue("")
        # self.graph:ObservableGraph[NodeId] = ObservableGraph()
        # self.invalidator: Invalidator = Invalidator(self.graph)
        # self.invalidator.listen(lambda nodes: self._handle_invalidation(nodes))
        self.executor: Executor = Executor()
        # self._operators: dict[OperatorHandle, object] = dict()
        # self._status: dict[NodeId, Any] = dict() # consider using an ObservableDict?

    # def operator_handle(self, node: NodeId) -> OperatorHandle|None:
    #     attributes = self.graph.attributes(node)
    #     handle: OperatorHandle|None = attributes.get('operator', None)
    #     return handle

    # def _handle_script_change(self, new_script: str) -> None:
    #     """ Handle script changes here """
    #     # - notify connected clients
    #     ...

    #     # - execute operators and update relevant nodes with the changed oprators
    #     ...

    # def _handle_invalidation(self, nodes: Iterable[NodeId]) -> None:
    #     """ Handle invalidated nodes here """
    #     # - notify connected clients about the invalidated nodes
    #     ...

    #     # - execute nodes that have been invalidated and update their state accordingly using the executor
    #     ...

    #     # notify clients about the new status
    #     self._handle_status_change({node: self._status.get(node) for node in nodes})

    # def _handle_status_change(self, changes: dict[NodeId, NodeStatus]) -> None:
    #     """ Handle state changes here """
    #     # notify connected clients about the state changes
    #     ...


class ExecutorWorker(Thread):
    def __init__(self, tasks: Queue[tuple[Future, Callable[[Executor], Any]]])->None:
        super().__init__()
        self._tasks = tasks

    def run(self) -> None:
        executor = Executor()
        while True:
            future, task = self._tasks.get()
            if task is None:
                break
            task_repr = getattr(task, "__qualname__", task)
            try:
                response = task(executor)
            except Exception as exc:
                future.set_exception(exc)
                console.print(f"[bold red]✗ {escape(str(task_repr))}[/] failed: {escape(str(exc))}")
                console.print_exception(show_locals=False, max_frames=8)
            else:
                future.set_result(response)
                console.print(f"[green]✓ {escape(str(task_repr))}[/]")

    def close(self) -> None:
        self._tasks.put((Future(), None))
        self.join()


class ExecutorClient:
    def __init__(self, tasks: Queue[tuple[Future, Callable[[Executor], Any]]]) -> None:
        self._tasks = tasks

    async def submit(self, process: Callable[[Executor], Any]) -> Any:
        future = Future[Any]()
        self._tasks.put((future, process))
        return await asyncio.wrap_future(future)

    async def execute_script(self, new_script: str) -> dict[OperatorHandle, OperatorSignature]:
        def execute(
            executor: Executor,
        ) -> dict[OperatorHandle, OperatorSignature]:
            operators = executor.execute_script(new_script)
            return {
                handle: OperatorSignature.from_func(func, revision=revision)
                for handle, (func, revision) in operators.items()
            }

        return await self.submit(execute)

    async def execute_graph(self, subgraph: Graph[NodeId, _NodeConfig]) -> dict[NodeId, NodeStatus]:
        return await self.submit(lambda executor: executor.execute_subgraph(subgraph))


class LogWidget(QPlainTextEdit):
    message_received = Signal(str)
    text_received = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)

        self.message_received.connect(
            self.append_message,
            Qt.ConnectionType.QueuedConnection,
        )
        self.text_received.connect(
            self._insert_text,
            Qt.ConnectionType.QueuedConnection,
        )

    def write(self, text: str) -> int:
        """Accept a text fragment, including from a worker thread."""
        if text:
            self.text_received.emit(text)
        return len(text)

    def flush(self) -> None:
        """No local buffer; queued text appears when Qt processes events."""
        pass

    @Slot(str)
    def append_message(self, message: str) -> None:
        self._insert_text(message + "\n")

    @Slot(str)
    def _insert_text(self, text: str) -> None:
        scrollbar = self.verticalScrollBar()
        follow_output = scrollbar.value() == scrollbar.maximum()

        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)

        if follow_output:
            scrollbar.setValue(scrollbar.maximum())

    # Keep your existing contextMenuEvent method.

##########
# MODELS #
##########
from typing import TypedDict


class _NodeShadow(TypedDict):
    operator_handle: OperatorHandle
    operator: OperatorSignature
    inputs: dict[InletName, object|None]
    status: NodeStatus


class _NodeAdditionalState(TypedDict):
    operator: OperatorSignature
    status: NodeStatus

class ProxyGraphModel(AbstractDAGModel):
    def __init__(
        self,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._config_graph: Graph[NodeName, _NodeConfig] = Graph()
        self._nodes_additional_state: dict[NodeName, _NodeAdditionalState] = {}
        self._local_graph: Graph[NodeName, _NodeShadow] = Graph() # with OperatorHandles and Signatures

    # READ
    def nodes(self) -> Iterable[NodeName]:
        for node in self._local_graph.nodes():
            yield node

    def addNode(self, 
            handle: OperatorHandle | None = None, 
            operator: OperatorSignature | None = None
        ) -> NodeName:
        
        node_id = NodeId(get_random_name())
        self._beginAddNodes([node_id])
        # self._local_graph.add_node(
        #     node_id, 
        #     operator_handle=handle,
        #     operator = operator,
        #     inputs={},
        #     status=DirtyStatus()
        # )
        self._config_graph.add_node(node_id, _NodeConfig(
            node_id,
            inputs={}
        ))
        self._nodes_additional_state[node_id] = _NodeAdditionalState(
            operator=operator,
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
        self._local_graph.update_attributes(
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

        self._local_graph.update_attributes(
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
        self._local_graph.set_attribute(node, 'status', status)
        self.nodesDataChanged.emit([node], [1], [])
        return True

    def closeEvent(self, event):
        self._unsubscribe()
        super().closeEvent(event)

    def toGraph(self) -> Graph[NodeId, _NodeConfig]:
        compute_graph = Graph[NodeId, _NodeConfig]()

        for node in self._local_graph.nodes():
            data = cast(_NodeShadow, self._local_graph.attributes(node))
            compute_graph.add_node(
                node,
                __operator__=data["operator_handle"],
                kwargs=dict(data["inputs"]),
            )

        for link in self._local_graph.links():
            compute_graph.add_link(
                link.source, link.target, link.inlet
            )

        return compute_graph



class EngineModel(QObject):
    scriptStatusChanged = Signal(str, bool)
    graphStatusChanged = Signal(str, bool)

    def __init__(self, parent: QObject|None = None):
        super().__init__(parent=parent)
        self._executing = False
        self._operator_signatures: dict[
            OperatorHandle, OperatorSignature
        ] = {}

        self._tasks: Queue[tuple[Future, Callable[[Executor], Any]]] = Queue()
        self.worker = ExecutorWorker(self._tasks)
        self.client = ExecutorClient(self._tasks)

        # models
        self.script = QTextDocument()
        self.operators = QStringListModel(self)

        self.worker.start()
        self.graph = ProxyGraphModel()

        # Graph Execution Scheduler
        class Scheduler(QObject):
            def __init__(self, parent: QObject|None = None):
                super().__init__(parent=parent)

        self._script_pending = False
        self._graph_pending = False
        self._draining = False
        self._script_valid = False

        self._execution_timer = QTimer(self)
        self._execution_timer.setSingleShot(True)
        self._execution_timer.setInterval(1000//60)
        self._execution_timer.timeout.connect(self._drain_execution)

        self.script.contentsChanged.connect(self.request_script_execution)
        self.graph.nodesDataChanged.connect(lambda nodes, columns, roles: 
            self.request_graph_execution() if 0 in columns else None)

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
        self.worker.close()

    def create_node(self, handle: OperatorHandle) -> NodeName:
        signature = self._operator_signatures[handle]
        return self.graph.addNode(handle, signature)

    def _handle_client_changes(self, changes):
        if operator_changes:=changes.get("operators", dict):
            fut = self.client.get_operators()
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
            signatures = await self.client.execute_script(
                self.script.toPlainText()
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
            compute_graph:Graph[NodeId, _NodeConfig] = self.graph.toGraph()
            statuses = await self.client.execute_graph(compute_graph)

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
from qdageditor5.views.node_data_viewer import NodeDataViewer
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


from myqtx.selection_dialog_view import SelectionDialog
from myqtx.logview import LogView

from qtpy.QtCore import (
    QEvent, 
    QObject, 
    Qt, 
    Signal, 
    SignalInstance,
    Slot
)

import PySide6QtAds as ads
class Window(QWidget):
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
        self.menubar = QMenuBar()

        self.edit_menu = self.menubar.addMenu("Edit")
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
        self.graph_edit.setFrameShape(QFrame.Shape.NoFrame)
        self.graph_edit.setModel(self._engine_model.graph)
        self.graph_edit.setSelectionModel(self.graphselection)
        self.graph_edit.requestNode.connect(lambda pos, source, editor=self.graph_edit: 
            self.open_new_node_dialog(pos, source, editor))
        
        self.graph_edit.requestLink.connect(lambda src, outlet, dst, inlet: 
            self._engine_model.graph.addLinks([(src, outlet, dst, inlet)]))

        self.inspector = NodeInspectorView()
        self.inspector.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector.setModel(self._engine_model.graph)
        self.inspector.setSelectionModel(self.graphselection)

        self.output_viewer = NodeDataViewer()
        self.output_viewer.setDisplayColumn(1)
        self.output_viewer.setModel(self._engine_model.graph)
        self.output_viewer.setSelectionModel(self.graphselection)

        self.statusbar = QStatusBar()

        # setup logging
        self.log_view = LogView()

        self.resize(1300, 700)
        self.__simple_layout()

    def menuBar(self):
        return self.menubar

    def statusBar(self):
        return self.statusbar

    def __docking_layout(self):
        # Docking layout
        def _create_dock(
            title: str,
            name: str,
            widget: QWidget,
        ) -> ads.CDockWidget:
            dock = ads.CDockWidget(self.dock_manager, title)
            dock.setObjectName(name)
            dock.setWidget(widget)
            self.view_menu.addAction(dock.toggleViewAction())
            return dock
        
        self.dock_manager = ads.CDockManager(self)
        self.view_menu = self.menubar.addMenu("View")

        self.graph_dock = _create_dock(
            "Graph", "graph", self.graph_edit,
        )
        self.script_dock = _create_dock(
            "Script", "script", self.script_edit,
        )
        self.operators_dock = _create_dock(
            "Operators", "operators", self.operators_view,
        )
        self.inspector_dock = _create_dock(
            "Inspector", "inspector", self.inspector,
        )
        self.output_dock = _create_dock(
            "Output", "output", self.output_viewer,
        )

        script_area = self.dock_manager.addDockWidget(
            ads.CenterDockWidgetArea,
            self.script_dock
        )

        graph_area = self.dock_manager.addDockWidget(
            ads.CenterDockWidgetArea,
            self.graph_dock,
            script_area
        )

        inspector_area = self.dock_manager.addDockWidget(
            ads.RightDockWidgetArea,
            self.inspector_dock,
            graph_area,
        )

        self.dock_manager.addDockWidget(
            ads.RightDockWidgetArea,
            self.output_dock
        )

        self.dock_manager.addDockWidget(
            ads.RightDockWidgetArea,
            self.operators_dock,
            script_area,
        )
        self.operators_dock.toggleView(False)

        self.dock_manager.setStyleSheet(
            self.dock_manager.styleSheet() + """
            ads--CDockSplitter {
                qproperty-handleWidth: 4;
            }

            ads--CDockContainerWidget ads--CDockSplitter::handle {
                background: palette(window);
            }

            ads--CDockContainerWidget ads--CDockSplitter::handle:hover {
                background: palette(window);
            }
            """
        )

    def __simple_layout(self):
        # Simple Layout
        splitter = QSplitter()
        left_area = QTabWidget()
        left_area.addTab(self.script_edit, "Script")
        graph_with_inspector = QWidget()
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.addWidget(self.graph_edit, 0, 0)
        grid_layout.addWidget(
            self.inspector,
            0, 0,
            alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        graph_with_inspector.setLayout(grid_layout)
        left_area.addTab(graph_with_inspector, "Graph")
        left_area.setCurrentWidget(graph_with_inspector)
        right_area = QTabWidget()
        right_area.addTab(self.output_viewer, "Output")
        
        splitter.addWidget(left_area)
        splitter.addWidget(right_area)
        splitter.setSizes([self.width() // 2, self.width() // 2])
        main_layout = QVBoxLayout()
        main_layout.setMenuBar(self.menubar)
        main_layout.addWidget(splitter)
        main_layout.addWidget(self.log_view)
        self.setLayout(main_layout)
        # self.setCentralWidget(main_layout)

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

    def closeEvent(self, event):
        self._engine_model.close()
        self._engine_model.close()
        self.log_view.setLogger(None)
        event.accept()


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
            pass



