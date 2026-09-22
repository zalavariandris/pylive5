from qtpy.QtCore import QSortFilterProxyModel, Qt

from pygraphrt.script_module import ScriptModuleRT
from .module_operator_tree_model import ModuleOperatorTreeModel


class ModulesListModel(QSortFilterProxyModel):
    """Flat view of editable modules in the shared module/operator model."""

    NameRole = ModuleOperatorTreeModel.NameRole
    CodeRole = ModuleOperatorTreeModel.CodeRole
    ModuleRole = ModuleOperatorTreeModel.ModuleRole

    def __init__(self, source: ModuleOperatorTreeModel, parent=None):
        super().__init__(parent)
        self.setSourceModel(source)

    def filterAcceptsRow(self, source_row, source_parent):
        if source_parent.isValid():
            return False
        index = self.sourceModel().index(source_row, 0, source_parent)
        return isinstance(index.data(self.ModuleRole), ScriptModuleRT)

    def flags(self, index):
        if not index.isValid() or index.model() is not self:
            return Qt.ItemFlag.NoItemFlags
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable)

    def addModule(self, module: ScriptModuleRT):
        self.sourceModel().addModule(module)

    def removeModule(self, row: int):
        index = self.index(row, 0)
        if index.isValid():
            self.sourceModel().removeModule(index.data(self.ModuleRole))
