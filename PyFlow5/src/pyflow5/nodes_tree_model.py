"""A tree projection of one graphmodel."""
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

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
    if node_rt.get_operator() is None:
        for i, val in enumerate(args):
            consolidated[i] = val
        for key, val in kwargs.items():
            consolidated[key] = val
        
    else:
        op_rt = node_rt.get_operator()
        for i, (name, param) in enumerate(op_rt.get_parameters().items()):
            if i<len(args):
                consolidated[i] = args[i]
            else:
                consolidated[name] = kwargs.get(name)

        # what to do when args is longer than the number of parameters
        if len(args) > len(op_rt.get_parameters()):
            for i in range(len(op_rt.get_parameters()), len(args)):
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
                    for location, val in consolidate_inputs_and_parameters(node_ref):
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

    def parent(self, index: QModelIndex) -> QModelIndex:
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

        # if parent.model() is not self or parent.column() != 0:
        #     return 0

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

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = ...) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if section == 0:
                return "Name"
            elif section == 1:
                return "Value"
        return None

    def columnCount(self, parent: QModelIndex):
        return 2

    def _mapToSource(self, index: QModelIndex) -> NodeName | tuple[NodeName, InletName] | None:
        if self._graph is None:
            return None
        if not index.isValid():
            return None
        internal_pointer = index.internalPointer()
        match internal_pointer:
            case _NodeShadow():
                return internal_pointer.name
            case _InputShadow():
                return (internal_pointer.parent_node.name, internal_pointer.name)
            case _:
                return None

    def data(self, index: QModelIndex, role: int = ...):
        if self._graph is None:
            return None

        if index.isValid() is False:
            return None

        if index.row() >= self.rowCount(QModelIndex()):
            return None

        shadow = index.siblingAtColumn(0).internalPointer()

        match shadow:
            case _NodeShadow() as node_shadow:
                node_shadow= shadow.rt
                match role, index.column():
                    case Qt.DisplayRole, 0:
                        return node_shadow.get_name()                    

            case _InputShadow() as inlet_shadow:
                match role, index.column():
                    case Qt.DisplayRole, 0:
                        return f"{inlet_shadow.location}"
                    case Qt.DisplayRole, 1:
                        node_rt = inlet_shadow.parent_node.rt
                        all_inputs = consolidate_inputs_and_parameters(node_rt)
                        return all_inputs.get(inlet_shadow.location, None)

            case _:
                ...
        
        return None
