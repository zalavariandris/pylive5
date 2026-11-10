from typing import Iterable, Any

from graphcook.observable_graph import ObservableGraph
from graphcook.eager_engine import EagerEngine
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5
from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel, 
    CellIdx,
    DirectionalLinkId, 
    NodeName, 
    InletName,
    OutletName
)

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QMainWindow

class GraphCookModel(AbstractDAGModel):
    def __init__(self, graph: ObservableGraph, parent=None):
        super().__init__(parent=parent)
        self.graph = graph

    def nodes(self) -> Iterable[NodeName]:
        for node in self.graph.nodes:
            yield node

    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return self.graph.a
        return None

    def nodeCellCount(self, node: NodeName) -> int:
        return 0

    def nodeCellData(self, node: NodeName, column: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        ...

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        pass

    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        ...

    def outletData(self, node: NodeName, outlet: OutletName, role:int) -> Any:
        ...

    def inLinks(self, target_node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        ...

    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        ...

    def links(self) -> Iterable[DirectionalLinkId]:
        ...

    def linkSource(self, link: DirectionalLinkId) -> tuple[NodeName,OutletName]:
        ...

    def linkTarget(self, link: DirectionalLinkId) -> tuple[NodeName,InletName]:
        ...



class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        engine = EagerEngine()
        self.graph = ObservableGraph()
        self.model = GraphCookModel(self.graph)
        self.editor = DirectionalGraphView5()
        self.editor.setModel(self.model)
        self.setCentralWidget(self.editor)

if __name__ == "__main__":
    app = QApplication([])
    window = Window()
    window.show()
    app.exec()