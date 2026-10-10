from qtpy.QtCore import QAbstractItemModel, QModelIndex
from qtpy.QtWidgets import QSizePolicy, QWidget


from .base_details_view import BaseDetailsView
from .formview import FormView
from .node_input_delegate import NodeInputDelegate


class NodeInspectorView(BaseDetailsView):
    def __init__(
        self, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setSelectionBehaviour(BaseDetailsView.SelectionBehaviour.FirstSelected)

        self._form_view = FormView(self)
        self._form_view.hide()
        self.setBodyWidget(self._form_view)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def setItemDelegate(self, delegate: NodeInputDelegate) -> None:
        self._form_view.setItemDelegate(delegate)

    def setModel(self, model: QAbstractItemModel | None) -> None:
        super().setModel(model)
        self._current_root = QModelIndex()
        self._form_view.setModel(model)
        self.showCurrentRootEvent()

    def showCurrentRootEvent(self) -> None:
        root = self.currentRoot()
        self._form_view.setVisible(root.isValid())
        if root.isValid():
            self._form_view.setRootIndex(root.siblingAtColumn(0))
