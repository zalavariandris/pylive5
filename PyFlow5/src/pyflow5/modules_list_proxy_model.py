from typing import cast
from qtpy.QtCore import QModelIndex, QSortFilterProxyModel, Qt

from pygraphrt.script_module import ScriptModuleRT
from .modules_operator_tree_model import ModulesOperatorsTreeModel


class ModulesListModel(QSortFilterProxyModel):
    """Flat view of editable modules in the shared module/operator model."""

    NameRole = ModulesOperatorsTreeModel.NameRole
    CodeRole = ModulesOperatorsTreeModel.SourceRole
    ModuleRole = ModulesOperatorsTreeModel.ModuleRole

    def __init__(self, source: ModulesOperatorsTreeModel, parent=None):
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

    def importModule(self, path: str):
        source_model = cast(ModulesOperatorsTreeModel, self.sourceModel())
        source_model.importModule(path)

    def removeModule(self, index:QModelIndex):
        if index.isValid():
            source_model = cast(ModulesOperatorsTreeModel, self.sourceModel())
            source_model.removeModule(index)
