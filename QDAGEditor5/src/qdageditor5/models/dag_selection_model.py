import warnings
from typing import (
    Any, 
    Hashable, 
    Iterable, 
    Literal, 
    Tuple
)

from qtpy.QtCore import (
    QObject, 
    Qt,
    Signal
)

from qdageditor5.models.standard_dag_model import NodeName
from qdageditor5.core.item_data_roles import (
    ShapeDataRole, 
    ShapeData
)


class DagSelectionModel(QObject):
    currentNodeChanged = Signal(...)  # Emits the current node key or None
    modelChanged = Signal(...)  # Emits when the model is changed
    selectionChanged = Signal(...)  # Emits when the selection changes

    # Public Functions
    def model(self) -> Any:
        ...

    def setModel(self, model: Any) -> None:
        ...

    def currentNode(self) -> NodeName|None:
        ...

    def selectedNodes(self) -> set[NodeName]:
        """
        Returns the set of currently selected node keys.
        """
        return self._selection
    
    def selectedLinks(self) -> set[tuple[NodeName, NodeName]]:
        """
        Returns the set of currently selected links as tuples of (source_node_key, target_node_key).
        """
        return self._selected_links
    
    def hasSelection(self) -> bool:
        """
        Returns True if there is any selection, False otherwise.
        """
        return bool(self._selection or self._selected_links)
    
    def isSelected(self, node_key: NodeName) -> bool:
        """
        Checks if the given node key is currently selected.
        """
        return node_key in self._selection
    
    # Public Slots
    def clear(self) -> None:
        ...

    def selectNode(self, node_key: NodeName) -> None:
        ...

    def setCurrentNode(self, node_key: NodeName|None) -> None:
        ...

    # Protected Functions
    def _emitSelectionChanged(self) -> None:
        ...