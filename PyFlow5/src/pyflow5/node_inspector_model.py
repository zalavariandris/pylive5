"""A flat projection of one runtime node's input bindings."""
from dataclasses import dataclass
from typing import Any

from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import QAbstractListModel, QModelIndex, Qt

from myqtx.inspector_roles import InspectorRole, UNSET
from pygraphrt.abstract_module_rt import ParameterData
from pygraphrt.graph_rt import NodeRef

from .pygraphrt_model import PyFlowRTModel


@dataclass
class _Input:
    key: tuple
    name: str
    value: Any = UNSET
    annotation: Any = None
    default: Any = UNSET
    binding: str = "missing"
    connection: tuple | None = None
    error: str = ""


class NodeInspectorModel(QAbstractListModel):
    """Expose parameter metadata and bindings without evaluating the graph.

    Valid literal and default parameter values can be edited in place.
    Complex values occupy one row and are passed intact to their editor widget.
    """

    def __init__(self, graph_model: PyFlowRTModel, parent=None):
        super().__init__(parent)
        self._graph_model = graph_model
        self._node:NodeName | None = None
        self._rows: list[_Input] = []
        self._description:str = ""
        graph_model.nodeDataChanged.connect(self._on_nodes_changed)
        graph_model.nodesAboutToBeRemoved.connect(self._on_nodes_removed)
        graph_model.modelAboutToBeReset.connect(self._clear)
        graph_model.modelReset.connect(self._clear)

    def node(self):
        return self._node

    def setNode(self, node:NodeName|None)->None:
        if node is not None and self._graph_model.getNode(node) is None:
            node = None
        if node == self._node:
            return
        self.beginResetModel()
        self._node = node
        self._rows, self._description = self._read_node()
        self.endResetModel()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)

    def _clear(self):
        self.setNode(None)

    def _on_nodes_removed(self, nodes:list[NodeName])->None:
        if self._node in nodes:
            self.setNode(None)

    def _on_nodes_changed(self, nodes:list[NodeName])->None:
        if self._node is None or self._node not in nodes:
            return
        if self._graph_model.getNode(self._node) is None:
            self.setNode(None)
            return
        rows, description = self._read_node()
        self._description = description
        if [row.key for row in rows] != [row.key for row in self._rows]:
            self.beginResetModel()
            self._rows = rows
            self.endResetModel()
        else:
            self._rows = rows
            if rows:
                self.dataChanged.emit(self.index(0), self.index(len(rows) - 1), [])
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 0)

    def _read_node(self):
        """Read the current node and return its input rows and description.

        Returns:
            tuple[list[_Input], str]: A tuple containing the list of input rows and the node description.
        """
        if self._node is None:
            return [], ""
        node = self._graph_model.getNode(self._node)
        operator = node.get_operator()
        available = operator is not None and operator.get_value() is not None
        description = (
            f"{operator.module.get_name()}.{operator.name}"
            if operator is not None else "No operator"
        )
        if not available:
            description += " ? operator unavailable"
        parameters = operator.get_parameters() if available else {}
        names = list(parameters)
        args, kwargs = node.get_inputs()
        rows = []

        for position, (name, parameter) in enumerate(parameters.items()):
            default = parameter.default
            if default is ParameterData._empty:
                default = UNSET
            annotation = parameter.annotation
            if annotation is ParameterData._empty:
                annotation = None
            if position < len(args):
                value, binding = args[position], "literal"
            elif name in kwargs:
                value, binding = kwargs[name], "literal"
            elif default is not UNSET:
                value, binding = default, "default"
            else:
                value, binding = UNSET, "missing"
            row = _Input(("parameter", name), name, value, annotation, default, binding)
            if binding == "missing":
                row.error = "Required input is not bound."
            if position < len(args) and name in kwargs:
                row.error = "Input is bound both positionally and by keyword."
            rows.append(row)

        # Retain malformed bindings after live signature changes.
        for position in range(len(names), len(args)):
            rows.append(_Input(
                ("argument", position), f"Argument {position + 1}", args[position],
                binding="literal", error="No matching parameter.",
            ))
        for name, value in kwargs.items():
            duplicate = name in names and names.index(name) < len(args)
            if name not in parameters or duplicate:
                rows.append(_Input(
                    ("keyword", name), f"{name} (keyword)" if duplicate else name,
                    value, binding="literal",
                    error="Duplicate keyword binding." if duplicate else "No matching parameter.",
                ))

        for row in rows:
            if isinstance(row.value, NodeRef):
                row.binding = "connection"
                row.connection = (row.value.get_name(), "out")
                row.value = UNSET
                if self._graph_model.getNode(row.connection[0]) is None:
                    row.error = "Connected node is missing."
            elif row.annotation is None and row.value is not UNSET:
                row.annotation = type(row.value)
        return rows, description

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index:QModelIndex, role=Qt.ItemDataRole.DisplayRole)->Any:
        if (not index.isValid() or index.model() is not self
                or index.column() != 0 or not 0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row.name
        if role == Qt.ItemDataRole.EditRole:
            return row.value
        if role == InspectorRole.KeyRole:
            return row.key
        if role == InspectorRole.TypeRole:
            return row.annotation
        if role == InspectorRole.DefaultRole:
            return row.default
        if role == InspectorRole.BindingRole:
            return row.binding
        if role == InspectorRole.ConnectionRole:
            return row.connection
        if role == InspectorRole.EditorHintsRole:
            return {}
        if role in (InspectorRole.ErrorRole, Qt.ItemDataRole.ToolTipRole):
            return row.error
        return None

    def flags(self, index:QModelIndex)->Qt.ItemFlag:
        if (not index.isValid() or index.model() is not self
                or index.column() != 0 or not 0 <= index.row() < len(self._rows)):
            return Qt.ItemFlag.NoItemFlags
        row = self._rows[index.row()]
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if row.key[0] == "parameter" and row.binding in ("literal", "default") and not row.error:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not self.flags(index) & Qt.ItemFlag.ItemIsEditable:
            return False
        node = self._graph_model.getNode(self._node)
        if node is None:
            return False
        row = self._rows[index.row()]
        parameters = list(node.get_operator().get_parameters())
        position = parameters.index(row.name)
        args, kwargs = node.get_inputs()
        args, kwargs = list(args), dict(kwargs)
        if position < len(args):
            args[position] = value
        else:
            kwargs[row.name] = value
        try:
            node.set_inputs(*args, **kwargs)
        except (TypeError, ValueError):
            return False
        return True

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole)->Any:
        if section != 0 or orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return str(self._node) if self._node is not None else "No node selected"
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._description
        return None
