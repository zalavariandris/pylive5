from .properties_editor.node_input_delegate import NodeInputDelegate

from .base_details_view import BaseDetailsView
from qtpy.QtWidgets import QAbstractScrollArea, QFrame, QHeaderView, QLabel, QSizePolicy, QTableView
from qtpy.QtCore import QAbstractItemModel

class NodeInspectorView(BaseDetailsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehaviour(BaseDetailsView.SelectionBehaviour.FirstSelected)
        # self.setTitle("Node Inspector")
        # self._label = QLabel("Node Inspector")
        # self.setBodyWidget(self._label)

        self._tableview = QTableView(self)
        self._tableview.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        self._tableview.horizontalHeader().hide()
        self._tableview.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        self._tableview.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._tableview.setItemDelegateForColumn(
            1, 
            NodeInputDelegate(self._tableview)
        )
        # set table column resizing
        table_header = self._tableview.horizontalHeader()
        table_header.setStretchLastSection(True)
        table_header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table_header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )

        self.setBodyWidget(self._tableview)

    def setModel(self, model:QAbstractItemModel):
        super().setModel(model)
        self._tableview.setModel(model)

    def showCurrentRootEvent(self):
        print(f"show current root: {self.currentRoot().data()}")
        if self.currentRoot().isValid() == False:
            # self._label.setText("No node selected")
            self._tableview.setVisible(False)
        else:
            # self._label.setText(self.currentRoot().data())
            self._tableview.setRootIndex(self.currentRoot())
            self._tableview.setVisible(True)
        return super().showCurrentRootEvent()
