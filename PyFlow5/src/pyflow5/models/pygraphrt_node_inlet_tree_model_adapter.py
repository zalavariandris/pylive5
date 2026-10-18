from __future__ import annotations

from qdageditor5.adapters.node_inlet_tree_model_adapter import NodeInletTreeModelAdapter
from qtpy.QtCore import QModelIndex, QObject, Qt

from ..core.input_roles import InputDataRole
from .pygraphrt_graphmodel import PyGraphRTGraphModel


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

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        graph = self.sourceGraph()
        if not isinstance(graph, PyGraphRTGraphModel):
            return None

        match self.getItemType(index):
            case self.ItemType.Node:
                return super().data(index, role)

            case self.ItemType.Inlet:
                node_name, inlet_name = self.mapToSource(index)
                if index.column() == 0:
                    if role == Qt.ItemDataRole.DisplayRole:
                        return str(inlet_name)
                    return graph.inletData(node_name, inlet_name, role)

                if index.column() == 1:
                    if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                        connection = graph.inletData(
                            node_name, inlet_name, InputDataRole.ConnectionRole
                        )
                        if connection is not None:
                            return f"-> {connection}" if role == Qt.ItemDataRole.DisplayRole else None
                        value = graph.inletData(
                            node_name, inlet_name, InputDataRole.InputValueRole
                        )
                        if value is graph.EmptyInputValue:
                            value = graph.inletData(
                                node_name, inlet_name, InputDataRole.DefaultValueRole
                            )
                        if value is graph.EmptyInputValue:
                            return None
                        return str(value) if role == Qt.ItemDataRole.DisplayRole else value
                    return graph.inletData(node_name, inlet_name, role)

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        graph = self.sourceGraph()
        if graph is None or not index.isValid() or index.model() is not self:
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)
        if self.getItemType(index) == self.ItemType.Inlet and index.column() == 1:
            node_name, inlet_name = self.mapToSource(index)
            if not any(graph.inLinks(node_name, inlet_name)):
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        source_graph = self.sourceGraph()
        if source_graph is None:
            return False

        if role != Qt.ItemDataRole.EditRole:
            return False

        match self.getItemType(index):
            case self.ItemType.Inlet:
                if index.column() != 1:
                    return False

                node_name, inlet_name = self.mapToSource(index)
                return source_graph.setInletData(
                    node_name,
                    inlet_name,
                    value,
                    InputDataRole.InputValueRole,
                )

            case _:
                return False
