import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import QModelIndex, QObject, QPointF, Signal

import pygraphrt as rt

from ..core.file_io import write_text_atomic

from .modules_operator_tree_model import ModulesOperatorsTreeModel
from .pygraphrt_graphmodel import PyGraphRTGraphModel
from .pygraphrt_node_inlet_tree_model_adapter import PyGraphRTNodeInletTreeModelAdapter


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

    def __init__(self, 
        engine: rt.GraphEvaluatorEngine|None=None,
        file: Path|None=None,
        parent:QObject|None=None
    ) -> None:
        super().__init__(parent=parent)
        self._filepath = Path(file).resolve() if file is not None else None
        self._filestat: FileStamp | None = None
        self._is_modified = False
        self._closed = False
        self._tracked_modules: set[rt.ScriptModuleRT] = set()
        if self._filepath is not None and self._filepath.exists():
            self._filestat = FileStamp.fromStat(self._filepath.stat())

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

        # Observe persisted content, not view refreshes or evaluation results.
        for signal in (
            self._engine._graph.nodes_added,
            self._engine._graph.nodes_removed,
            self._engine._graph.nodes_changed,
            self.graph_model.nodeMoved,
        ):
            signal.connect(self._markModified)
        self._engine._registry.modules_added.connect(self._onModulesAdded)
        self._engine._registry.modules_removed.connect(self._onModulesRemoved)
        self._trackModules(self._engine._registry.modules())

    def _markModified(self, *_args: object) -> None:
        if not self._closed:
            self.setModified(True)
            self.modified.emit()

    def _trackModules(self, modules: Iterable[rt.ScriptModuleRT]) -> None:
        for module in modules:
            if isinstance(module, rt.ImportModuleRT) or module in self._tracked_modules:
                continue
            module.script_changed.connect(self._markModified)
            self._tracked_modules.add(module)

    def _onModulesAdded(self, modules: list[rt.ScriptModuleRT]) -> None:
        self._trackModules(modules)
        self._markModified()

    def _onModulesRemoved(self, modules: list[rt.ScriptModuleRT]) -> None:
        for module in modules:
            if module in self._tracked_modules:
                module.script_changed.disconnect(self._markModified)
                self._tracked_modules.remove(module)
        self._markModified()

    def filePath(self) -> Path|None:
        return self._filepath

    def fileStat(self) -> FileStamp | None:
        return self._filestat

    def restoreFileBinding(self, path: Path | None, stat: FileStamp | None) -> None:
        """Restore session metadata without treating today's file as the baseline."""
        self._filepath = path.resolve() if path is not None else None
        self._filestat = stat if path is not None else None
        self.filePathChanged.emit(self._filepath)

    def requestNodeExecution(self, node_name: NodeName) -> None:
        node_rt = self.graph_model.mapToSource(node_name)
        if node_rt is not None:
            self._engine.request(node_rt)

    def close(self) -> None:
        """Stop evaluation and disconnect requests from the graph model."""
        if self._closed:
            return
        self._closed = True
        for module in self._tracked_modules:
            module.script_changed.disconnect(self._markModified)
        self._tracked_modules.clear()
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

    def isModified(self) -> bool:
        return self._is_modified

    def setModified(self, modified: bool) -> None:
        if modified != self._is_modified:
            self._is_modified = modified
            self.isModifiedChanged.emit(modified)

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
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int or data["version"] != 3
        ):
            raise ValueError("Unsupported graph format; expected version 3.")
        if (
            not isinstance(data.get("graph"), dict)
            or not isinstance(data.get("modules", {}), dict)
        ):
            raise ValueError("A graph document must contain graph and module objects.")
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
        deserializer = rt.GraphDeserializer()
        registry, graph = deserializer.fromdict(data)
        engine = rt.GraphEvaluatorEngine(graph=graph, registry=registry)
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
        serializer = rt.GraphSerializer(self._engine._graph, self._engine._registry)
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
