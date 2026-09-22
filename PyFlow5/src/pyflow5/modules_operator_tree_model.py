from dataclasses import dataclass, field
from typing import Iterable

from pygraphrt.graph_rt import GraphRT
from qtpy.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal, Slot
from pygraphrt.abstract_module_rt import AbstractModule, OperatorRef
from pygraphrt.script_module import ScriptModuleRT


# @dataclass(eq=False)
# class _ModuleItem:
#     module: AbstractModule
#     operators: list["_OperatorItem"] = field(default_factory=list)


# @dataclass(eq=False)
# class _OperatorItem:
#     ref: OperatorRef
#     parent: _ModuleItem


class ModulesOperatorsTreeModel(QAbstractItemModel):
    """One-column module/operator browser, observing externally owned modules.

    Rows are snapshots: runtime notifications arrive after changes, so Qt's
    begin/end calls bracket changes to these snapshots rather than the runtime.
    Modules and this model must be used on the same Qt thread.
    """

    scriptSaveFailed = Signal(str)

    ModuleRole = int(Qt.ItemDataRole.UserRole) + 1
    OperatorRole = ModuleRole + 1
    NameRole = OperatorRole + 1
    SourceRole = NameRole + 1

    def __init__(self, parent=None)->None:
        super().__init__(parent)
        self._graph:GraphRT|None = None

    # RESET
    def setGraph(self, graph:GraphRT|None):
        """Observe the runtime's module collection instead of maintaining our own."""
        self.beginResetModel()
        self._graph = graph
        self.endResetModel()

    # READ
    def columnCount(self, parent=QModelIndex()):
        return 1

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        
        if not parent.isValid():
            # Modules
            if row == 0:
                # return the index for the first module
                definitions_module = self._graph.definitions()
                return self.createIndex(row, column, definitions_module)
            
            elif row < len(self._graph.imports()+1):
                import_module = self._graph.imports()[row-1]
                return self.createIndex(row, column, import_module)
            
        elif parent.isValid() and parent.model() is self:
            # Operators
            module = parent.internalPointer()
            assert isinstance(module, AbstractModule)
            operator = module.operators[row]
            return self.createIndex(row, column, operator)
        
        else:
            return QModelIndex()

    def rowCount(self, parent=QModelIndex()):
        if self._graph is None:
            return 0

        if not parent.isValid():
            # Modules has operators as children
            definitions = self._graph.definitions()
            imports = self._graph.imports()
            return len(imports) + 1
        
        elif parent.isValid() and parent.model() is self:
            # Operators has no children
            return 0
        else:
            return 0

    def parent(self, child:QModelIndex)->QModelIndex: # type: ignore
        if self._graph is None:
            return QModelIndex()
        
        if not child.isValid() or child.model() is not self:
            return QModelIndex()
        
        data = child.internalPointer()
        if isinstance(data, AbstractModule):
            # A module has no parent in this tree
            return QModelIndex()
        
        elif isinstance(data, OperatorRef):
            # find the parent module of the operator
            op = data
            module = op.module
            if module is not None:
                if module is self._graph.definitions():
                    row = 0
                    return self.createIndex(0, 0, module)
                else:
                    idx = list(self._graph.imports()).index(module)
                    return self.createIndex(idx+1, 0, module)
            else:
                return QModelIndex()
        else:
            return QModelIndex()
            
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.model() is not self:
            return None
        data = index.internalPointer()

        match data:
            case AbstractModule():
                module = data
                match role:
                    case Qt.ItemDataRole.DisplayRole | Qt.ItemDataRole.EditRole:
                        return module.get_name()
                    
                    case self.SourceRole:
                        return module.get_source()
                    
                    case _:
                        return None
                    
            case OperatorRef():
                operator_ref = data.module
                match role:
                    case Qt.ItemDataRole.DisplayRole | Qt.ItemDataRole.EditRole:
                        return operator_ref.get_name()
                    
                    case _:
                        return None
            case _:
                return None

    def flags(self, index:QModelIndex):
        if not index.isValid() or index.model() is not self:
            return Qt.ItemFlag.NoItemFlags

        data = index.internalPointer()
        match data:
            case OperatorRef():
                return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            
            case AbstractModule():
                return Qt.ItemFlag.NoItemFlags
            
            case _:
                return Qt.ItemFlag.NoItemFlags

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if section == 0 and orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return "Modules and operators"
        return None

    # CREATE
    def importModule(self, file_path: str) -> None:
        assert self._graph is not None, "Graph must be initialized before importing a module."
        self.rowCount()
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
        self._graph.add_import(file_path)
        self.endInsertRows()

    # UPDATE
    def setData(self, index:QModelIndex, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.model() is not self:
            return False
        data = index.internalPointer()

        match data:
            case AbstractModule() as module:
                match role:
                    case Qt.ItemDataRole.EditRole:
                        print("cant set non-definitions modul name")
                        return False
                    case self.SourceRole:
                        module.set_script(value)
                        return True
                    case _:
                        return False
                    
            case OperatorRef() as operator_ref:
                return False
            case _:
                return False
    
    # DELETE
    def removeModule(self, index:QModelIndex)->bool:
        if self._graph is None:
            return False

        data = index.internalPointer()

        if isinstance(data, AbstractModule):
            row = index.row()
            if row == 0:
                print("cant remove definition module")
                return False
            
            self.beginRemoveRows(QModelIndex(), row, row)
            module = data
            self._graph.remove_import(module)
            self.endRemoveRows()
            return True
        else:
            return False

            
    # SYNC
    def getModule(self, index):
        if not index.isValid() or index.model() is not self:
            return None
        
        data = index.internalPointer()
        if isinstance(data, AbstractModule):
            return data
        return None

    def getOperator(self, index):
        if not index.isValid() or index.model() is not self:
            return None
        
        data = index.internalPointer()
        if isinstance(data, OperatorRef):
            return data
        
        return None
    