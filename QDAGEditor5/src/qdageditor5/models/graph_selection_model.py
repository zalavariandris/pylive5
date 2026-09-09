import warnings
from typing import (
    Any, 
    Hashable, 
    Iterable, 
    Literal, 
    Tuple
)

from qtpy.QtCore import (
    QAbstractItemModel,
    QItemSelectionModel, 
    QObject,
    Qt,
    Signal
)

from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel, 
    NodeName, 
    InletName, 
    OutletName, 
    DirectionalLinkId
)

from enum import IntEnum


class GraphSelectionModel(QObject):
    currentNodeChanged = Signal(object, object) # current, previous
    nodesSelectionChanged = Signal(set, set) # selected, deselected
    currentLinkChanged = Signal(object, object) # current, previous
    linksSelectionChanged = Signal(set, set) # selected, deselected
    modelChanged = Signal()

    class SelectionFlag(IntEnum):
        Clear = 0x01
        Select = 0x02
        Deselect = 0x04
        Toggle = 0x08
        Current = 0x10
        ClearAndSelect = Clear | Select


    def __init__(self, model: AbstractDAGModel, parent: QObject | None = None):
        super().__init__(parent=parent)
        self._current_node: NodeName | None = None
        self._selected_nodes: set[NodeName] = set()
        self._current_link: DirectionalLinkId | None = None
        self._selected_links: set[DirectionalLinkId] = set()

        self._model: AbstractDAGModel | None = None
        self._connections = []
        self.setModel(model)

    def setModel(self, model: AbstractDAGModel):
        if self._model == model:
            return # Prevent unnecessary resets
        
        # Clear existing selections safely
        self.selectNodes(set(), GraphSelectionModel.SelectionFlag.Clear)
        self.selectLinks(set(), GraphSelectionModel.SelectionFlag.Clear)
        self.setCurrentNode(None)
        self.setCurrentLink(None)

        for signal, slot in self._connections:
            signal.disconnect(slot)

        connections = [
            (model.modelReset, self.clearSelection)
        ]
        for signal, slot in connections:
            signal.connect(slot)
        self._connections = connections


        self._model = model
        self.modelChanged.emit()
    
    def selectedNodes(self) -> tuple[NodeName, ...]:
        return tuple(self._selected_nodes)

    def hasNodesSelection(self) -> bool:
        return bool(self._selected_nodes)

    def selectNode(self, node: NodeName, mode: SelectionFlag = SelectionFlag.Select | SelectionFlag.Current):
        """Selects the node using the specified command, and emits selectionChanged().
        By default the 'node' is added to the selection and set as the current node."""
        self.selectNodes({node}, mode=mode)

    def clearSelection(self):
        """Clears all selections and current node/link."""
        self.selectNodes(set(), GraphSelectionModel.SelectionFlag.Clear)
        self.selectLinks(set(), GraphSelectionModel.SelectionFlag.Clear)
        self.setCurrentNode(None)
        self.setCurrentLink(None)
    
    def __applySelection(
        self, 
        items: set[Hashable], 
        mode: SelectionFlag, 
        current_selection: set[Hashable]
    ) -> set[Hashable]:
        """Generic helper to apply Qt selection flags to a set of items."""
        new_selection = set(current_selection)

        if mode & self.SelectionFlag.Clear:
            new_selection.clear()

        if mode & self.SelectionFlag.Select:
            new_selection.update(items)
        elif mode & self.SelectionFlag.Deselect:
            new_selection.difference_update(items)
        elif mode & self.SelectionFlag.Toggle:
            new_selection.symmetric_difference_update(items)
            
        return new_selection

    def selectNodes(self, nodes: Iterable[NodeName], mode: SelectionFlag = SelectionFlag.ClearAndSelect):
        """Selects the nodes using the specified command, and emits selectionChanged()."""
        nodes = set(nodes)
        old_selection = set(self._selected_nodes)
        new_selection = self.__applySelection(nodes, mode, old_selection)

        # Apply the new selection state
        self._selected_nodes = new_selection

        # 3. Handle Current flag if requested and nodes are provided
        if mode & self.SelectionFlag.Current and nodes:
            # Sets are unordered, so we grab an arbitrary element from the input nodes to become current
            new_current = next(iter(nodes))
            if new_current != self._current_node:
                self.setCurrentNode(new_current)

        # 4. Compare changes and emit the signal
        self.emitNodesSelectionChanged(new_selection, old_selection)

    def emitNodesSelectionChanged(self, newSelection: set[NodeName], oldSelection: set[NodeName]):
        """Compares the two selections newSelection and oldSelection and
        emits nodesSelectionChanged() with the deselected and selected items."""
        assert isinstance(newSelection, set), f"newSelection must be a set, got {type(newSelection)}"
        assert isinstance(oldSelection, set), f"oldSelection must be a set, got {type(oldSelection)}"

        selected = newSelection - oldSelection
        deselected = oldSelection - newSelection

        # Only emit if an actual state change occurred
        if selected or deselected:
            self.nodesSelectionChanged.emit(selected, deselected)
            
    def currentNode(self) -> NodeName | None:
        return self._current_node

    def setCurrentNode(self, node: NodeName | None):
        if node == self._current_node:
            return  # No change, do nothing
        previous = self._current_node
        self._current_node = node
        self.currentNodeChanged.emit(node, previous)
    
    def selectedLinks(self) -> tuple[DirectionalLinkId, ...]:
        return tuple(self._selected_links)

    def selectLink(self, link: DirectionalLinkId, mode: SelectionFlag = SelectionFlag.Select | SelectionFlag.Current):
        self.selectLinks({link}, mode=mode)

    def selectLinks(self, links: Iterable[DirectionalLinkId], mode: SelectionFlag = SelectionFlag.ClearAndSelect):
        """Selects the links using the specified command, and emits selectionChanged()."""
        links = set(links)
        old_selection = set(self._selected_links)
        new_selection = self.__applySelection(links, mode, old_selection)

        # Apply the new selection state
        self._selected_links = new_selection

        # 3. Handle Current flag if requested and links are provided
        if mode & self.SelectionFlag.Current and links:
            # Sets are unordered, so we grab an arbitrary element from the input links to become current
            new_current = next(iter(links))
            if new_current != self._current_link:
                self.setCurrentLink(new_current)

        # 4. Compare changes and emit the signal
        self.emitLinksSelectionChanged(new_selection, old_selection)

    def emitLinksSelectionChanged(self, newSelection: set[DirectionalLinkId], oldSelection: set[DirectionalLinkId]):
        """Compares the two selections newSelection and oldSelection and
        emits linksSelectionChanged() with the deselected and selected items."""
        assert isinstance(newSelection, set), f"newSelection must be a set, got {type(newSelection)}"
        assert isinstance(oldSelection, set), f"oldSelection must be a set, got {type(oldSelection)}"

        selected = newSelection - oldSelection
        deselected = oldSelection - newSelection

        # Only emit if an actual state change occurred
        if selected or deselected:
            self.linksSelectionChanged.emit(selected, deselected)

    def currentLink(self) -> DirectionalLinkId | None:
        return self._current_link
    
    def setCurrentLink(self, link: DirectionalLinkId | None):
        if link == self._current_link:
            return  # No change, do nothing
        previous = self._current_link
        self._current_link = link
        self.currentLinkChanged.emit(link, previous)
    