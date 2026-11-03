from enum import StrEnum
from typing import Callable, cast

from qtpy.QtCore import (
    QAbstractItemModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPersistentModelIndex,
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

from myqtx.widgets.lock_switch import LockSwitch


class BaseDetailsView(QFrame):
    currentChanged = Signal(QModelIndex, QModelIndex)

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
        self._current_root: QPersistentModelIndex = QPersistentModelIndex()
        self._selection_behaviour: BaseDetailsView.SelectionBehaviour = BaseDetailsView.SelectionBehaviour.Current

        # lock switch
        self._lock_switch = LockSwitch("-node-", self)
        self._lock_switch.setToolTip("Keep viewing this output when the selection changes.")
        self._lock_switch.setChecked(False)
        self._lock_switch.toggled.connect(lambda checked: self._on_lock_toggled(checked))

        # header
        viewer_header = QHBoxLayout()
        # viewer_header.addWidget(QLabel("Viewer", self))
        viewer_header.addStretch()
        viewer_header.addWidget(self._lock_switch)

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
                (model.modelAboutToBeReset, self._on_model_reset),
                (model.modelReset,  self._on_model_reset),
                (model.dataChanged, self._on_data_changed),
                (model.rowsAboutToBeRemoved, self._on_rows_about_to_be_removed),
                (model.rowsRemoved, self._on_rows_removed)
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)
        
        self._model = model
        self._on_model_reset()

    def currentRoot(self)->QModelIndex:
        return QModelIndex(self._current_root)

    def _on_lock_toggled(self, checked: bool) -> None:
        if checked:
            return
        previous_root = self.currentRoot()
        if self._nodes_selection_model is None:
            self._current_root = QPersistentModelIndex()
        else:
            match self._selection_behaviour:
                case BaseDetailsView.SelectionBehaviour.FirstSelected:
                    indexes = self._nodes_selection_model.selectedIndexes()
                    first_index = indexes[0] if indexes else QModelIndex()
                    self._current_root = QPersistentModelIndex(first_index)
                case BaseDetailsView.SelectionBehaviour.LastSelected:
                    indexes = self._nodes_selection_model.selectedIndexes()
                    last_index = indexes[-1] if indexes else QModelIndex()
                    self._current_root = QPersistentModelIndex(last_index)
                case _:
                    self._current_root = QPersistentModelIndex(
                        self._nodes_selection_model.currentIndex(),
                    )
        if self.currentRoot() != previous_root:
            self.currentChanged.emit(self.currentRoot(), previous_root)
        self.showCurrentRootEvent(self.currentRoot(), [])

    def _on_selection_changed(
        self, selected: QItemSelection, deselected: QItemSelection,
    ) -> None:
        if self._lock_switch.isChecked():
            return

        if self._selection_behaviour not in  {BaseDetailsView.SelectionBehaviour.FirstSelected, BaseDetailsView.SelectionBehaviour.LastSelected}:
            return

        previous_root = self.currentRoot()
        match self._selection_behaviour:
            case BaseDetailsView.SelectionBehaviour.FirstSelected:
                indexes = self._nodes_selection_model.selectedIndexes()
                first_index = indexes[0] if indexes else QModelIndex()
                self._current_root = QPersistentModelIndex(first_index)
                self._lock_switch.setText(f"{self.currentRoot().siblingAtColumn(0).data()}")
            case BaseDetailsView.SelectionBehaviour.LastSelected:
                indexes = self._nodes_selection_model.selectedIndexes()
                last_index = indexes[-1] if indexes else QModelIndex()
                self._current_root = QPersistentModelIndex(last_index)
                self._lock_switch.setText(f"{self.currentRoot().siblingAtColumn(0).data()}")
            case _:
                pass
        if self.currentRoot() != previous_root:
            self.currentChanged.emit(self.currentRoot(), previous_root)
        self.showCurrentRootEvent(self.currentRoot(), [])

    def _on_selection_current_changed(
        self, current: QModelIndex, previous: QModelIndex,
    ) -> None:
        if self._lock_switch.isChecked():
            return
        
        if self._selection_behaviour != self.SelectionBehaviour.Current:
            return 
            
        previous_root = self.currentRoot()
        self._current_root = QPersistentModelIndex(current)
        self._lock_switch.setText(f"{self.currentRoot().siblingAtColumn(0).data()}")
        if current != previous_root:
            self.currentChanged.emit(current, previous_root)
        self.showCurrentRootEvent(self.currentRoot(), [])

    def selectionModel(self) -> QItemSelectionModel:
        return self._nodes_selection_model

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
                (selection_model.currentChanged, self._on_selection_current_changed),
            ]
            for signal, slot in self._selection_model_connections:
                signal.connect(slot)
            self._nodes_selection_model = selection_model
            self._on_selection_changed(selection_model.selection(), QItemSelection())
            self._on_selection_current_changed(selection_model.currentIndex(), QModelIndex())

    def _on_model_reset(self) -> None:
        previous_root = self.currentRoot()
        self._current_root = QPersistentModelIndex()
        if previous_root.isValid():
            self.currentChanged.emit(QModelIndex(), previous_root)
        self.showCurrentRootEvent(QModelIndex(), [])

    def _on_data_changed(
        self, topLeft: QModelIndex, bottomRight: QModelIndex, roles: list[int],
    ) -> None:
        if not self._current_root.isValid():
            return

        if topLeft.parent() != self._current_root.parent():
            return

        if bottomRight.parent() != self._current_root.parent():
            return

        rows = range(topLeft.row(), bottomRight.row() + 1)
        if self._current_root.row() in rows:
            self.showCurrentRootEvent(self.currentRoot(), roles)

    def _on_rows_about_to_be_removed(
        self, parent: QModelIndex, first: int, last: int,
    ) -> None:
        index = self.currentRoot()
        while index.isValid():
            if index.parent() == parent and first <= index.row() <= last:
                self._on_model_reset()
                return
            index = index.parent()

    def _on_rows_removed(self, parent: QModelIndex, first: int, last: int) -> None:
        self.showCurrentRootEvent(self.currentRoot(), [])

    def showCurrentRootEvent(self, index: QModelIndex, roles: list[int] = [])->None:
        # todo: make it an abstrat emthod
        #todo:
        """this will be called automatically when the current selection changes."""
        pass
