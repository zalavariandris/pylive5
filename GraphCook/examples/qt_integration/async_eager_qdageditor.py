from typing import Iterable, Any

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
from qtpy.QtCore import QPointF, Qt, QObject
from qtpy.QtGui import QColor


from qdageditor5.views.node_inspector_delegate import NodeInspectorDelegate
from myqtx.widgets.coloredit import ColorEdit
from qtpy.QtWidgets import QDialog, QSplitter, QWidget

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


class AsyncEagerDGraphModel(AbstractDAGModel):
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


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.model = AsyncEagerDGraphModel()
        self.operator_list_model = QStringListModel(["A", "B", "C"])
        self.selection = GraphSelectionModel(self.model)
        splitter = QSplitter()
        self.setCentralWidget(splitter)
        self.editor1 = DirectionalGraphView5()
        splitter.addWidget(self.editor1)
        # self.editor2 = DirectionalGraphView5()
        # splitter.addWidget(self.editor2)

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

        

    def new_node(self, scene_pos, source, editor):
        if scene_pos is None:
            viewport_center = QPointF(editor.contentsRect().center())
            scene_pos = editor.mapToScene(viewport_center)

        dialog = SelectionDialog(self.operator_list_model, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                operator_name = selected_index.data(Qt.ItemDataRole.DisplayRole)
                new_node = self.model.addNode(operator_name)
                editor.setNodePosition(new_node, scene_pos)

        finally:
            dialog.deleteLater()

if __name__ == "__main__":
    import sys
    from qtpy.QtWidgets import QApplication

    app = QApplication(sys.argv)
    editor = Window()
    editor.show()
    sys.exit(app.exec())