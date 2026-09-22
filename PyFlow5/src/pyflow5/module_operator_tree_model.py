from dataclasses import dataclass, field
from typing import Iterable

from pygraphrt.graph_rt import GraphRT
from qtpy.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal, Slot
from pygraphrt.abstract_module_rt import AbstractModule, OperatorRef
from pygraphrt.script_module import ScriptModuleRT


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

    scriptSaveFailed = Signal(str)

    ModuleRole = int(Qt.ItemDataRole.UserRole) + 1
    OperatorRole = ModuleRole + 1
    NameRole = OperatorRole + 1
    CodeRole = NameRole + 1

    def __init__(self, modules: Iterable[AbstractModule] = (), parent=None):
        super().__init__(parent)
        self._items: list[_ModuleItem] = []
        self._graph = None
        self.setModules(modules)

    def setGraph(self, graph:GraphRT):
        """Observe the runtime's module collection instead of maintaining our own."""
        if self._graph is not None:
            self._graph.modules_changed.disconnect(self._sync_modules)
        self._graph = graph
        graph.modules_changed.connect(self._sync_modules)
        self._sync_modules()

    @Slot()
    def _sync_modules(self):
        self._replace_modules(self._graph.modules())

    def _connect(self, module):
        for signal in (module.operators_added, module.operators_removed,
                       module.operators_changed):
            signal.connect(self._on_operators_changed)
        if isinstance(module, ScriptModuleRT):
            module.script_changed.connect(self._on_script_changed)

    def _disconnect(self, module):
        for signal in (module.operators_added, module.operators_removed,
                       module.operators_changed):
            signal.disconnect(self._on_operators_changed)
        if isinstance(module, ScriptModuleRT):
            module.script_changed.disconnect(self._on_script_changed)

    @staticmethod
    def _make_item(module):
        item = _ModuleItem(module)
        item.operators = [_OperatorItem(ref, item) for ref in module.operators()]
        return item

    def setModules(self, modules: Iterable[AbstractModule]):
        if self._graph is not None:
            raise ValueError("Change modules through the bound graph")
        self._replace_modules(modules)

    def _replace_modules(self, modules):
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
        if self._graph is not None:
            self._graph.add_import_module(module)
            return
        if any(item.module is module for item in self._items):
            return
        item = self._make_item(module)
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self._connect(module)
        self.endInsertRows()

    def removeModule(self, module: AbstractModule):
        if self._graph is not None:
            self._graph.remove_import(module)
            return
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

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, self.NameRole):
            return module.get_name() if isinstance(item, _ModuleItem) else item.ref.name

        if role == self.CodeRole and isinstance(item, _ModuleItem) and isinstance(module, ScriptModuleRT):
            return module.get_script()
        
        if role == self.ModuleRole:
            return module
        
        if role == self.OperatorRole and isinstance(item, _OperatorItem):
            return item.ref
        
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.model() is not self:
            return False
        item = index.internalPointer()
        if not isinstance(item, _ModuleItem) or not isinstance(item.module, ScriptModuleRT):
            return False
        if role in (Qt.ItemDataRole.EditRole, self.NameRole):
            item.module.set_name(value)
            self.dataChanged.emit(index, index, [int(Qt.ItemDataRole.DisplayRole),
                                               int(Qt.ItemDataRole.EditRole), self.NameRole])
            return True
        if role == self.CodeRole:
            try:
                item.module.set_script(value)
            except OSError as error:
                self.scriptSaveFailed.emit(str(error))
                return False
            return True
        return False

    @Slot()
    def _on_script_changed(self):
        module = self.sender()
        for row, item in enumerate(self._items):
            if item.module is module:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, [self.CodeRole])
                break

    def flags(self, index:QModelIndex):
        if not index.isValid() or index.model() is not self:
            return Qt.ItemFlag.NoItemFlags

        item = index.internalPointer()
        match item:
            case _OperatorItem(ref=ref) if ref is not None:
                return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            
            case _ModuleItem():
                return Qt.ItemFlag.NoItemFlags
            
            case _:
                return Qt.ItemFlag.NoItemFlags

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
