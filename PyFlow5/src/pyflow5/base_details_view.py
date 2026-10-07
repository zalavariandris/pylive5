from enum import StrEnum
from typing import Callable, cast

from qtpy.QtCore import (
    QAbstractItemModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    Qt,
    Signal,
    SignalInstance,
    Slot
)

from qtpy.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QHBoxLayout,
    QVBoxLayout, 
    QWidget
)


class BaseDetailsView(QFrame):
    class SelectionBehaviour(StrEnum):
        FirstSelected = "first"
        LastSelected = "last"
        Current = "current"

    def __init__(self, parent=None)->None:
        super().__init__(parent)

        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Plain)
        
        # private members
        self._model: QAbstractItemModel|None = None
        self._model_connections: list[tuple[SignalInstance, Callable]] = []
        self._nodes_selection_model: QItemSelectionModel|None = None
        self._selection_model_connections: list[tuple[SignalInstance, Callable]] = []
        self._current_root:QModelIndex = QModelIndex()
        self._selection_behaviour: BaseDetailsView.SelectionBehaviour = BaseDetailsView.SelectionBehaviour.Current

        # lock switch
        self._viewer_lock_switch = QCheckBox("-node-", self)
        self._viewer_lock_switch.setToolTip("Keep viewing this output when the selection changes.")
        self._viewer_lock_switch.setChecked(False)
        self._viewer_lock_switch.toggled.connect(lambda checked: None)

        # header
        viewer_header = QHBoxLayout()
        # viewer_header.addWidget(QLabel("Viewer", self))
        viewer_header.addStretch()
        viewer_header.addWidget(self._viewer_lock_switch)

        # main layout
        viewer_layout = QVBoxLayout(self)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.addLayout(viewer_header)

        self._body_widget:QWidget = QLabel("-body-", self)
        viewer_layout.addWidget(self._body_widget)

    def setSelectionBehaviour(self, behaviour: SelectionBehaviour) -> None:
        self._selection_behaviour = behaviour

    def selectionBehaviour(self):
        return self._selection_behaviour

    def setBodyWidget(self, widget: QWidget) -> None:
        layout = cast(QVBoxLayout, self.layout())
        if self._body_widget is not None:
            layout.removeWidget(self._body_widget)
            self._body_widget.deleteLater()

        self._body_widget = widget
        layout.addWidget(widget)

    def model(self):
        return self._model

    def setModel(self, model: QAbstractItemModel|None):
        assert isinstance(model, QAbstractItemModel) or model is None

        if self._model:
            # Disconnect previous connections
            for signal, slot in self._model_connections:
                try:
                    signal.disconnect(slot)
                except TypeError as err:
                    print(f"Failed to disconnect signal {signal} from slot {slot} due to {err}")
            self._model_connections.clear()
            
        if model:
            # Connect new model signals
            self._model_connections = [
                (model.modelReset,  self._on_model_reset),
                (model.dataChanged, self._on_data_changed),
                (model.rowsRemoved, self._on_rows_removed)
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)
        
        self._model = model
        # self._setCurrentIndex(QModelIndex())

    def currentRoot(self)->QModelIndex:
        return self._current_root

    def _on_selection_changed(self, selected:QItemSelection, deselected:QItemSelection):
        if self._viewer_lock_switch.isChecked():
            print("- Lock is checked, cant set current node")
            return

        if self._selection_behaviour not in  {BaseDetailsView.SelectionBehaviour.FirstSelected, BaseDetailsView.SelectionBehaviour.LastSelected}:
            return

        match self._selection_behaviour:
            case BaseDetailsView.SelectionBehaviour.FirstSelected:
                first_index = selected.indexes()[0] if selected.indexes() else QModelIndex()
                self._current_root = first_index
                self._viewer_lock_switch.setText(f"{self._current_root.data()}") 
                self.showCurrentRootEvent()
            case BaseDetailsView.SelectionBehaviour.LastSelected:
                last_index = selected.indexes()[-1] if selected.indexes() else QModelIndex()
                self._current_root = last_index
                self._viewer_lock_switch.setText(f"{self._current_root.data()}")
                self.showCurrentRootEvent()
            case _:
                pass

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex):
        if self._viewer_lock_switch.isChecked():
            print("- Lock is checked, cant set current node")
            return
        
        if self._selection_behaviour != self.SelectionBehaviour.Current:
            return 
            
        self._current_root = current
        self._viewer_lock_switch.setText(f"{self._current_root.data()}")
        self.showCurrentRootEvent()

    def setSelectionModel(self, selection_model: QItemSelectionModel):
        assert isinstance(selection_model, QItemSelectionModel) or selection_model is None

        if selection_model is self._nodes_selection_model:
            return
        
        if self._nodes_selection_model:
            for signal, slot in self._selection_model_connections:
                signal.disconnect(slot)
            self._selection_model_connections = []
            self._nodes_selection_model = None

        if selection_model:
            self._selection_model_connections = [
                (selection_model.selectionChanged, self._on_selection_changed),
                (selection_model.currentChanged, self._on_current_changed),
            ]
            for signal, slot in self._selection_model_connections:
                signal.connect(slot)
            self._nodes_selection_model = selection_model

    def _on_model_reset(self):
        self._current_root = QModelIndex()
        self.showCurrentRootEvent()

    def _on_data_changed(self, topLeft:QModelIndex, bottomRight:QModelIndex, roles:list[int]=[]):
        columns = range(topLeft.column(), bottomRight.column() + 1)

        if 0 not in columns:
            return

        if topLeft.parent() != self._current_root.parent():
            return

        if bottomRight.parent() != self._current_root.parent():
            return

        rows = range(topLeft.row(), bottomRight.row() + 1)
        if self._current_root.row() in rows:
            self.showCurrentRootEvent()

    def _on_rows_removed(self, parent:QModelIndex, first: int, last: int):
        if parent != self._current_root.parent():
            return
        
        if self._current_root.row() >= first and self._current_root.row() <= last:
            self.showCurrentRootEvent()

    def showCurrentRootEvent(self):
        # todo: make it an abstrat emthod
        #todo:
        """this will be called automatically when the current selection changes."""
        pass
    