from enum import IntFlag
from typing import Hashable, Iterable

from qtpy.QtCore import QObject, Signal

from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel,
    NodeName,
    DirectionalLinkId,
)


class GraphSelectionModel(QObject):
    """Track selected items and an explicitly chosen current node/link.

    Current is independent of selection, like QItemSelectionModel.currentIndex().
    The view chooses it from mouse gestures; bulk selection never chooses an
    arbitrary item from an unordered collection.

    Our Current flag sets that item; Qt's Current flag instead refers to its
    interactive selection layer.
    """
    currentNodeChanged = Signal(object, object) # current, previous
    nodesSelectionChanged = Signal(set, set) # selected, deselected
    currentLinkChanged = Signal(object, object) # current, previous
    linksSelectionChanged = Signal(set, set) # selected, deselected
    modelChanged = Signal()

    class SelectionFlag(IntFlag):
        Clear = 0x01
        Select = 0x02
        Deselect = 0x04
        Toggle = 0x08
        Current = 0x10  # Set the current item for a single-item command.
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
        if self._model is model:
            return

        for signal, slot in self._connections:
            signal.disconnect(slot)

        self._model = model
        self.clear()
        self._connections = [
            (model.modelAboutToBeReset, self.clear),
            (model.modelReset, self.clear),
            (model.nodesAboutToBeRemoved, self._on_nodes_removed),
            (model.nodesRemoved, self._prune_links),
            (model.linksAboutToBeRemoved, self._on_links_removed),
            (model.linksReset, self._prune_links),
            (model.inletsChanged, self._prune_links),
            (model.outletsChanged, self._prune_links),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)
        self.modelChanged.emit()

    def model(self) -> AbstractDAGModel:
        return self._model

    def _on_nodes_removed(self, nodes):
        removed = set(nodes)
        # Some models remove incident links without separate link notifications.
        links = set(self._selected_links)
        if self._current_link is not None:
            links.add(self._current_link)
        self._on_links_removed({
            link for link in links if link[0] in removed or link[2] in removed
        })
        if self._current_node in removed:
            self.setCurrentNode(None)
        if removed & self._selected_nodes:
            self.selectNodes(removed, self.SelectionFlag.Deselect)

    def _on_links_removed(self, links):
        removed = set(links)
        if self._current_link in removed:
            self.setCurrentLink(None)
        if removed & self._selected_links:
            self.selectLinks(removed, self.SelectionFlag.Deselect)

    def _prune_links(self, *args):
        if not self._selected_links and self._current_link is None:
            return
        tracked = set(self._selected_links)
        if self._current_link is not None:
            tracked.add(self._current_link)
        self._on_links_removed(tracked - set(self._model.links()))

    def selectedNodes(self) -> tuple[NodeName, ...]:
        return tuple(self._selected_nodes)

    def currentNode(self) -> NodeName | None:
        return self._current_node

    def hasNodesSelection(self) -> bool:
        return bool(self._selected_nodes)

    def selectNode(self, node: NodeName, mode: SelectionFlag = SelectionFlag.Select | SelectionFlag.Current):
        """Selects the node using the specified command, and emits selectionChanged().
        By default the 'node' is added to the selection and set as the current node."""
        self.selectNodes({node}, mode=mode)

    def clearSelection(self) -> None:
        """Clear selected nodes and links, preserving the current items."""
        old_nodes, old_links = self._selected_nodes, self._selected_links
        self._selected_nodes, self._selected_links = set(), set()
        self.emitNodesSelectionChanged(set(), old_nodes)
        self.emitLinksSelectionChanged(set(), old_links)

    def clear(self) -> None:
        """Clear all selections and current items before notifying observers."""
        old_nodes, old_links = self._selected_nodes, self._selected_links
        old_node, old_link = self._current_node, self._current_link
        self._selected_nodes, self._selected_links = set(), set()
        self._current_node, self._current_link = None, None
        if old_node is not None:
            self.currentNodeChanged.emit(None, old_node)
        if old_link is not None:
            self.currentLinkChanged.emit(None, old_link)
        self.emitNodesSelectionChanged(set(), old_nodes)
        self.emitLinksSelectionChanged(set(), old_links)

    def __applySelection(
        self,
        items: set[Hashable],
        mode: SelectionFlag,
        current_selection: set[Hashable]
    ) -> set[Hashable]:
        """Apply selection flags to a copy of the selected items."""
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

    def selectNodes(self, nodes: Iterable[NodeName], mode: SelectionFlag = SelectionFlag.ClearAndSelect) -> None:
        """Selects the nodes using the specified command, and emits selectionChanged()."""
        nodes = set(nodes)
        old_selection = set(self._selected_nodes)
        new_selection = self.__applySelection(nodes, mode, old_selection)
        valid_nodes = set(self._model.nodes())
        new_selection.intersection_update(valid_nodes)

        # Apply the new selection state
        self._selected_nodes = new_selection

        if mode & self.SelectionFlag.Current and len(nodes) == 1:
            node = next(iter(nodes))
            self.setCurrentNode(node if node in valid_nodes else None)

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

    def setCurrentNode(self, node: NodeName | None) -> None:
        """Set focus without changing selection; the node must exist."""
        if node is not None and node not in self._model.nodes():
            raise ValueError(f"Node {node!r} does not exist in the model")
        if node == self._current_node:
            return  # No change, do nothing
        previous = self._current_node
        self._current_node = node
        self.currentNodeChanged.emit(node, previous)

    def selectedLinks(self) -> tuple[DirectionalLinkId, ...]:
        return tuple(self._selected_links)

    def selectLink(self, link: DirectionalLinkId, mode: SelectionFlag = SelectionFlag.Select | SelectionFlag.Current):
        self.selectLinks({link}, mode=mode)

    def selectLinks(self, links: Iterable[DirectionalLinkId], mode: SelectionFlag = SelectionFlag.ClearAndSelect) -> None:
        """Selects the links using the specified command, and emits selectionChanged()."""
        links = set(links)
        old_selection = set(self._selected_links)
        new_selection = self.__applySelection(links, mode, old_selection)
        valid_links = set(self._model.links())
        new_selection.intersection_update(valid_links)

        # Apply the new selection state
        self._selected_links = new_selection

        if mode & self.SelectionFlag.Current and len(links) == 1:
            link = next(iter(links))
            self.setCurrentLink(link if link in valid_links else None)

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

    def setCurrentLink(self, link: DirectionalLinkId | None) -> None:
        """Set focus without changing selection; the link must exist."""
        if link is not None and link not in self._model.links():
            raise ValueError(f"Link {link!r} does not exist in the model")
        if link == self._current_link:
            return  # No change, do nothing
        previous = self._current_link
        self._current_link = link
        self.currentLinkChanged.emit(link, previous)

