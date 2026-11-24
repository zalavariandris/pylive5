import asyncio
from textwrap import dedent
from typing import Iterable, Any
from qasync import QEventLoop, asyncSlot
from qdageditor5.core.item_data_roles import NodeDataRole
from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel, 
    NodeName,
    CellIdx,
    InletName,
    OutletName,
    DirectionalLinkId
)

import networkx as nx
from qtpy.QtCore import QAbstractListModel, QPointF, Qt, QObject
from qtpy.QtGui import QColor


from qdageditor5.views.node_inspector_delegate import NodeInspectorDelegate
from myqtx.widgets.coloredit import ColorEdit
from qtpy.QtWidgets import QAbstractScrollArea, QDialog, QListView, QSizePolicy, QSplitter, QWidget

from typing import Any, Callable, Iterable, Mapping

from graphcook.core.cache import MemoryCache
import concurrent.futures
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
    ProviderStatus
)
from graphcook.eager_observable_engine import OperatorSignature

import logging

from qtpy.QtCore import Signal, Slot
from qtpy.QtWidgets import QPlainTextEdit


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
    def __init__(self, parent: QObject|None = None):
        super().__init__(parent=parent)
        self._graph = Graph[NodeId]()
        self._node_status: Mapping[NodeId, NodeStatus] = {}

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

    def addNode(self, operator: OperatorHandle|None = None) -> NodeName|None:
        from unique_names_generator import get_random_name
        node_id = get_random_name()
        self._beginAddNodes([node_id])
        self._graph.add_node(node_id, 
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
        node_data: Mapping[str, Any] = self._graph.attributes(self.mapToSource(node_name))
        node_status = self._node_status.get(self.mapToSource(node_name), DirtyStatus())
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
        node_data: Mapping[str, Any] = self._graph.attributes(self.mapToSource(node))
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
        node_data: Mapping[str, Any] = self._graph.attributes(self.mapToSource(node))
        match role:
            case Qt.ItemDataRole.DisplayRole:
                if inlet in node_data:
                    return str(node_data[inlet])
                else:
                    return self.EMPTY

            case Qt.ItemDataRole.EditRole:
                return node_data.get(inlet, self.EMPTY)
            
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

    def closeEvent(self, event):
        self._unsubscribe()
        super().closeEvent(event)

from qtpy.QtWidgets import QDockWidget, QMainWindow, QSplitter
from qtpy.QtCore import QStringListModel
from qtpy.QtCore import Qt
from qdageditor5.views.node_inspector_view import NodeInspectorView
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5
from myqtx.selection_dialog_view import SelectionDialog

from threading import Thread
from queue import Queue
class Worker(Thread):
    def __init__(self):
        super().__init__()
        self._tasks = Queue()
        self.cache = MemoryCache()

    def run(self) -> None:
        while True:
            task = self._tasks.get()

            if task is None:
                break

            operation, future, *args = task

            if not future.set_running_or_notify_cancel():
                continue

            match operation:
                case "execute_script":
                    worker_logger.info("Executing script")

                    try:
                        operators = _execute_provider(args[0])
                    except BaseException as exc:
                        worker_logger.exception("Script execution failed")
                        future.set_exception(exc)
                    else:
                        worker_logger.info("Loaded %d operators", len(operators))
                        future.set_result(operators)

                case _:
                    future.set_exception(
                        RuntimeError(f"Unknown operation: {operation}")
                    )

    def close(self):
        # signal the thread to exit
        self._tasks.put(None)
        self.join()

    async def execute_script(self, script:str):
        from concurrent.futures import Future
        future = Future()
        self._tasks.put(('execute_script', future, script))
        return await asyncio.wrap_future(future)

from QtScriptEditorAdvanced import ScriptEditAdvanced
class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.operator_list_model = QStringListModel([])
        self.model = AsyncEagerGraphModel()

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

    @asyncSlot()
    async def submit_execute_script(self) -> None:
        document = self.script_editor.document()
        if document is None:
            return

        script_text = document.toPlainText()

        try:
            operators = await self.worker.execute_script(script_text)
        except Exception as exc:
            # Incomplete code is expected while typing.
            # print(f"Script execution failed: {exc}")
            return

        # Ignore this result if the script changed while we were waiting.
        if document.toPlainText() != script_text:
            return

        self.operator_list_model.setStringList(
            [handle.name for handle in operators]
        )

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