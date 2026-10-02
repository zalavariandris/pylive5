"""A tree projection of one graphmodel."""
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from .inspector_roles import InspectorRole, UNSET
from pygraphrt.abstract_operator import ParameterData
from qdageditor5.models.abstract_dag_model import InletName, NodeName
from qtpy.QtCore import QAbstractItemModel, QAbstractListModel, QModelIndex, Qt
# from .pygraphrt_model import PyFlowRTModel

import pygraphrt as rt

@dataclass
class _OperatorShadow:
    rt: rt.OperatorRef

@dataclass
class _InputShadow:
    location: int|str
    parent_node: _NodeShadow

@dataclass
class _NodeShadow:
    rt: rt.NodeRef
    operator: _OperatorShadow | None
    inlet_order: list[_InputShadow]


def consolidate_inputs_and_parameters(node_rt: rt.NodeRef) -> Mapping[str|int, Any]:
    # TODO:
    # create a single utility to return the consolidated node inputs and operator parameters
    # todo: this could become the get_inputs in the GraphDefinition, since integer locations are not allowed for kwor arguments.
    # 

    consolidated: dict[str|int, Any] = {}
    
    # consolidate operator parameters
    args, kwargs = node_rt.get_inputs()
    op_rt = node_rt.get_operator()
    
    if op_rt is None:
        for i, val in enumerate(args):
            consolidated[i] = val
        for key, val in kwargs.items():
            consolidated[key] = val
        
    else:
        parameters:Mapping = op_rt.get_parameters()
        for i, (name, param) in enumerate(parameters.items()):
            if i<len(args):
                consolidated[i] = args[i]
            else:
                consolidated[name] = kwargs.get(name)

        # what to do when args is longer than the number of parameters
        if len(args) > len(parameters):
            for i in range(len(parameters), len(args)):
                consolidated[i] = args[i]

        # consolidate remaining keyword arguments that were not matched with parameters
        for key, val in kwargs.items():
            if key not in consolidated:
                consolidated[key] = val

    return consolidated



class NodesTreeModel(QAbstractItemModel):
    """A tree projection of one graphmodel."""

    def __init__(self, graph: rt.GraphDefinitionRT, registry:rt.ModuleRegistry, parent=None):
        super().__init__(parent)
        self._graph: rt.GraphDefinitionRT | None = None
        self._graph_connections: list[Any] = []
        self._nodes_shadow: list[_NodeShadow] = []
        self._registry = registry
        self._modules_connections: list[Any] = []
        self._setSourceEngine(graph, registry)

    def _setSourceEngine(self, graph: rt.GraphDefinitionRT, registry:rt.ModuleRegistry):
        # if self._source_graph is graph_model:
        #     return

        if self._graph is not None:
            for signal, slot in self._graph_connections:
                signal.disconnect(slot)
            self._graph_connections.clear()
            self._graph = None

        if graph is not None:
            self._graph_connections = [
                (graph.nodes_added,  self._rebuild_nodes_shadow),
                (graph.nodes_removed, self._rebuild_nodes_shadow),
                (graph.nodes_changed, self._rebuild_nodes_shadow),
            ]
            for signal, slot in self._graph_connections:
                signal.connect(slot)
            self._graph = graph

        if self._registry is not None:
            for signal, slot in self._modules_connections:
                signal.disconnect(slot)
            self._modules_connections = []

        if registry is not None:
            self._modules_connections = [
                (registry.modules_added,  self._rebuild_nodes_shadow),
                (registry.modules_removed, self._rebuild_nodes_shadow),
                (registry.operators_added,  self._rebuild_nodes_shadow),
                (registry.operators_removed, self._rebuild_nodes_shadow),
                (registry.operators_changed, self._rebuild_nodes_shadow),
            ]
            for signal, slot in self._modules_connections:
                signal.connect(slot)

        self._rebuild_nodes_shadow()

    def _rebuild_nodes_shadow(self):
        if self._graph is None:
            self.beginResetModel()
            self._nodes_shadow = []
            self.endResetModel()
        else:
            self.beginResetModel()

            self._nodes_shadow = []
            for node_ref in self._graph.nodes():
                nodeshadow = _NodeShadow(
                    rt=node_ref, 
                    operator=_OperatorShadow(rt=node_ref.get_operator()),
                    inlet_order=[]
                ) 

                if op_rt:=node_ref.get_operator():
                    for name, param in op_rt.get_parameters().items():
                        nodeshadow.inlet_order.append(
                            _InputShadow(location=name, parent_node=nodeshadow)
                        )
                else:
                    for location, val in consolidate_inputs_and_parameters(node_ref).items():
                        nodeshadow.inlet_order.append(_InputShadow(location=location, parent_node=nodeshadow))


                self._nodes_shadow.append(nodeshadow)

            self.endResetModel()

        print("Rebuilt nodes shadow: ", self._nodes_shadow)

   
    # mapping source to QModel indexes
    def index(self, row: int, column: int = 0, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            # create index for top-level node
            node_shadow = self._nodes_shadow[row]
            return self.createIndex(row, column, node_shadow)

        else:
            # create index for inlet
            node_shadow = self._nodes_shadow[parent.row()]
            inlet_shadow = node_shadow.inlet_order[row]
            return self.createIndex(row, column, inlet_shadow)

    def parent(self, index: QModelIndex) -> QModelIndex: # type: ignore
        if not index.isValid() or index.model() is not self:
            return QModelIndex()

        internal_pointer = index.internalPointer()
        match internal_pointer:
            case _NodeShadow():
                # top-level nodes have no parent
                return QModelIndex()  

            case _InputShadow():
                # inlet nodes have a parent node
                parent_node_shadow = internal_pointer.parent_node
                if parent_node_shadow is None:
                    return QModelIndex()
                node_row = self._nodes_shadow.index(parent_node_shadow)
                return self.createIndex(node_row, 0, parent_node_shadow)

            case _:
                assert False, f"Unexpected internal pointer type: {type(internal_pointer)}"
                return QModelIndex()

    # read
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if self._graph is None:
            return 0

        if parent.isValid() and parent.column() != 0:
            return 0

        handle = parent.internalPointer()

        if parent.isValid() is False:
            return len(self._nodes_shadow)
        else:
            handle = parent.internalPointer()
            match handle:
                case _NodeShadow():
                    return len(handle.inlet_order)
                case _InputShadow():
                    return 0
                case _:
                    assert False, f"Expected a _NodeHandle for a valid parent index, got {handle}"
                    pass

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section == 0:
                return "Name"
            elif section == 1:
                return "Value"
        return None

    def columnCount(self, parent: QModelIndex=QModelIndex())->int:
        return 2

    # def _mapToSource(self, index: QModelIndex) -> NodeName | tuple[NodeName, InletName] | None:
    #     if self._graph is None:
    #         return None
    #     if not index.isValid():
    #         return None
    #     internal_pointer = index.internalPointer()
    #     match internal_pointer:
    #         case _NodeShadow():
    #             return internal_pointer.name
    #         case _InputShadow():
    #             return (internal_pointer.parent_node.name, internal_pointer.name)
    #         case _:
    #             return None

    def _input_details(
        self, inlet: _InputShadow
    ) -> tuple[int | str, Any, type | None]:
        node = inlet.parent_node.rt
        args, kwargs = node.get_inputs()
        location = inlet.location
        parameter = None

        operator = node.get_operator()
        if operator is not None and isinstance(location, str):
            parameters = operator.get_parameters()
            parameter = parameters.get(location)

            if parameter is not None:
                position = list(parameters).index(location)
                if position < len(args):
                    location = position

        if isinstance(location, int):
            value = args[location]
        else:
            value = kwargs.get(location, UNSET)

        default = (
            parameter.default
            if parameter is not None
            else ParameterData._empty
        )

        annotation = (
            parameter.annotation
            if parameter is not None
            else ParameterData._empty
        )

        # Support simple postponed annotations without evaluating arbitrary text.
        if isinstance(annotation, str):
            annotation = {
                "int": int,
                "float": float,
                "str": str,
                "Path": Path,
                "pathlib.Path": Path,
            }.get(annotation)

        if annotation is ParameterData._empty:
            annotation = Path if isinstance(value, Path) else type(value)

        value_type = (
            annotation
            if annotation in (int, float, str, Path)
            else None
        )
        return location, value, value_type, default

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if self._graph is None:
            return None

        if index.isValid() is False:
            return None

        if index.row() >= self.rowCount(index.parent()):
            return None

        shadow = index.siblingAtColumn(0).internalPointer()

        match shadow:
            case _NodeShadow() as node_shadow:
                node_rt = node_shadow.rt
                match role, index.column():
                    case Qt.ItemDataRole.DisplayRole, 0:
                        return node_rt.get_name()                  

            case _InputShadow() as inlet_shadow:
                if index.column() == 0:
                    if role == Qt.ItemDataRole.DisplayRole:
                        return str(inlet_shadow.location)
                    return None

                location, value, value_type, default = self._input_details(inlet_shadow)

                if role == InspectorRole.DefaultRole:
                    return None if default is ParameterData._empty else default

                if role == InspectorRole.TypeRole:
                    return value_type

                if role == Qt.ItemDataRole.DisplayRole:
                    if value is UNSET:
                        if default is ParameterData._empty:
                            return "Not set"
                        return f"Default: {default}"
                    return str(value) if isinstance(value, Path) else value

                if role == InspectorRole.TypeRole:
                    return value_type

                if role == Qt.ItemDataRole.EditRole:
                    if isinstance(value, rt.NodeRef) or value_type is None:
                        return None

                    # Qt chooses its default editor from this value's Python type.
                    if value is None:
                        return {
                            int: 0,
                            float: 0.0,
                            str: "",
                            Path: "",
                        }[value_type]

                    try:
                        if value_type is Path:
                            return str(value)
                        return value_type(value)
                    except (TypeError, ValueError, OverflowError):
                        return {
                            int: 0,
                            float: 0.0,
                            str: "",
                            Path: "",
                        }[value_type]

            case _:
                ...
        
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid() or index.model() is not self:
            return Qt.ItemFlag.NoItemFlags

        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        shadow = index.internalPointer()

        if index.column() == 1 and isinstance(shadow, _InputShadow):
            _, value, value_type, default = self._input_details(shadow)
            if not isinstance(value, rt.NodeRef) and value_type is not None:
                flags |= Qt.ItemFlag.ItemIsEditable

        return flags

    def setData(
        self,
        index: QModelIndex,
        value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if role != Qt.ItemDataRole.EditRole:
            return False
        if not self.flags(index) & Qt.ItemFlag.ItemIsEditable:
            return False

        inlet = index.internalPointer()
        location, _, value_type, default = self._input_details(inlet)
        if value_type is None:
            return False

        node = inlet.parent_node.rt
        args, kwargs = node.get_inputs()
        args, kwargs = list(args), dict(kwargs)

        try:
            value = value_type(value)

            if isinstance(location, int):
                args[location] = value
            else:
                kwargs[location] = value

            node.set_inputs(*args, **kwargs)
        except (TypeError, ValueError, OverflowError):
            return False

        return True
