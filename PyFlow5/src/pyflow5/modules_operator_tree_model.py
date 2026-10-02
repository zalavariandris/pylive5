from pygraphrt import (
    AbstractModule,
    GraphDefinitionRT,
    ImportModuleRT,
    ScriptModuleRT
)
from pygraphrt.abstract_operator import AbstractOperator
from pygraphrt.script_module import ScriptOperatorRef
from qtpy.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt

import pygraphrt as rt

class ModulesOperatorsTreeModel(QAbstractItemModel):
    """One-column tree reading modules and operators from a graph runtime.

    Module indexes have internal ID -1. Operator indexes store their parent
    module's row. Mapping helpers translate between these indexes and
    the registered modules and operators.
    """

    SourceRole = int(Qt.ItemDataRole.UserRole) + 4

    NO_PARENT = 0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._registry: rt.ModuleRegistry | None = None

    def sourceRegistry(self) -> rt.ModuleRegistry | None:
        return self._registry

    def setSourceRegistry(self, registry: rt.ModuleRegistry | None) -> None:
        """Replace the runtime used by this model."""
        self.beginResetModel()
        self._registry = registry
        self.endResetModel()

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = QModelIndex(),
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        module_id = parent.row() + 1 if parent.isValid() else self.NO_PARENT
        return self.createIndex(row, column, module_id)

    def parent(self, child: QModelIndex) -> QModelIndex:  # type: ignore
        if self._registry is None or not child.isValid():
            return QModelIndex()
        if child.model() is not self or child.column() != 0:
            return QModelIndex()

        module_id = child.internalId()
        if module_id == self.NO_PARENT:
            return QModelIndex()

        return self.index(module_id-1, 0)

    def mapToSource(
            self, index: QModelIndex
        ) -> AbstractModule | AbstractOperator | None:
            if self._registry is None:
                return None
    
            if not index.isValid():
                return None
            
            if index.model() is not self:
                return None
    
            if index.column() != 0:
                return None
    
            modules = list(self._registry.modules())
            module_id = index.internalId()
            module_row = index.row() if module_id == self.NO_PARENT else module_id -1
            if not 0 <= module_row < len(modules):
                return None
    
            module = modules[module_row]
            if module_id == self.NO_PARENT:
                return module
    
            operators = list(module.operators())
            if not 0 <= index.row() < len(operators):
                return None
            return operators[index.row()]
    
    def mapFromSource(
        self, source: AbstractModule | AbstractOperator | None
    ) -> QModelIndex:
        if self._registry is None:
            return QModelIndex()

        if not isinstance(source, (AbstractModule, AbstractOperator)):
            return QModelIndex()

        for module_row, module in enumerate(self._registry.modules()):
            module_index = self.index(module_row, 0)
            if source is module:
                return module_index

            if isinstance(source, AbstractOperator):
                for operator_row, operator in enumerate(module.operators()):
                    if operator == source:
                        return self.index(operator_row, 0, module_index)

        return QModelIndex()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if self._registry is None:
            return 0

        modules = self._registry.modules()
        if not parent.isValid():
            return len(modules)

        if parent.model() is not self or parent.column() != 0:
            return 0
        if parent.internalId() != self.NO_PARENT:
            return 0

        module_row = parent.row()
        if not 0 <= module_row < len(modules):
            return 0

        return len(list(modules[module_row].operators()))
    
    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object | None:
        item:AbstractModule | AbstractOperator | None = self.mapToSource(index)
        if item is None:
            return None

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            match item:
                case ImportModuleRT() as im:
                    return im.get_display_name()
                case ScriptModuleRT() as sm:
                    return sm.get_display_name()
                case ScriptOperatorRef() as operator:
                    return operator.get_name()
                case _:
                    assert False, f"Unexpected item type in modules and operators tree: {item}"
        
        if role == self.SourceRole and isinstance(item, ScriptModuleRT):
            return item.get_source()
        
        return None

    

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        item = self.mapToSource(index)
        match item:
            case AbstractModule() | AbstractOperator():
                return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            case _:
                return Qt.ItemFlag.NoItemFlags

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
            return "Modules and operators"
        return None

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if role != self.SourceRole or not isinstance(value, str):
            return False

        module = self.mapToSource(index)
        if not isinstance(module, ScriptModuleRT):
            return False

        module.set_script(value)
        return True

    def addEmbeddedModule(self, name:str|None = None) -> QModelIndex|None:
        assert self._registry is not None, "Graph must be initialized before adding a module."
        
        existing_module_names = {module.get_display_name() for module in self._registry.modules()}
        import pytools
        generator = pytools.UniqueNameGenerator(existing_module_names)
        unique_name = generator("_local_")
        script_module = rt.ScriptModuleRT(name=unique_name)
        script_module.set_script("") 
        row = self.rowCount()
        self.beginInsertRows(QModelIndex(), row, row)
        self._registry.add_module(script_module)
        self.endInsertRows()
        return self.index(row, 0)

    def importModule(self, file_path: str) -> QModelIndex|None:
        assert self._registry is not None, "Graph must be initialized before importing a module."
        module = ImportModuleRT(file_path)
        row = self.rowCount()
        self.beginInsertRows(QModelIndex(), row, row)
        self._registry.add_module(module)
        self.endInsertRows()
        return self.index(row, 0)

    def removeModule(self, index: QModelIndex) -> bool:
        if self._registry is None:
            return False

        module = self.mapToSource(index)
        if not isinstance(module, ImportModuleRT):
            return False

        row = index.row()
        self.beginRemoveRows(QModelIndex(), row, row)
        self._registry.remove_import(module)
        self.endRemoveRows()
        return True


