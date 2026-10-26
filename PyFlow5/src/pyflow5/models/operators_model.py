from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Callable
from unittest import case
from qtpy.QtCore import SignalInstance
from qtpy.QtWidgets import QApplication, QStyle

from qtpy.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt

import pygraphrt2 as rt2

from myutils.bilist import BiList
from bidict import bidict

@dataclass(frozen=True)
class _OperatorShadow:
    name: str

class OperatorsModel(QAbstractItemModel):
    """A list of operators from the source registry."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._registry: rt2.ScriptModule | None = None
        self._registry_connections: list[tuple[SignalInstance, Callable]] = []

        self._shadows: BiList[_OperatorShadow] = BiList()
        self._mapping: bidict[rt2.ScriptOperatorRef, _OperatorShadow] = bidict()

    def sourceRegistry(self) -> rt2.ScriptModule | None:
        return self._registry

    def setSourceRegistry(self, registry: rt2.ScriptModule | None) -> None:
        """Replace the runtime used by this model."""
        if self._registry is registry:
            return

        if self._registry is not None:
            for signal, slot in self._registry_connections:
                signal.disconnect(slot)
            self._registry_connections.clear()

        if registry is not None:
            # todo: proper insertion and removal handling will be necessary to match the 
            # qabstractitmodel interface
            self._registry_connections = [
                (registry.operators_added,   self._on_operators_added),
                (registry.operators_removed, self._on_operators_removed),
                (registry.operators_changed, self._on_operators_changed),
            ]
            for signal, slot in self._registry_connections:
                signal.connect(slot)

        

        self.beginResetModel()
        self._registry = registry
        self._mapping.clear()
        self._shadows.clear()
        if self._registry is not None:
            for operator in self._registry.operators():
                shadow = _OperatorShadow(name=operator.name())
                self._shadows.append(shadow)
                self._mapping[operator] = shadow
        self.endResetModel()

    def _on_operators_added(self, operators: list[rt2.ScriptOperatorRef]) -> None:
        if len(operators) == 0:
            return
        
        first = len(self._shadows)
        last = len(self._shadows) + len(operators) - 1
        # todo: keep the original operators order
        self.beginInsertRows(QModelIndex(), first, last)
        for operator in operators:
            shadow = _OperatorShadow(name=operator.name())
            self._shadows.append(shadow)
            self._mapping[operator] = shadow
        self.endInsertRows()

    def _on_operators_removed(self, operators: list[rt2.ScriptOperatorRef]) -> None:
        """Handle the removal of operators from the registry."""
        # todo: keep the original operators order when removing
        # consolidate contiguous removed rows into a single beginRemoveRows/endRemoveRows block
        for operator in operators:
            shadow = self._mapping.get(operator)
            if shadow is not None:
                row = self._shadows.index(shadow)
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._mapping[operator]
                self._shadows.pop(row)
                self.endRemoveRows()

    def _on_operators_changed(self, operators: list[rt2.ScriptOperatorRef]) -> None:
        """Handle the change of operators in the registry."""
        # todo: consolidate contiguous changed rows into a single dataChanged signal
        for operator in operators:
            shadow = self._mapping.get(operator, None)
            if shadow is not None:
                row = self._shadows.index(shadow)
                index = self.index(row, 0, QModelIndex())
                self.dataChanged.emit(index, index)

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = QModelIndex(),
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        return self.createIndex(row, column)

    def parent(self, child: QModelIndex) -> QModelIndex:  # type: ignore
        return QModelIndex() # flat model

    def mapToSource(
        self, index: QModelIndex
    ) -> rt2.ScriptOperatorRef | None:
        if self._registry is None:
            return None

        if not index.isValid():
            return None
        
        if index.model() is not self:
            return None

        if index.column() != 0:
            return None

        if index.row() < 0 or index.row() >= len(self._shadows):
            return None

        shadow = self._shadows[index.row()]
        operator = self._mapping.inverse[shadow]
        return operator
    
    def mapFromSource(
        self, source: rt2.ScriptOperatorRef | None
    ) -> QModelIndex:
        if self._registry is None:
            return QModelIndex()

        if not isinstance(source, rt2.ScriptOperatorRef):
            return QModelIndex()

        ## Find the operator in the registry
        ## todo: performance optimization is necessary
        shadow = self._mapping.get(source)
        if shadow is None:
            return QModelIndex()
        return self.index(self._shadows.inverse[shadow], 0)

        return QModelIndex()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0 # this is a flat list

        return len(self._shadows)
    
    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object | None:
        if index.model() is not self:
            return None
        
        if not index.isValid():
            return None

        if index.column() != 0:
            return None

        if index.row() < 0 or index.row() >= len(self._shadows):
            return None

        shadow = self._shadows[index.row()]

        match role:
            case Qt.ItemDataRole.DisplayRole:
                return shadow.name
            case Qt.ItemDataRole.EditRole:
                return shadow.name
            case Qt.ItemDataRole.WhatsThisRole:
                return shadow.name
        
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if index.isValid()==False:
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        if (
            section == 0
            and orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return "Operators"
        return None
