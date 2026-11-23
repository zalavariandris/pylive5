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
from qtpy.QtCore import Qt, QObject
from qtpy.QtGui import QColor


from qdageditor5.views.node_inspector_delegate import NodeInspectorDelegate
from myqtx.widgets.coloredit import ColorEdit
from qtpy.QtWidgets import QSplitter, QWidget

class StandardNodeInspectorDelegate(NodeInspectorDelegate):
    def createEditor(self, model:AbstractDAGModel, node: NodeName, inlet: InletName) -> QWidget:
        value = model.inletData(node, inlet, Qt.ItemDataRole.EditRole)
        if isinstance(value, QColor):
            editor = ColorEdit()
        else:
            editor = super().createEditor(model, node, inlet)
        return editor


class NXDagModel(AbstractDAGModel):
    EMPTY = None
    def __init__(self, parent: QObject|None = None):
        super().__init__(parent=parent)
        self._graph = nx.MultiDiGraph()

    # READ
    def nodes(self) -> Iterable[NodeName]:
        for node in self._graph.nodes():
            yield node

    def addNode(self) -> NodeName|None:
        from unique_names_generator import get_random_name
        node_id = get_random_name()
        self._beginAddNodes([node_id])
        self._graph.add_node(node_id, 
            label="-label-",
            footer="-footer-",
            fg=QColor(220, 40, 240),
            bg=QColor(20, 200, 200)
        )
        self._endAddNodes()
        return node_id

    def nodeHeaderData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return f"{node_name}"
        return None

    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return f"{self._graph.nodes[node_name].get('label')}"
            
            case Qt.ItemDataRole.ForegroundRole:
                if 'fg' in self._graph.nodes[node_name]:
                    return self._graph.nodes[node_name]['fg']
                
            case Qt.ItemDataRole.BackgroundRole:
                if 'bg' in self._graph.nodes[node_name]:
                    return self._graph.nodes[node_name]['bg']
                    
            case NodeDataRole.TrailingRole:
                return self._graph.nodes[node_name].get('footer')
                    
        return None

    def nodeCellCount(self, node: NodeName) -> int:
        return 0

    def nodeCellData(self, node: NodeName, column: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        for key, value in self._graph.nodes[node].items():
            yield key

    def inletHeaderData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return str(inlet)
            case _:
                return None

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                if inlet in self._graph.nodes[node]:
                    return str(self._graph.nodes[node][inlet])
                else:
                    return self.EMPTY

            case Qt.ItemDataRole.EditRole:
                return self._graph.nodes[node].get(inlet, self.EMPTY)
            
            case _:
                return None

    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        return ['out']

    def outletData(self, node: NodeName, outlet: OutletName, role:int) -> Any:
        return None

    def inLinks(self, target_node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._graph.in_edges(target_node, keys=True):
            if key == inlet:
                yield (src, 'out', dst, key)

    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._graph.out_edges(source_node, keys=True):
            if outlet == 'out':
                yield (src, 'out', dst, key)

    def links(self) -> Iterable[DirectionalLinkId]:
        for src, dst, key in self._graph.edges(keys=True):
            yield (src, 'out', dst, key)

    # update
    def removeNodes(self, nodes: Iterable[NodeName]) -> bool:
        self._beginRemoveNodes(nodes)
        self._graph.remove_nodes_from(nodes)
        self._endRemoveNodes()
        return True

    def addLinks(self, links:Iterable[DirectionalLinkId]) -> bool:
        self._beginAddLinks(links)
        for link in links:
            src, outlet, dst, inlet = link
            self._graph.add_edge(src, dst, key=inlet)

        self._endAddLinks()
        return True

    def removeLinks(self, links) -> bool:
        self._beginRemoveLinks(links)
        for link in links:
            src, outlet, dst, inlet = link
            self._graph.remove_edge(src, dst, key=inlet)

        self._endRemoveLinks()
        return True

    def setInletData(self, node: NodeName, inlet: InletName, value: Any, role: int) -> bool:
        if role == Qt.ItemDataRole.EditRole:
            if value is self.EMPTY:
                del self._graph.nodes[node][inlet]
                self.inletDataChanged.emit(node, tuple([inlet]), [])
                return True
            else:
                self._graph.nodes[node][inlet] = value
                self.inletDataChanged.emit(node, tuple([inlet]), [])
                return True

        return False

    def closeEvent(self, event):
        self._unsubscribe()
        super().closeEvent(event)

from qtpy.QtWidgets import QDockWidget, QMainWindow
from qtpy.QtCore import Qt
from qdageditor5.views.node_inspector_view import NodeInspectorView
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.model = NXDagModel()
        self.selection = GraphSelectionModel(self.model)
        splitter = QSplitter()
        self.setCentralWidget(splitter)
        self.editor1 = DirectionalGraphView5()
        splitter.addWidget(self.editor1)
        self.editor2 = DirectionalGraphView5()
        splitter.addWidget(self.editor2)

        self.inspector = NodeInspectorView()
        self.inspector._delegate = StandardNodeInspectorDelegate()
        dockwidget = QDockWidget()
        dockwidget.setWidget(self.inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dockwidget)

        self.editor1.setModel(self.model)
        self.editor1.setSelectionModel(self.selection)
        self.editor1.requestNode.connect(lambda pos, source, editor=self.editor1: 
            self.new_node(pos, source, editor))
        self.editor1.requestLink.connect(lambda src, outlet, dst, inlet: 
            self.model.addLinks([(src, outlet, dst, inlet)]))
        self.editor2.setModel(self.model)
        self.editor2.setSelectionModel(self.selection)
        self.editor2.requestNode.connect(lambda pos, source, editor=self.editor2: 
            self.new_node(pos, source, editor))
        self.editor2.requestLink.connect(lambda src, outlet, dst, inlet: 
            self.model.addLinks([(src, outlet, dst, inlet)]))
        
        self.inspector.setModel(self.model)
        self.selection.currentNodeChanged.connect(
            lambda current, previous: self.inspector.setCurrentNode(current))

    def new_node(self, pos, source, editor):
        nodename = self.model.addNode()
        editor.setNodePosition(nodename, pos)

if __name__ == "__main__":
    import sys
    from qtpy.QtWidgets import QApplication

    app = QApplication(sys.argv)
    editor = Window()
    editor.show()
    sys.exit(app.exec())