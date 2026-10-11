from pygraphrt.abstract_operator import ParameterData
from qtpy.QtCore import QAbstractItemModel, QModelIndex, Qt
from qtpy.QtWidgets import QSizePolicy, QStyledItemDelegate, QWidget, QLabel, QPushButton


from .base_details_view import BaseDetailsView
from .formview import FormView
from .node_input_delegate import NodeInputFieldDelegate
from .node_input_delegate import NodeInputLabelDelegate


class NodeInspectorView(BaseDetailsView):
    def __init__(
        self, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setSelectionBehaviour(BaseDetailsView.SelectionBehaviour.FirstSelected)

        self._form_view = FormView(self)
        self._field_delegate = NodeInputFieldDelegate(parent=self)
        self._form_view.setFieldDelegate(self._field_delegate)
        self._labels_delegate = NodeInputLabelDelegate(parent=self)
        self._form_view.setLabelDelegate(self._labels_delegate)
        self._form_view.hide()

        self.setBodyWidget(self._form_view)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    # def setFieldDelegate(self, delegate: NodeInputDelegate) -> None:
    #     self._form_view.setFieldDelegate(delegate)

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
