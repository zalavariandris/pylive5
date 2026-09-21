from qtpy.QtWidgets import QDialog, QVBoxLayout, QTreeView, QDialogButtonBox
from qtpy.QtCore import QAbstractItemModel, QModelIndex


class SelectionDialog(QDialog):
    def __init__(self, model: QAbstractItemModel, parent=None):
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
        # self._operator_tree.selectionModel().currentChanged.connect(self._update_accept)
        # model.rowsRemoved.connect(self._update_accept)
        # model.modelReset.connect(self._update_accept)
        for row in range(model.rowCount()):
            module_index = model.index(row, 0)
            if model.rowCount(module_index):
                self._operator_tree.setCurrentIndex(model.index(0, 0, module_index))
                break
        # self._update_accept()
        self._operator_tree.setFocus()

    # def _update_accept(self, *args):
    #     selected_index = self.selected_index()
    #     CanAccept = self.canAccept(selected_index)
    #     print(f"CanAccept {selected_index}: {CanAccept}")
    #     self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(CanAccept)

    def _on_activated(self, index):
        self.accept()

    # def canAccept(self, index:QModelIndex):
    #     # todo: Implement more sophisticated acceptance logic if needed
    #     # currently only accepts indexes that have a valid parent
    #     if index.isValid() and index.parent().isValid():
    #         return True
    #     return False

    # def accept(self):
    #     selected_index = self.selected_index()
    #     if self.canAccept(selected_index):
    #         super().accept()

    def selected_index(self):
        return self._operator_tree.currentIndex()
