from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QVBoxLayout, QListWidget, QListWidgetItem, QDialogButtonBox
from typing import Iterable


class OperatorSelectionDialog(QDialog):
    def __init__(self, items: Iterable[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Operator")
        self.setMinimumWidth(280)

        layout = QVBoxLayout(self)

        # List of operators
        self._operator_list = QListWidget(self)
        self._operator_list.addItems(items)
        self._operator_list.setCurrentRow(0)          # start with first item selected
        self._operator_list.setFocus()                # keyboard focus on open
        layout.addWidget(self._operator_list)

        # Optional buttons (still useful for mouse users)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Keyboard behaviour
        self._operator_list.itemActivated.connect(self._on_item_activated)  # Enter / double-click
        self._operator_list.itemDoubleClicked.connect(self.accept)

    def _on_item_activated(self, item: QListWidgetItem):
        """Enter key or activation → accept the dialog."""
        self.accept()

    def selected_operator(self) -> str | None:
        """Return the currently selected operator name, or None if nothing is selected."""
        item = self._operator_list.currentItem()
        return item.text() if item else None
    