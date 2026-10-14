from __future__ import annotations

from qtpy.QtCore import QItemSelection, QModelIndex, QSortFilterProxyModel
from qtpy.QtCore import QItemSelectionModel


class ProxyItemSelectionModel(QItemSelectionModel):
    """Keeps a proxy model selection in sync with a source-model selection."""

    def __init__(
        self,
        model: QSortFilterProxyModel|None=None,
        selection_model: QItemSelectionModel|None=None,
        parent=None,
    ) -> None:
        super().__init__(model, parent)
        self._model: QSortFilterProxyModel|None = None
        self._selection_model:QItemSelectionModel|None = None
        self._syncing = False

        self.setModel(model)
        self.setSelectionModel(selection_model)
        
        self.selectionChanged.connect(self._sync_to_source_selection)
        self.currentChanged.connect(self._sync_to_source_current)
        
    def setModel(self, model: QSortFilterProxyModel|None) -> None:
        self._model = model

        self._apply_source_selection()
        self._apply_source_current()
    
    def setSelectionModel(self, selection_model: QItemSelectionModel|None) -> None:
        if self._selection_model:
            self._selection_model.selectionChanged.disconnect(self._sync_from_source_selection)
            self._selection_model.currentChanged.disconnect(self._sync_from_source_current)

        if selection_model:
            selection_model.selectionChanged.connect(self._sync_from_source_selection)
            selection_model.currentChanged.connect(self._sync_from_source_current)

        self._selection_model = selection_model

        self._apply_source_selection()
        self._apply_source_current()

    def _sync_to_source_selection(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        if self._syncing:
            return
        
        if self._selection_model is None:
            return
        
        self._selection_model.select(
            self._model.mapSelectionToSource(self.selection()),
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )

    def _sync_to_source_current(self, current: QModelIndex, previous: QModelIndex) -> None:
        if self._syncing:
            return
        
        if self._selection_model is None:
            return
        
        source_current = self._model.mapToSource(current)
        self._selection_model.setCurrentIndex(
            source_current,
            QItemSelectionModel.SelectionFlag.NoUpdate,
        )

    def _sync_from_source_selection(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        if self._syncing:
            return
        self._apply_source_selection()

    def _sync_from_source_current(self, current: QModelIndex, previous: QModelIndex) -> None:
        if self._syncing:
            return
        self._apply_source_current()

    def _apply_source_selection(self) -> None:
        if self._selection_model is None:
            return
        
        self._syncing = True
        try:
            self.select(
                self._model.mapSelectionFromSource(self._selection_model.selection()),
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
        finally:
            self._syncing = False

    def _apply_source_current(self) -> None:
        if self._selection_model is None:
            return
        
        self._syncing = True
        try:
            proxy_current = self._model.mapFromSource(self._selection_model.currentIndex())
            self.setCurrentIndex(
                proxy_current,
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        finally:
            self._syncing = False
