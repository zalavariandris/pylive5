import asyncio
from textwrap import dedent
from typing import Iterable, Any, cast
from typing import Any, Callable, Iterable, Mapping
from threading import Thread
from queue import Queue
import concurrent.futures
import logging

from qasync import QEventLoop, asyncSlot

from qtpy.QtCore import QAbstractListModel, QPointF, Qt, QObject
from qtpy.QtCore import QStringListModel
from qtpy.QtCore import Qt
from qtpy.QtCore import Signal, Slot
from qtpy.QtWidgets import QAbstractScrollArea, QDialog, QListView, QSizePolicy, QSplitter, QWidget
from qtpy.QtWidgets import QDockWidget, QMainWindow, QSplitter
from qtpy.QtWidgets import QPlainTextEdit

from qdageditor5.core.item_data_roles import NodeDataRole
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


worker_logger = logging.getLogger("graphcook.worker")


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


class QtLogHandler(logging.Handler):
    def __init__(self, send_message: Callable[[str], None]) -> None:
        super().__init__()
        self._send_message = send_message

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._send_message(self.format(record))
        except Exception:
            self.handleError(record)


class AsyncEagerGraphModel(AbstractDAGModel):
    def __init__(self, graph:ObservableGraph[NodeId], parent: QObject|None = None):
        super().__init__(parent=parent)
        self._config_graph = graph
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

    def addNode(self, operator: OperatorSignature|None = None) -> NodeName|None:
        from unique_names_generator import get_random_name
        node_id = NodeId(get_random_name())
        self._beginAddNodes([node_id])
        self._config_graph.add_node(node_id, 
            __operator__ = operator
        )
        self._endAddNodes()
        return node_id

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
        node_data: Mapping[str, Any] = self._config_graph.attributes(self.mapToSource(node))
        signature:OperatorSignature|None = node_data.get(OPERATOR_ATTRIBUTE)
        if signature is not None:
            for inlet_name, inlet_signature in signature.inlets.items():
                yield inlet_name

            for key, value in node_data.items():
                if key.startswith('_'):
                    continue
                if key not in signature.inlets.keys():
                    yield key
        else:
            for key, value in node_data.items():
                if key.startswith('_'):
                    continue

                yield key

    def inletHeaderData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return str(inlet)
            case _:
                return None

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        node_data: Mapping[str, Any] = self._config_graph.attributes(self.mapToSource(node))
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

                operator_signature = node_data.get(OPERATOR_ATTRIBUTE)
                assert isinstance(operator_signature, OperatorSignature) or operator_signature is None
                if operator_signature is None:
                    return self.EMPTY

                inlet_signature = operator_signature.inlets.get(inlet)
                if inlet_signature is None:
                    return self.EMPTY

                default = inlet_signature.default
                if default is not None:
                    return default

                annotation = inlet_signature.annotation
                if annotation in (str, int, float, bool):
                    return annotation()

                return self.EMPTY
            
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


class Worker(Thread):
    def __init__(self):
        super().__init__()
        self._tasks = Queue()
        self._resolved_functions: dict[OperatorHandle, Callable|None] = {}
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
        from concurrent.futures import Future
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
                try:
                    operators: dict[OperatorHandle, Callable] = _execute_provider(payload)
                except BaseException as exc:
                    worker_logger.exception("Script execution failed")
                    future.set_exception(exc)
                else:
                    worker_logger.info("Loaded %d operators", len(operators))
                    
                    self._resolved_functions.clear()
                    self._resolved_functions.update({
                        op: func 
                        for op, func in operators.items()
                    })
                    signatures = {
                        op: OperatorSignature.from_func(func)
                        for op, func in operators.items()
                    }
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


class ExecutionCoordinator:
    def __init__(self, config: ObservableGraph[NodeId]):
        self.config = config

    def add_effect(self, node: NodeId) -> None:
        ...

    def remove_effect(self, node: NodeId) -> None:
        ...

    def invalidate(self, *nodes: NodeId) -> None:
        ...


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.operator_list_model = QStringListModel([])
        config_graph = ObservableGraph[NodeId]()
        self.model = AsyncEagerGraphModel(config_graph)
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
        self.operator_list = QListView()
        self.operator_list.setSizePolicy(
            QSizePolicy.Policy.Minimum, 
            QSizePolicy.Policy.Expanding
        )
        # self.operator_list.setFixedWidth(180)
        self.operator_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.operator_list.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents);
        self.operator_list.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding);
        self.operator_list.setModel(self.operator_list_model)
        splitter.addWidget(self.operator_list)
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

        config_graph.listen(on_config_graph_changed)
        self.selection.currentNodeChanged.connect(self.submit_execute_graph)

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
            signatures:dict[OperatorHandle, OperatorSignature] = await self.worker.submit('execute_script', script_text)
        except Exception as exc:
            return

        # Ignore this result if the script changed while we were waiting.
        if document.toPlainText() != script_text:
            return

        self.operator_list_model.setStringList(
            [handle.name for handle in signatures.keys()]
        )
        self._operator_signatures = signatures

    @asyncSlot()
    async def submit_execute_graph(self) -> None:
        # get relevant subgraph from the editor
        current_name = self.selection.currentNode()
        current_node_id = self.model.mapToSource(current_name)
        G = self.model._config_graph
        # prepare subgraph
        resolved_subgraph = Graph[NodeId]()
        for node in G.nodes():
            operator_signature = G.attributes(node)["__operator__"]
            assert isinstance(operator_signature, OperatorSignature)
            operator_handle = OperatorHandle(operator_signature.name)
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
                operator_signature = self._operator_signatures.get(operator_handle)
                new_node = self.model.addNode(operator_signature)
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
