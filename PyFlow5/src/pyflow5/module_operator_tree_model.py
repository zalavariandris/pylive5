from dataclasses import dataclass, field
from typing import Iterable

from qtpy.QtCore import QAbstractItemModel, QModelIndex, Qt, Slot
from pygraphrt.abstract_module_rt import AbstractModule, OperatorRef


@dataclass(eq=False)
class _ModuleItem:
    module: AbstractModule
    operators: list["_OperatorItem"] = field(default_factory=list)


@dataclass(eq=False)
class _OperatorItem:
    ref: OperatorRef
    parent: _ModuleItem


class ModuleOperatorTreeModel(QAbstractItemModel):
    """One-column module/operator browser, observing externally owned modules.

    Rows are snapshots: runtime notifications arrive after changes, so Qt's
    begin/end calls bracket changes to these snapshots rather than the runtime.
    Modules and this model must be used on the same Qt thread.
    """

    ModuleRole = int(Qt.ItemDataRole.UserRole) + 1
    OperatorRole = ModuleRole + 1

    def __init__(self, modules: Iterable[AbstractModule] = (), parent=None):
        super().__init__(parent)
        self._items: list[_ModuleItem] = []
        self.setModules(modules)

    def _connect(self, module):
        for signal in (module.operators_added, module.operators_removed,
                       module.operators_changed):
            signal.connect(self._on_operators_changed)

    def _disconnect(self, module):
        for signal in (module.operators_added, module.operators_removed,
                       module.operators_changed):
            signal.disconnect(self._on_operators_changed)

    @staticmethod
    def _make_item(module):
        item = _ModuleItem(module)
        item.operators = [_OperatorItem(ref, item) for ref in module.operators()]
        return item

    def setModules(self, modules: Iterable[AbstractModule]):
        modules = list(dict.fromkeys(modules))
        items = [self._make_item(module) for module in modules]
        self.beginResetModel()
        for item in self._items:
            self._disconnect(item.module)
        self._items = items
        for item in self._items:
            self._connect(item.module)
        self.endResetModel()

    def addModule(self, module: AbstractModule):
        if any(item.module is module for item in self._items):
            return
        item = self._make_item(module)
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self._connect(module)
        self.endInsertRows()

    def removeModule(self, module: AbstractModule):
        for row, item in enumerate(self._items):
            if item.module is module:
                self.beginRemoveRows(QModelIndex(), row, row)
                self._disconnect(module)
                self._items.pop(row)
                self.endRemoveRows()
                return

    def columnCount(self, parent=QModelIndex()):
        return 1

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            return len(self._items)
        if parent.model() is not self or parent.column() != 0:
            return 0
        item = parent.internalPointer()
        return len(item.operators) if isinstance(item, _ModuleItem) else 0

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        items = self._items if not parent.isValid() else parent.internalPointer().operators
        return self.createIndex(row, column, items[row])

    def parent(self, index):
        if not index.isValid() or index.model() is not self:
            return QModelIndex()
        item = index.internalPointer()
        if isinstance(item, _OperatorItem):
            return self.createIndex(self._items.index(item.parent), 0, item.parent)
        return QModelIndex()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.model() is not self:
            return None
        item = index.internalPointer()
        module = item.module if isinstance(item, _ModuleItem) else item.ref.module
        if role == Qt.ItemDataRole.DisplayRole:
            return module.name() if isinstance(item, _ModuleItem) else item.ref.name
        if role == self.ModuleRole:
            return module
        if role == self.OperatorRole and isinstance(item, _OperatorItem):
            return item.ref
        return None

    def flags(self, index):
        if not index.isValid() or index.model() is not self:
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if section == 0 and orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return "Modules and operators"
        return None

    @Slot(list)
    def _on_operators_changed(self, changes):
        module = self.sender()
        for row, item in enumerate(self._items):
            if item.module is module:
                self._sync_operators(row, item)
                break

    def _sync_operators(self, row, item):
        refs = list(item.module.operators())
        parent = self.index(row, 0)
        # Preserve surviving rows and their persistent indexes.
        for child_row in reversed(range(len(item.operators))):
            if item.operators[child_row].ref not in refs:
                self.beginRemoveRows(parent, child_row, child_row)
                removed_item = item.operators.pop(child_row)
                self.endRemoveRows()
                del removed_item  # Keep internalPointer alive through removal notifications.
        existing = {child.ref for child in item.operators}
        added = [ref for ref in refs if ref not in existing]
        if added:
            first = len(item.operators)
            self.beginInsertRows(parent, first, first + len(added) - 1)
            item.operators.extend(_OperatorItem(ref, item) for ref in added)
            self.endInsertRows()
        if item.operators:
            self.dataChanged.emit(self.index(0, 0, parent),
                                  self.index(len(item.operators) - 1, 0, parent),
                                  [int(Qt.ItemDataRole.DisplayRole), self.OperatorRole])
