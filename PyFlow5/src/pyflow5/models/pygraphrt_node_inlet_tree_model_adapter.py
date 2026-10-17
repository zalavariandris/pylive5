from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin

import pygraphrt as rt

from qdageditor5.adapters.node_inlet_tree_model_adapter import (
    _InletShadow,
    NodeInletTreeModelAdapter,
)
from qdageditor5.models.abstract_dag_model import InletName
from qtpy.QtCore import QModelIndex, QObject, Qt

from ..core.input_roles import InputDataRole
from .pygraphrt_graphmodel import PyGraphRTGraphModel


@dataclass(frozen=True)
class _InputDetails:
    node: rt.NodeRef
    inlet_name: InletName
    # Runtime argument position or keyword, distinct from the graph inlet name.
    location: int | str
    value: object
    annotation: object
    default: object

    @property
    def base_annotation(self) -> object:
        if get_origin(self.annotation) is Annotated:
            return get_args(self.annotation)[0]
        return self.annotation

    @property
    def editable_type(self) -> type | None:
        if isinstance(self.value, rt.NodeRef):
            return None
        annotation = self.base_annotation
        if isinstance(annotation, type) and annotation is not Any:
            return annotation
        if get_origin(annotation) is tuple:
            return tuple
        return None


class PyGraphRTNodeInletTreeModelAdapter(NodeInletTreeModelAdapter):
    """Add editable runtime input values to the graph's node/inlet tree."""

    def __init__(
        self,
        source_graph: PyGraphRTGraphModel | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(source_graph, parent)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 2

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < 2
        ):
            return ("Name", "Value")[section]
        return None

    def _input_details(self, index: QModelIndex) -> _InputDetails | None:
        source_graph = self.sourceGraph()
        if not isinstance(source_graph, PyGraphRTGraphModel):
            return None

        shadow = self._shadow(index)
        if not isinstance(shadow, _InletShadow):
            return None
        node_inlet = self.mapToSource(index)
        if node_inlet is None:
            return None

        node_name, inlet_name = node_inlet
        node_rt = source_graph.mapToSource(node_name)
        if node_rt is None:
            return None

        args, kwargs = node_rt.get_inputs()
        operator = node_rt.get_operator()
        parameters = operator.get_parameters() if operator is not None else {}
        parameter = parameters.get(inlet_name)

        # The graph orders declared parameters, extra positional inputs, then
        # extra keywords. Use its identities, including escaped numeric names.
        inlets = list(source_graph.inlets(node_name))
        if inlet_name not in inlets:
            return None
        position = inlets.index(inlet_name)
        location: int | str
        if position < len(args):
            location = position
            value = args[position]
        else:
            if not isinstance(inlet_name, str):
                return None
            location = inlet_name
            value = kwargs.get(location, rt.ParameterData.EMPTY)

        default: object = rt.ParameterData.EMPTY
        annotation: object = rt.ParameterData.EMPTY
        if parameter is not None:
            default = parameter.default
            annotation = parameter.annotation
        if isinstance(annotation, str):
            annotation = {
                "int": int,
                "float": float,
                "str": str,
                "bool": bool,
                "Path": Path,
                "pathlib.Path": Path,
            }.get(annotation)
        elif annotation is rt.ParameterData.EMPTY:
            example = default if value is rt.ParameterData.EMPTY else value
            if example is rt.ParameterData.EMPTY:
                annotation = None
            else:
                annotation = Path if isinstance(example, Path) else type(example)

        return _InputDetails(
            node=node_rt,
            inlet_name=inlet_name,
            location=location,
            value=value,
            annotation=annotation,
            default=default,
        )

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        source_graph = self.sourceGraph()
        if source_graph is None:
            return None

        itemtype = self.getItemType(index)
        match itemtype:
            case self.ItemType.Node:
                return super().data(index, role) #todo: why is the super giving back the execution values instead of the name of the node for example?
            
            case self.ItemType.Inlet:
                node_name, inlet_name = self.mapToSource(index)
                match index.column():
                    case 0: # inlet label
                        match role:
                            case Qt.ItemDataRole.DisplayRole:
                                return f"{inlet_name}"
                            case _:
                                return super().data(index, role)
                    
                    case 1: # inlet field
                        match role:
                            case Qt.ItemDataRole.DisplayRole:
                                for link in source_graph.inLinks(node_name, inlet_name):
                                    src, out_, tgt, in_ = link
                                    return f"-> {src}"
                                return super().data(index, role)
                            case Qt.ItemDataRole.EditRole:
                                return super().data(index, role)
                            case _:
                                return super().data(index, role)

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        sourcegraph = self.sourceGraph()
        if sourcegraph is None:
            return Qt.ItemFlag.NoItemFlags

        match self.getItemType(index):
            case self.ItemType.Node:
                return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            
            case self.ItemType.Inlet:
                if index.column() == 1:
                    node_name, inlet_name = self.mapToSource(index)
                    inlinks = list(sourcegraph.inLinks(node_name, inlet_name))
                    if len(inlinks)  == 0:
                        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
                    else:
                        return Qt.ItemFlag.ItemIsEnabled

        return super().flags(index)
    
    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if role != Qt.ItemDataRole.EditRole or index.column() != 1:
            return False
        details = self._input_details(index)
        if details is None:
            return False

        itemtype = super().getItemType(index)
        match itemtype:
            case self.ItemType.Node:
                return False # todo: consider setting node props here.
            case self.ItemType.Inlet:
                pass
            case _:
                return False

        args, kwargs = details.node.get_inputs()
        args, kwargs = list(args), dict(kwargs)
        location = details.location
        if value is rt.ParameterData.EMPTY:
            if isinstance(location, int):
                args.pop(location)
            elif location in kwargs:
                del kwargs[location]
            else:
                return False
        else:
            value_type = details.editable_type
            if value_type is None:
                return False
            try:
                if value_type is bool and isinstance(value, str):
                    text = value.lower()
                    if text not in ("true", "false"):
                        return False
                    value = text == "true"

                elif value_type is tuple and get_origin(details.base_annotation) is tuple:
                    component_types = get_args(details.base_annotation)
                    if not isinstance(value, tuple):
                        return False
                    if component_types and all(t in (int, float) for t in component_types):
                        if len(value) != len(component_types):
                            return False
                        value = tuple(t(item) for t, item in zip(component_types, value))

                elif issubclass(value_type, (int, float, str, Path, Enum)):
                    value = value_type(value)

                elif not isinstance(value, value_type):
                    # Custom editors return the actual object; do not reconstruct it.
                    return False
                
            except (TypeError, ValueError, OverflowError):
                return False

            if isinstance(location, int):
                args[location] = value
            else:
                kwargs[location] = value

        # The graph forwards the runtime notification to the base adapter.
        details.node.set_inputs(*args, **kwargs)
        return True
