from __future__ import annotations

from pyparsing import Literal
"""A tree projection of one graphmodel."""
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, NamedTuple

from .inspector_roles import InspectorRole
from pygraphrt.abstract_operator import ParameterData
from qdageditor5.models.abstract_dag_model import InletName, NodeName
from qtpy.QtCore import QAbstractItemModel, QAbstractListModel, QModelIndex, QObject, Qt
# from .pygraphrt_model import PyFlowRTModel

import pygraphrt as rt


@dataclass
class _OperatorShadow:
    rt: rt.AbstractOperator

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


class _InputDetails(NamedTuple):
    location: int|str
    value: object
    annotation: Any
    default: Any

class NodesTreeModel(QAbstractItemModel):
    """A tree projection of one graphmodel."""

    def __init__(
        self,
        graph: rt.GraphDefinitionRT,
        registry: rt.ModuleRegistry,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._graph: rt.GraphDefinitionRT | None = None
        self._graph_connections: list[Any] = []
        self._nodes_shadow: list[_NodeShadow] = []
        self._registry: rt.ModuleRegistry | None = None
        self._modules_connections: list[Any] = []
        self._setSourceEngine(graph, registry)

    def _setSourceEngine(
        self,
        graph: rt.GraphDefinitionRT | None,
        registry: rt.ModuleRegistry | None,
    ) -> None:
        if self._graph is not None:
            for signal, slot in self._graph_connections:
                signal.disconnect(slot)
            self._graph_connections.clear()
            self._graph = None

        if graph is not None:
            self._graph_connections = [
                (graph.nodes_added, self._on_nodes_added),
                (graph.nodes_removed, self._on_nodes_removed),
                (graph.nodes_changed, self._on_nodes_changed),
            ]
            for signal, slot in self._graph_connections:
                signal.connect(slot)
            self._graph = graph

        if self._registry is not None:
            for signal, slot in self._modules_connections:
                signal.disconnect(slot)
            self._modules_connections = []

        self._registry = registry
        if registry is not None:
            self._modules_connections = [
                (registry.modules_added, self._on_registry_changed),
                (registry.modules_removed, self._on_registry_changed),
                (registry.operators_added, self._on_registry_changed),
                (registry.operators_removed, self._on_registry_changed),
                (registry.operators_changed, self._on_registry_changed),
            ]
            for signal, slot in self._modules_connections:
                signal.connect(slot)

        self._rebuild_nodes_shadow()

    def _rebuild_nodes_shadow(self) -> None:
        self.beginResetModel()
        self._nodes_shadow = (
            [self._make_node_shadow(node_ref) for node_ref in self._graph.nodes()]
            if self._graph is not None
            else []
        )
        self.endResetModel()

    @staticmethod
    def _input_locations(node_ref: rt.NodeRef) -> list[int | str]:
        operator = node_ref.get_operator()
        if operator is not None:
            return list(operator.get_parameters())
        return list(consolidate_inputs_and_parameters(node_ref))

    @classmethod
    def _make_node_shadow(cls, node_ref: rt.NodeRef) -> _NodeShadow:
        operator = node_ref.get_operator()
        node_shadow = _NodeShadow(
            rt=node_ref,
            operator=_OperatorShadow(operator) if operator is not None else None,
            inlet_order=[],
        )
        node_shadow.inlet_order = [
            _InputShadow(location, node_shadow)
            for location in cls._input_locations(node_ref)
        ]
        return node_shadow

    def _on_nodes_added(self, nodes: list[rt.NodeRef]) -> None:
        for node_ref in nodes:
            if any(shadow.rt == node_ref for shadow in self._nodes_shadow):
                continue
            row = len(self._nodes_shadow)
            self.beginInsertRows(QModelIndex(), row, row)
            self._nodes_shadow.append(self._make_node_shadow(node_ref))
            self.endInsertRows()

    def _on_nodes_removed(self, nodes: list[rt.NodeRef]) -> None:
        for node_ref in nodes:
            row = next(
                (
                    index
                    for index, shadow in enumerate(self._nodes_shadow)
                    if shadow.rt == node_ref
                ),
                None,
            )
            if row is None:
                continue
            self.beginRemoveRows(QModelIndex(), row, row)
            self._nodes_shadow.pop(row)
            self.endRemoveRows()

    def _on_nodes_changed(self, nodes: list[rt.NodeRef]) -> None:
        for node_ref in nodes:
            node_shadow = next(
                (
                    shadow
                    for shadow in self._nodes_shadow
                    if shadow.rt == node_ref
                ),
                None,
            )
            if node_shadow is not None:
                self._refresh_node(node_shadow)

    def _on_registry_changed(self, *_: object) -> None:
        for node_shadow in self._nodes_shadow:
            self._refresh_node(node_shadow)

    def _refresh_node(self, node_shadow: _NodeShadow) -> None:
        operator = node_shadow.rt.get_operator()
        node_shadow.operator = (
            _OperatorShadow(operator) if operator is not None else None
        )

        old_locations = [inlet.location for inlet in node_shadow.inlet_order]
        new_locations = self._input_locations(node_shadow.rt)
        prefix = 0
        while (
            prefix < min(len(old_locations), len(new_locations))
            and old_locations[prefix] == new_locations[prefix]
        ):
            prefix += 1

        suffix = 0
        while (
            suffix < len(old_locations) - prefix
            and suffix < len(new_locations) - prefix
            and old_locations[-(suffix + 1)] == new_locations[-(suffix + 1)]
        ):
            suffix += 1

        parent = self.createIndex(
            self._nodes_shadow.index(node_shadow), 0, node_shadow
        )
        remove_count = len(old_locations) - prefix - suffix
        if remove_count:
            last = prefix + remove_count - 1
            self.beginRemoveRows(parent, prefix, last)
            del node_shadow.inlet_order[prefix : last + 1]
            self.endRemoveRows()

        insert_count = len(new_locations) - prefix - suffix
        if insert_count:
            last = prefix + insert_count - 1
            self.beginInsertRows(parent, prefix, last)
            node_shadow.inlet_order[prefix:prefix] = [
                _InputShadow(location, node_shadow)
                for location in new_locations[prefix : last + 1]
            ]
            self.endInsertRows()

        if node_shadow.inlet_order:
            self.dataChanged.emit(
                self.index(0, 1, parent),
                self.index(len(node_shadow.inlet_order) - 1, 1, parent),
                [],
            )

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
        self, 
        inlet: _InputShadow
    ) -> _InputDetails:
        node:rt.NodeRef = inlet.parent_node.rt
        args, kwargs = node.get_inputs()
        location:int|str = inlet.location
        parameter:rt.ParameterData|None = None

        # find parameter locator
        operator:rt.AbstractOperator|None = node.get_operator()
        if operator is not None and isinstance(location, str):
            parameters = operator.get_parameters()
            parameter = parameters.get(location)

            if parameter is not None:
                position = list(parameters).index(location)
                if position < len(args):
                    location = position

        # find value based on location
        if isinstance(location, int):
            value = args[location]
        else:
            value = kwargs.get(location, ParameterData.EMPTY)

        # has default?
        default = (
            parameter.default
            if parameter is not None
            else ParameterData.EMPTY
        )

        annotation = (
            parameter.annotation
            if parameter is not None
            else ParameterData.EMPTY
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

        if annotation is ParameterData.EMPTY:
            if value is ParameterData.EMPTY:
                annotation = None
            else:
                annotation = Path if isinstance(value, Path) else type(value)

        return _InputDetails(
            location, 
            value, 
            annotation,
            default
        )

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
                        return f"{inlet_shadow.location}"
                    return None

                if index.column() == 1:
                    input_details = self._input_details(inlet_shadow)

                    if role == InspectorRole.NodeRefRole:
                        return inlet_shadow.parent_node.rt

                    elif role == InspectorRole.InputLocationRole:
                        return inlet_shadow.location

                    if role == Qt.ItemDataRole.DisplayRole:
                        if input_details.value is ParameterData.EMPTY:
                            if input_details.default is ParameterData.EMPTY:
                                return "Not set"
                            else:
                                return f"{input_details.default}"
                            
                        elif input_details.value is rt.NodeRef:
                            return f"->{input_details.value}"
                        else:
                            return input_details.value

                    elif role == Qt.ItemDataRole.EditRole:
                        if isinstance(input_details.value, rt.NodeRef):
                            return None
                        
                        elif input_details.value is ParameterData.EMPTY:
                            # Qt chooses its default editor from this value's Python type.
                            annotation = input_details.annotation
                            if annotation is int:
                                return 0
                            if annotation is float:
                                return 0.0
                            if annotation is str:
                                return ""
                            if annotation is Path:
                                return ""
                            if annotation is bool:
                                return False
                    
                            return None
                        return input_details.value

                    elif role == InspectorRole.IsUsingDefaultRole:
                        return (
                            input_details.value is ParameterData.EMPTY
                            and input_details.default is not ParameterData.EMPTY
                        )

                    elif role == InspectorRole.DefaultRole:
                        if input_details.default is ParameterData.EMPTY:
                            return None
                        return input_details.default

                    elif role == InspectorRole.AnnotationRole:
                        return input_details.annotation

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
        if value is ParameterData.EMPTY:
            return self.clearInput(inlet.parent_node.rt, location)
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

    def clearInput(self, node_ref: rt.NodeRef, location: int | str) -> bool:
        if self._graph is None or node_ref not in self._graph.nodes():
            return False

        operator = node_ref.get_operator()
        args, kwargs = node_ref.get_inputs()
        args, kwargs = list(args), dict(kwargs)
        changed = False

        if isinstance(location, int):
            if not 0 <= location < len(args):
                return False
            args.pop(location)
            changed = True
        else:
            parameters = list(operator.get_parameters()) if operator else []
            if location in parameters:
                position = parameters.index(location)
                if position < len(args):
                    args.pop(position)
                    changed = True

            if location in kwargs:
                del kwargs[location]
                changed = True

        if not changed:
            return False

        self._graph._update_node(node_ref, operator, args, kwargs)
        return True
