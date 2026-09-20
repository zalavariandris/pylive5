from qtpy.QtWidgets import QDialog, QVBoxLayout, QTreeView, QDialogButtonBox
from pygraphrt.abstract_module_rt import OperatorRef
from pyflow5.module_operator_tree_model import ModuleOperatorTreeModel


class OperatorSelectionDialog(QDialog):
    def __init__(self, model: ModuleOperatorTreeModel, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Operator")
        self.setMinimumWidth(280)
        layout = QVBoxLayout(self)
        self._operator_tree = QTreeView(self)
        self._operator_tree.setModel(model)
        self._operator_tree.expandAll()
        layout.addWidget(self._operator_tree)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._operator_tree.activated.connect(self._on_activated)
        self._operator_tree.selectionModel().currentChanged.connect(self._update_accept)
        model.rowsRemoved.connect(self._update_accept)
        model.modelReset.connect(self._update_accept)
        for row in range(model.rowCount()):
            module_index = model.index(row, 0)
            if model.rowCount(module_index):
                self._operator_tree.setCurrentIndex(model.index(0, 0, module_index))
                break
        self._update_accept()
        self._operator_tree.setFocus()

    def _update_accept(self, *args):
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.selected_operator() is not None)

    def _on_activated(self, index):
        self.accept()

    def accept(self):
        if self.selected_operator() is not None:
            super().accept()

    def selected_operator(self) -> OperatorRef | None:
        index = self._operator_tree.currentIndex()
        return index.data(ModuleOperatorTreeModel.OperatorRole)
