from pygraphrt.abstract_module_rt import AbstractModule, OperatorRef
from pygraphrt.graph_rt import GraphRT
from pygraphrt.import_module import ImportModuleRT
from pygraphrt.script_module import ScriptModuleRT
from qtpy.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt


class ModulesOperatorsTreeModel(QAbstractItemModel):
    """One-column tree reading modules and operators from a graph runtime.

    Module indexes have internal ID zero. Operator indexes store their parent
    module's row plus one. Mapping helpers are conveniences for callers; Qt
    overrides do not depend on them.
    """

    ModuleRole = int(Qt.ItemDataRole.UserRole) + 1
    OperatorRole = int(Qt.ItemDataRole.UserRole) + 2
    SourceRole = int(Qt.ItemDataRole.UserRole) + 4

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._graph: GraphRT | None = None

    def setGraph(self, graph: GraphRT | None) -> None:
        """Replace the runtime used by this model."""
        self.beginResetModel()
        self._graph = graph
        self.endResetModel()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def index(
        self,
        row: int,
        column: int,
        parent: QModelIndex = QModelIndex(),
    ) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        module_id = parent.row() + 1 if parent.isValid() else 0
        return self.createIndex(row, column, module_id)

    def parent(self, child: QModelIndex) -> QModelIndex:  # type: ignore
        if self._graph is None or not child.isValid():
            return QModelIndex()
        if child.model() is not self or child.column() != 0:
            return QModelIndex()

        module_id = child.internalId()
        if module_id == 0:
            return QModelIndex()

        return self.index(module_id - 1, 0)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if self._graph is None:
            return 0

        modules = self._graph.modules()
        if not parent.isValid():
            return len(modules)

        if parent.model() is not self or parent.column() != 0:
            return 0
        if parent.internalId() != 0:
            return 0

        module_row = parent.row()
        if not 0 <= module_row < len(modules):
            return 0

        return len(list(modules[module_row].operators()))
    
    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object | None:
        if self._graph is None or not index.isValid():
            return None
        if index.model() is not self or index.column() != 0:
            return None

        modules = self._graph.modules()
        module_id = index.internalId()
        module_row = index.row() if module_id == 0 else module_id - 1
        if not 0 <= module_row < len(modules):
            return None

        item: AbstractModule | OperatorRef = modules[module_row]
        if module_id != 0:
            operators = list(item.operators())
            if not 0 <= index.row() < len(operators):
                return None
            item = operators[index.row()]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return item.get_display_name()
        if role == self.ModuleRole and isinstance(item, AbstractModule):
            return item
        if role == self.OperatorRole and isinstance(item, OperatorRef):
            return item
        if role == self.SourceRole and isinstance(item, ScriptModuleRT):
            return item.get_script()
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if (
            self.data(index, self.ModuleRole) is None
            and self.data(index, self.OperatorRole) is None
        ):
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

        module = self.data(index, self.ModuleRole)
        if not isinstance(module, ScriptModuleRT):
            return False

        module.set_script(value)
        return True

    def importModule(self, file_path: str) -> None:
        assert self._graph is not None, "Graph must be initialized before importing a module."
        module = ImportModuleRT(file_path)
        row = self.rowCount()
        self.beginInsertRows(QModelIndex(), row, row)
        self._graph.add_import(module)
        self.endInsertRows()

    def removeModule(self, index: QModelIndex) -> bool:
        if self._graph is None:
            return False

        module = self.data(index, self.ModuleRole)
        if not isinstance(module, ImportModuleRT):
            return False

        row = index.row()
        self.beginRemoveRows(QModelIndex(), row, row)
        self._graph.remove_import(module)
        self.endRemoveRows()
        return True

    def mapToSource(
        self, index: QModelIndex
    ) -> AbstractModule | OperatorRef | None:
        item = self.data(index, self.ModuleRole)
        if item is None:
            item = self.data(index, self.OperatorRole)
        return item if isinstance(item, (AbstractModule, OperatorRef)) else None

    def mapFromSource(
        self, source: AbstractModule | OperatorRef
    ) -> QModelIndex:
        if self._graph is None:
            return QModelIndex()

        module = source.module if isinstance(source, OperatorRef) else source
        try:
            module_row = self._graph.modules().index(module)
        except ValueError:
            return QModelIndex()

        module_index = self.index(module_row, 0)
        if isinstance(source, AbstractModule):
            return module_index

        try:
            operator_row = list(module.operators()).index(source)
        except ValueError:
            return QModelIndex()

        return self.index(operator_row, 0, module_index)
