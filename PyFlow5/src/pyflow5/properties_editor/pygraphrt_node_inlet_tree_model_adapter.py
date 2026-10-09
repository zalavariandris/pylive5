from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin

import pygraphrt as rt
from myqtx.editorregistry import EditorContext
from pygraphrt.abstract_operator import ParameterData
from qdageditor5.adapters.node_inlet_tree_model_adapter import (
    NodeInletTreeModelAdapter,
)
from qdageditor5.models.abstract_dag_model import InletName
from qtpy.QtCore import QModelIndex, QObject, Qt

from ..nodert_input_roles import NodeRTInputRole
from ..pygraphrt_graphmodel import PyGraphRTGraphModel


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
    def editable_type(self) -> type | None:
        if isinstance(self.value, rt.NodeRef):
            return None
        if isinstance(self.annotation, type) and self.annotation is not Any:
            return self.annotation
        if get_origin(self.annotation) is tuple:
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
        source = self.sourceGraph()
        inlet = self._inlet_source(index)
        if not isinstance(source, PyGraphRTGraphModel) or inlet is None:
            return None

        node_name, inlet_name = inlet
        node = source.mapToSource(node_name)
        if node is None:
            return None

        args, kwargs = node.get_inputs()
        operator = node.get_operator()
        parameters = operator.get_parameters() if operator is not None else {}
        parameter = parameters.get(inlet_name)

        # The graph orders declared parameters, extra positional inputs, then
        # extra keywords. Use its identities, including escaped numeric names.
        inlets = list(source.inlets(node_name))
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
            value = kwargs.get(location, ParameterData.EMPTY)

        default: object = ParameterData.EMPTY
        annotation: object = ParameterData.EMPTY
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
        elif annotation is ParameterData.EMPTY:
            example = default if value is ParameterData.EMPTY else value
            if example is ParameterData.EMPTY:
                annotation = None
            else:
                annotation = Path if isinstance(example, Path) else type(example)

        return _InputDetails(
            node=node,
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
        if index.column() != 1:
            return super().data(index, role)

        details = self._input_details(index)
        if details is None:
            return None

        value = details.value
        if role == NodeRTInputRole.ConnectionRole:
            return (value.get_name(),) if isinstance(value, rt.NodeRef) else None
        if role == NodeRTInputRole.NodeRefRole:
            return details.node
        if role == NodeRTInputRole.InputLocationRole:
            return details.inlet_name
        if role == NodeRTInputRole.AnnotationRole:
            return details.annotation
        if role == NodeRTInputRole.EditorContextRole:
            operator = details.node.get_operator()
            return EditorContext(
                module_name=operator.get_module_name() if operator is not None else "",
                operator_name=operator.get_name() if operator is not None else "",
                parameter_name=str(details.inlet_name),
                annotation=details.annotation,
                source_path=operator.get_source_path() if operator is not None else None,
            )
        if role == NodeRTInputRole.DefaultRole:
            if details.default is ParameterData.EMPTY:
                return None
            return details.default
        if role == NodeRTInputRole.IsUsingDefaultRole:
            return (
                value is ParameterData.EMPTY
                and details.default is not ParameterData.EMPTY
            )

        if role == Qt.ItemDataRole.DisplayRole:
            if value is ParameterData.EMPTY:
                if details.default is ParameterData.EMPTY:
                    return "Not set"
                return str(details.default)
            if isinstance(value, rt.NodeRef):
                return f"-> {value.get_name()}"
            return str(value) if isinstance(value, (Path, Enum)) else value

        if role == Qt.ItemDataRole.EditRole:
            if isinstance(value, rt.NodeRef):
                return None
            if value is ParameterData.EMPTY:
                value = details.default
            if value is ParameterData.EMPTY:
                value_type = details.editable_type
                if value_type in (int, float, str, bool):
                    return value_type()
                return None
            return value

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.column() == 1:
            details = self._input_details(index)
            if details is not None and details.editable_type is not None:
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

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

        args, kwargs = details.node.get_inputs()
        args, kwargs = list(args), dict(kwargs)
        location = details.location
        if value is ParameterData.EMPTY:
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
                elif value_type is tuple and get_origin(details.annotation) is tuple:
                    component_types = get_args(details.annotation)
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
