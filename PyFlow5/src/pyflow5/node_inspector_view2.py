from .properties_editor.node_input_delegate import NodeInputDelegate

from .base_details_view import BaseDetailsView
from qtpy.QtWidgets import QAbstractScrollArea, QFrame, QHeaderView, QLabel, QLineEdit, QSizePolicy, QTableView
from qtpy.QtCore import QAbstractItemModel
from myqtx import FormWidget


class NodeInspectorView(BaseDetailsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehaviour(BaseDetailsView.SelectionBehaviour.FirstSelected)
        self._form_widget = FormWidget(self)
        # self._form_widget.submitted.connect(self.onFormSubmitted)
        self._form_widget.value_changed.connect(self.onFormValueChanged)

        self.setBodyWidget(self._form_widget)

    def setModel(self, model:QAbstractItemModel):
        super().setModel(model)

    def showCurrentRootEvent(self):
        print(f"show current root: {self.currentRoot().data()}")
        if self.currentRoot().isValid() == False:
            # self._label.setText("No node selected")
            self._form_widget.clear()
        else:
            # self._label.setText(self.currentRoot().data())
            self._form_widget.clear()
            model = self.model()
            for row in range(model.rowCount(self.currentRoot())):
                name = model.data(model.index(row, 0, parent=self.currentRoot()))
                value = model.data(model.index(row, 1, parent=self.currentRoot()))
                widget = QLineEdit()
                widget.setText(str(value))
                self._form_widget.insertEditor(row, 
                    name, 
                    widget,
                    getter=lambda w=widget: w.text(),
                    setter=lambda v, w=widget: w.setText(v),
                    signal=widget.textChanged
                ) 
            self._form_widget.setVisible(True)

    # def onFormSubmitted(self, values: dict[str, object]) -> None:
    #     print(f"Form submitted with values: {values}")
    #     model = self.model()
    #     model.setData(self.currentRoot(), values)
    #     return super().showCurrentRootEvent()

    def onFormValueChanged(self, name: str, value: object) -> None:
        # find row with name and update its value in the model

        model = self.model()
        if model is None:
            return

        if not self.currentRoot().isValid():
            return
        
        for row in range(model.rowCount(self.currentRoot())):
            if model.data(model.index(row, 0, parent=self.currentRoot())) == name:
                break
        input_index = model.index(row, 1, parent=self.currentRoot())
        model.setData(input_index, value)
