from qtpy.QtCore import QAbstractItemModel, QModelIndex, Qt
from qtpy.QtWidgets import QSizePolicy, QStyledItemDelegate, QWidget, QLabel, QPushButton


from .base_details_view import BaseDetailsView
from .formview import FormView


class NodeInspectorView(BaseDetailsView):
    def __init__(
        self, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setSelectionBehaviour(BaseDetailsView.SelectionBehaviour.FirstSelected)
        self.setAutoFillBackground(True)

        self._form_view = FormView(self)
        self._form_view.hide()

        self.setBodyWidget(self._form_view)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def setFieldDelegate(self, delegate: QStyledItemDelegate) -> None:
        self._form_view.setFieldDelegate(delegate)

    def setLabelDelegate(self, delegate: QStyledItemDelegate) -> None:
        self._form_view.setLabelDelegate(delegate)

    def setModel(self, model: QAbstractItemModel | None) -> None:
        super().setModel(model)
        self._current_root = QModelIndex()
        self._form_view.setModel(model)
        self.showCurrentRootEvent(self._current_root)

    def showCurrentRootEvent(self, index: QModelIndex, roles: list[int] = [])->None:
        root = self.currentRoot()
        self._form_view.setVisible(root.isValid())
        if root.isValid():
            self._form_view.setRootIndex(root.siblingAtColumn(0))
