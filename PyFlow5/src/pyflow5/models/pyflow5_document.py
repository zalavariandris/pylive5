import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import QModelIndex, QObject, QPointF, Signal, Property
from qtpy.QtGui import QTextDocument

import pygraphrt2 as rt2
from pygraphrt2.engine_serializer import FORMAT_VERSION

from ..core.file_io import write_text_atomic

from .operators_model import OperatorsModel
from .pygraphrt_graphmodel import PyGraphRTGraphModel
from .pygraphrt_node_inlet_tree_model_adapter import PyGraphRTNodeInletTreeModelAdapter
from qtpy.QtWidgets import QPlainTextDocumentLayout

@dataclass(frozen=True)
class FileStamp:
    """The file state against which the next save checks for external edits."""

    st_mtime_ns: int
    st_size: int

    @classmethod
    def fromStat(cls, stat: os.stat_result) -> "FileStamp":
        return cls(stat.st_mtime_ns, stat.st_size)


class FileChangedError(RuntimeError):
    """Saving requires confirmation because the bound file changed."""



class PyFlowDocument(QObject):
    nodesInvalidated = Signal(list)
    modified = Signal()
    isModifiedChanged = Signal(bool)
    filePathChanged = Signal(object)
    scriptStateChanged = Signal()

    def __init__(self, 
        engine: rt2.Engine|None=None,
        file: Path|None=None,
        parent:QObject|None=None
    ) -> None:
        super().__init__(parent=parent)
        self._filepath = Path(file).resolve() if file is not None else None
        self._filestat: FileStamp | None = None
        self._is_modified = False
        self._closed = False

        if self._filepath is not None and self._filepath.exists():
            self._filestat = FileStamp.fromStat(self._filepath.stat())

        # RT
        self._engine = engine or rt2.Engine()
        self._engine.set_auto_execute_targets([])
        self.script_document: QTextDocument = QTextDocument(self)
        self.script_document.setDocumentLayout(
            QPlainTextDocumentLayout(self.script_document)
        )
        self.script_document.setPlainText(self._engine.registry.get_script())

        # Models
        ## Graph Model
        self.graph_model = PyGraphRTGraphModel(self._engine)
        ## Modules Model
        self.operators_model = OperatorsModel()
        self.operators_model.setSourceRegistry(self._engine.registry)

        # Adapters
        ## Node inlet tree adapter
        self.node_inlet_tree_adapter = PyGraphRTNodeInletTreeModelAdapter(self.graph_model)
        
        self._connections = [
            (self.script_document.contentsChanged, self._onScriptChanged),
            # (self._engine.registry_invalidated, self._engine.evaluate_registry),
            (self._engine.registry.stateChanged, self.scriptStateChanged.emit),
            (self._engine.nodes_invalidated, self._onNodesInvalidated),
            (self._engine.graph.nodes_added, self._markModified),
            (self._engine.graph.nodes_removed, self._markModified),
            (self._engine.graph.nodes_changed, self._markModified),
            (self.graph_model.nodeMoved, self._markModified),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)
        # self._engine.execute(*self._engine.graph.nodes())

        self._engine.nodes_executed.connect(lambda: print("nodes executed"))

    def _onScriptChanged(self) -> None:
        source = self.script_document.toPlainText()
        if not self._closed and source != self._engine.registry.get_script():
            self._markModified()
            self._engine.registry.set_script(source)

    def _onNodesInvalidated(self, nodes: list[rt2.NodeRef]) -> None:
        if not self._closed:
            self.nodesInvalidated.emit([node.name() for node in nodes])

    def scriptState(self) -> str | Exception | None:
        return self._engine.registry.get_state()

    def _markModified(self, *_args: object) -> None:
        """Mark the document as modified."""
        if not self._closed:
            self.setModified(True)
            self.modified.emit()

    def isModified(self) -> bool:
        return self._is_modified

    def setModified(self, modified: bool) -> None:
        if modified != self._is_modified:
            self._is_modified = modified
            self.isModifiedChanged.emit(modified)

    def filePath(self) -> Path|None:
        return self._filepath

    def fileStat(self) -> FileStamp | None:
        return self._filestat

    def restoreFileBinding(self, path: Path | None, stat: FileStamp | None) -> None:
        """Restore session metadata without treating today's file as the baseline."""
        self._filepath = path.resolve() if path is not None else None
        self._filestat = stat if path is not None else None
        self.filePathChanged.emit(self._filepath)

    def setAutoExecuteTargets(
        self, node_names: Iterable[NodeName] | None
    ) -> None:
        """Set the nodes to be automatically executed by the engine.
        node_names: Iterable[NodeName] | None
            if None, all nodes are watched automatically.
            empty iterable disables auto-execution for all nodes.
        """
        if self._closed:
            return

        if node_names is None:
            self._engine.set_auto_execute_targets(None)
            return

        targets: list[rt2.NodeRef] = []
        for name in node_names:
            node = self.graph_model.mapToSource(name)
            if node is not None:
                targets.append(node)

        self._engine.set_auto_execute_targets(targets)

    def requestNodeExecution(self, node_name: NodeName) -> None:
        node_rt = self.graph_model.mapToSource(node_name)
        if node_rt is not None:
            self._engine.execute_nodes(node_rt)

    def close(self) -> None:
        """Stop evaluation and disconnect requests from the graph model."""
        if self._closed:
            return
        self._closed = True
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self.operators_model.setSourceRegistry(None)
        self.graph_model.close()
        self._engine.close()

    def getNodeOperator(self, node_name: NodeName) -> QModelIndex:
        node_ref = self.graph_model.mapToSource(node_name)
        if node_ref is None:
            return QModelIndex()

        node_state = node_ref.resolve()
        operator = node_state.operator
        if operator is None:
            return QModelIndex()

        operator_index = self.operators_model.mapFromSource(operator)
        return operator_index


    # Serialization
    @classmethod
    def open(cls, file_path: str | Path) -> "PyFlowDocument":
        path = Path(file_path).resolve()
        with path.open(encoding="utf-8") as stream:
            jsontext = stream.read()
            stat = FileStamp.fromStat(os.fstat(stream.fileno()))
        doc = cls.deserialize(jsontext)
        doc.restoreFileBinding(path, stat)
        return doc

    @classmethod
    def deserialize(cls, jsontext: str) -> "PyFlowDocument":
        data = json.loads(jsontext)
        if not isinstance(data, dict):
            raise ValueError("A graph document must be an object.")
        if type(data.get("version")) is not int or data["version"] != FORMAT_VERSION:
            raise ValueError(f"Unsupported graph format; expected version {FORMAT_VERSION}. got: {data.get('version')!r}")
        if (
            not isinstance(data.get("graph"), dict)
            or not isinstance(data.get("script"), dict)
        ):
            raise ValueError("A graph document must contain graph and script objects.")
        records = data["graph"].get("nodes", {})
        if not isinstance(records, dict):
            raise ValueError("Graph nodes must be an object.")
        positions: dict[str, QPointF] = {}
        for name, record in records.items():
            if not isinstance(record, dict):
                raise ValueError(f"Invalid node record: {name!r}")
            position = record.get("position", [0, 0])
            if (
                not isinstance(position, list) or len(position) != 2
                or any(
                    type(value) not in (int, float) or not math.isfinite(value)
                    for value in position
                )
            ):
                raise ValueError(f"Invalid position for node {name!r}")
            positions[name] = QPointF(*position)
        deserializer = rt2.GraphDeserializer()
        registry, graph = deserializer.fromdict(data)
        engine = rt2.Engine(graph=graph, registry=registry)
        doc = None
        try:
            doc = cls(engine=engine)
            for name, position in positions.items():
                doc.graph_model.setNodePosition(name, position)
            doc.setModified(False)
        except Exception:
            if doc is not None:
                doc.close()
            else:
                engine.close()
            raise
        return doc

    def serialize(self) -> str:
        serializer = rt2.GraphSerializer(self._engine.graph, self._engine.registry)
        data = serializer.todict()

        # inject position
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = self.graph_model.nodePosition(name)
            if not math.isfinite(position.x()) or not math.isfinite(position.y()):
                raise ValueError(f"Invalid position for node {name!r}")
            record["position"] = [position.x(), position.y()]

        text = json.dumps(data, indent=4)
        return text

    def save(self, *, override: bool = False) -> None:
        """Save the runtime and node positions as UTF-8 JSON."""
        if self._filepath is None:
            raise ValueError("document has no file path specified.")

        self._saveTo(self._filepath, override=override)

    def saveAs(self, file_path: str | Path, override: bool = True) -> None:
        self._saveTo(Path(file_path).resolve(), override=override)

    def _saveTo(self, path: Path, *, override: bool) -> None:
        text = self.serialize()
        if not override:
            try:
                current_stat = FileStamp.fromStat(path.stat())
            except FileNotFoundError:
                current_stat = None
            expected_stat = self._filestat if path == self._filepath else None
            if current_stat != expected_stat:
                raise FileChangedError(f"The file '{path}' has changed externally.")
        written_stat = write_text_atomic(path, text)
        self.restoreFileBinding(path, FileStamp.fromStat(written_stat))
        self.setModified(False)


    # Editing
    def createNewNode(self, operator_index: QModelIndex, scene_pos: QPointF | None = None) -> None:
        assert operator_index.isValid(), "Operator index must be valid."
        assert operator_index.model() is self.operators_model, "Operator index must belong to the operators model."
        selected_op_ref = self.operators_model.mapToSource(operator_index)
        if selected_op_ref:
            self.graph_model.addNode(selected_op_ref, scene_pos or QPointF(0, 0))

    def deleteNodes(self, node_names: Iterable[NodeName]) -> None:
        self.graph_model.removeNodes(node_names)

    def restart_graph(self) -> None:
        """Recover the model/view while preserving the current runtime and script."""
        self.graph_model.reset_graph_from_scratch()
        self._engine.evaluate_registry()
