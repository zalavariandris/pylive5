from textwrap import dedent
from typing import Callable, Iterable, Any, Protocol, TypedDict


from graphcook.observable_graph import ObservableGraph, GraphChange
from graphcook.eager_engine import OperatorHandle
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

from graphcook.core.base_engine import (
    OperatorHandle
)

from qtpy.QtCore import QPointF, Qt
from qtpy.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QListView, QMainWindow, QPlainTextEdit, QSizePolicy, QSplitter, QVBoxLayout, QWidget
from graphcook.eager_engine import NodeId

# define engine contracts for the view
class NodeSignatureProtocol(TypedDict):
    operator: OperatorHandle
    inlets: list[str]

class EngineGraphProtocol(Protocol):
    # read
    def nodes(self) -> Iterable['NodeId']:
        ...

    def attributes(self, node: 'NodeId') -> NodeSignatureProtocol:
        ...

    def in_links(self, node: 'NodeId') -> Iterable[tuple['NodeId', 'NodeId', str]]:
        ...

    def out_links(self, node: 'NodeId') -> Iterable[tuple['NodeId', 'NodeId', str]]:
        ...

    def links(self) -> Iterable[tuple['NodeId', 'NodeId', str]]:
        ...

    # update
    def add_link(self, src: 'NodeId', dst: 'NodeId', inlet: str) -> None:
        ...

    # # observe
    # def listen(self, callback: callable[[GraphChange], None]) -> None:
    #     ...

class ProviderProtocol(Protocol):
    # read
    def operators(self) -> Iterable['OperatorHandle']:
        ...

class ObservableProtocol(Protocol):
    def listen(self, callback: Callable[[GraphChange], None]) -> None:
        ...

class EagerEngineProtocol(EngineGraphProtocol, ProviderProtocol, ObservableProtocol, Protocol):
    def script(self) -> str: ...
    def set_script(self, script: str) -> None: ...


# implement models
class EagerGraphModel(AbstractDAGModel):
    def __init__(self, engine: EagerEngineProtocol, parent=None):
        super().__init__(parent=parent)
        self.engine = engine

    def mapFromSource(self, node: 'NodeId')->NodeName:
        return node

    def mapToSource(self, node: NodeName) -> 'NodeId':
        return node

    # READ
    def nodes(self) -> Iterable[NodeName]:
        for node in self.engine.nodes():
            yield node

    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        match role:
            case Qt.ItemDataRole.DisplayRole:
                node_signature = self.engine.attributes(node_name)
                match role:
                    case Qt.ItemDataRole.DisplayRole:
                        op:OperatorHandle = node_signature['operator']
                        return op.name
                    
        return None

    def nodeCellCount(self, node: NodeName) -> int:
        return 0

    def nodeCellData(self, node: NodeName, column: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        node_signature = self.engine.attributes(node)
        operator_handle = node_signature['operator']

        for inlet in node_signature['inlets']:
            yield inlet

        # Yield inlets that are connected but not defined in the operator signature
        for src, dst, inlet in self.engine.in_links(node):
            if inlet not in node_signature['inlets']:
                yield inlet

    def inletData(self, node: NodeName, inlet: InletName, role:int=Qt.ItemDataRole.DisplayRole) -> Any:
        return inlet

    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        return ['out']

    def outletData(self, node: NodeName, outlet: OutletName, role:int) -> Any:
        return None

    def inLinks(self, target_node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        for src, dst, linked_inlet in self.engine.in_links(target_node):
            if linked_inlet == inlet:
                yield (src, 'out', dst, linked_inlet)

    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        for src, dst, inlet in self.engine.out_links(source_node):
            if outlet == 'out':
                yield (src, 'out', dst, inlet)

    def links(self) -> Iterable[DirectionalLinkId]:
        for src, dst, inlet in self.engine.links():
            yield (src, 'out', dst, inlet)

    def linkSource(self, link: DirectionalLinkId) -> tuple[NodeName,OutletName]:
        src, outlet, dst, inlet = link
        return (src, outlet)

    def linkTarget(self, link: DirectionalLinkId) -> tuple[NodeName,InletName]:
        src, outlet, dst, inlet = link
        return (dst, inlet)

from qtpy.QtCore import QAbstractListModel 
from typing import Protocol


class OperatorListModel(QAbstractListModel):
    def __init__(self, engine: EagerEngineProtocol, parent=None):
        super().__init__(parent=parent)
        self.engine = engine

    def rowCount(self, parent=None) -> int:
        return len(list(self.engine.operators()))

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            all_operators = list(self.engine.operators())
            return all_operators[index.row()].name
        return None


from graphcook.eager_engine import EagerEngineChange

class ProviderView(QWidget):
    def __init__(self, engine: EagerEngineProtocol, parent=None):
        super().__init__(parent=parent)
        self.engine = engine
        layout = QHBoxLayout()
        self.setLayout(layout)

        self.script_view = QPlainTextEdit()
        self.script_view.setPlainText(self.engine.script())
        self.script_view.textChanged.connect(self._handle_editor_text_changed)

        engine.listen(self._handle_engine_change)
        layout.addWidget(self.script_view)
        self.list_view = QListView()
        layout.addWidget(self.list_view)
        self.model = OperatorListModel(self.engine)
        self.list_view.setModel(self.model)
        self.list_view.setSizePolicy(
            QSizePolicy.Policy.Minimum, 
            QSizePolicy.Policy.Expanding
        )

    def _handle_engine_change(self, engine_change:EagerEngineChange):
        if engine_change.script is not None:
            if self.script_view.toPlainText() != engine_change.script.new:
                self.script_view.setPlainText(engine_change.script.new)

    def _handle_editor_text_changed(self):
        new_text = self.script_view.toPlainText()
        if new_text != self.engine.script():
            self.engine.set_script(new_text)

from myqtx.selection_dialog_view import SelectionDialog

class EngineWindow(QMainWindow):
    def __init__(self, engine: EagerEngineProtocol):
        super().__init__()
        self.setWindowTitle("Eager QDAG Editor")
        self._statusbar = self.statusBar() # ensure statusbar
        self.engine = engine

        self.engine.listen(self._handle_engine_change)

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
        self.editor2 = DirectionalGraphView5()
        self.editor2.requestNode.connect(lambda scene_pos, source: 
                self._handle_node_request(scene_pos=scene_pos, source=source)
            )
        self.editor2.requestLink.connect(lambda source, outlet, target, inlet:
            self._handle_link_request(source, outlet, target, inlet)
        )
        self.viewer = QLabel("Viewer")

        splitter = QSplitter()
        splitter.addWidget(self.provider_pane)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.editor2)
        splitter.addWidget(self.viewer)
        splitter.setSizes([600, 600, 600])
        self.resize(2000, 650)
        self.setCentralWidget(splitter)

        # graph setup
        self.model = EagerGraphModel(self.engine)

        # bind views to models
        self.editor.setModel(self.model)
        self.editor.fitNodes()
        self.editor2.setModel(self.model)
        self.editor2.fitNodes()

        self.operator_list_model = OperatorListModel(self.engine)
        self.operator_list.setModel(self.operator_list_model)

    def _handle_engine_change(self, change: EagerEngineChange):
        self._statusbar.showMessage("Engine changed", 2000)

    def _handle_node_request(self, *, scene_pos:QPointF|None=None, source:NodeName|None=None) -> None:
        if scene_pos is None:
            viewport_center = QPointF(self.editor.contentsRect().center())
            scene_pos = self.editor.mapToScene(viewport_center)

        dialog = SelectionDialog(self.operator_list_model, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                operator_name = selected_index.data(Qt.ItemDataRole.DisplayRole)
                new_node = self.engine.node(operator_name)
                self.editor.setNodePosition(new_node, scene_pos)

        finally:
            dialog.deleteLater()

    def _handle_link_request(
        self, source: NodeName, outlet: OutletName, target: NodeName, inlet: InletName,
    ) -> None:
        try:
            self.engine.add_link(source, target, inlet)
        except ValueError as error:
            self.statusBar().showMessage(f"Cannot connect: {error}", 5000)
        else:
            self.statusBar().clearMessage()

if __name__ == "__main__":
    app = QApplication([])
    engine = EagerEngine(dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello_world(name:str, greeting:str="Hello"):
            return f"{greeting}, {name}!"
    """))
    the_name = engine.node("the_name")
    the_greeting = engine.node("the_greeting")
    hello_world = engine.node("hello_world")
    engine.add_link(the_name, hello_world, 'name')
    window = EngineWindow(engine)
    window.show()
    app.exec()
