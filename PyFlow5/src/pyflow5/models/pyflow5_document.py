import json
import math
from pathlib import Path
from textwrap import dedent
import traceback
from typing import Iterable

from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import QModelIndex, QObject, QPointF, Signal, Slot

import pygraphrt as rt


from .modules_operator_tree_model import ModulesOperatorsTreeModel
from .pygraphrt_graphmodel import PyGraphRTGraphModel
from .pygraphrt_node_inlet_tree_model_adapter import PyGraphRTNodeInletTreeModelAdapter

class PyFlowDocument(QObject):
    nodesInvalidated = Signal(list)
    isModifiedChanged = Signal(bool)

    def __init__(self, 
        engine: rt.GraphEvaluatorEngine|None=None,
        file: Path|None=None,
        parent:QObject|None=None
    ):
        super().__init__(parent=parent)
        self._file = file
        self._modification_time = None
        self._is_modified = False
        if self._file is not None and self._file.exists():
            self._modification_time = self._file.stat().st_mtime

        # RT
        self._engine = engine or rt.GraphEvaluatorEngine(backend=rt.InlineExecutionBackend())

        # Models
        ## Graph Model
        self.graph_model = PyGraphRTGraphModel(self._engine)
        self._engine._invalidator.nodes_invalidated.connect(
            lambda nodes: self.nodesInvalidated.emit([self.graph_model.mapFromSource(node_ref) for node_ref in nodes])
        )

        ## Modules Model
        self.modules_model = ModulesOperatorsTreeModel()
        self.modules_model.setSourceRegistry(self._engine._registry)

        # Adapters
        ## Node inlet tree adapter
        self.node_inlet_tree_adapter = PyGraphRTNodeInletTreeModelAdapter(self.graph_model)
        
        # Initial evaluation
        self._engine.request(*self._engine._graph.nodes())

        # track modification
        modification_signals = [
            self.graph_model.nodesAdded,
            self.graph_model.nodesRemoved,
            self.graph_model.nodesDataChanged,
            self.graph_model.nodeMoved,
            self.graph_model.inletsReset,
            self.graph_model.inletDataChanged,
            self.graph_model.outletsReset,
            self.graph_model.linksAdded,
            self.graph_model.linksRemoved,
            self.graph_model.linksReset,
            self.graph_model.modelReset,
            self.graph_model.cellsInserted,
            self.graph_model.cellsRemoved,
            self.graph_model.cellsDataChanged,

            self.modules_model.modelReset,
            self.modules_model.rowsInserted,
            self.modules_model.rowsRemoved,
            self.modules_model.rowsMoved,
            self.modules_model.dataChanged
        ]
        for signal in modification_signals:
            signal.connect(lambda: self._set_modified(True))

    def _set_modified(self, modified: bool) -> None:
        self._is_modified = modified
        self.isModifiedChanged.emit(modified)

    def file(self) -> Path|None:
        return self._file

    def requestNodeExecution(self, node_name: NodeName) -> None:
        node_rt = self.graph_model.mapToSource(node_name)
        if node_rt is not None:
            self._engine.request(node_rt)

    def close(self) -> None:
        """Stop evaluation and disconnect requests from the graph model."""
        self.graph_model.close()
        self._engine.close()

    def getNodeOperator(self, node_name: NodeName) -> QModelIndex:
        node_ref = self.graph_model.mapToSource(node_name)
        if node_ref is None:
            return QModelIndex()
        
        operator = node_ref.get_operator()
        if operator is None:
            return QModelIndex()

        operator_index = self.modules_model.mapFromSource(operator)
        return operator_index

    # Serialization
    @classmethod
    def fromfile(cls, file_path: str | Path) -> "PyFlowDocument":
        path = Path(file_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        deserializer = rt.GraphDeserializer(base_dir=path.parent)
        registry, graph = deserializer.fromdict(data)
        doc = cls(engine=rt.GraphEvaluatorEngine(graph=graph, registry=registry), file=path)
        return doc

    def save(self, *, file:Path|None=None, override: bool = True) -> None:
        """Save the runtime and node positions as UTF-8 JSON."""
        if file is not None:
            self._file = file
            
        if self._file is None:
            raise ValueError("No file specified for saving the document.")

        if not override and self._file.exists():
            if self._modification_time != self._file.stat().st_mtime:
                raise RuntimeError("The file has been modified externally.")
        
        serializer = rt.GraphSerializer(self._engine._graph, self._engine._registry)
        data = serializer.todict()

        # inject position
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = self.graph_model.nodePosition(name)
            record["position"] = [position.x(), position.y()]

        text = json.dumps(data, indent=4)
        Path(self._file).write_text(text, encoding="utf-8")

    # Editing
    def createNewNode(self, operator_index:QModelIndex, scene_pos:QPointF|None=None):
        assert operator_index.isValid(), "Operator index must be valid."
        assert operator_index.model() is self.modules_model, "Operator index must belong to the modules model."
        selected_op_ref = operator_index.data(ModulesOperatorsTreeModel.OperatorRole)
        if selected_op_ref:
            self.graph_model.addNode(selected_op_ref, scene_pos or QPointF(0, 0))

    def deleteNodes(self, node_names: Iterable[NodeName]) -> None:
        self.graph_model.removeNodes(node_names)

    def restart_graph(self):
        """Recover the model/view while preserving the current runtime and script."""
        # todo: this needs to be reimplemented
        self.graph_model.reset_graph_from_scratch()
