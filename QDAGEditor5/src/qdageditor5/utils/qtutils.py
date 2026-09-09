from qtpy.QtCore import *
from typing import Tuple

def indexToPath(index: QModelIndex) -> Tuple[int, ...]:
    """
    Find the path of a QModelIndex in a tree structure.
    Args:
        index: The QModelIndex to find the path for
    Returns:
        A list of integers representing the path from root to the index.
    """
    if not index.isValid():
        return ()
    
    path_parts = []
    current = index
    
    # Walk up the tree to build the path
    while current.isValid():        
        # Add row
        path_parts.append(current.row())
        
        # Move to parent
        current = current.parent()
    
    # Reverse to show root -> leaf order
    path_parts.reverse()
    
    return tuple(path_parts)

def indexFromPath(model:QAbstractItemModel, path: Tuple[int, ...]) -> QModelIndex:
    """
    Convert a path representation back to a QModelIndex in the given model.
    Args:
        model: The model to search in
        path: A list of integers representing the path from root to the index.
    Returns:
        The QModelIndex corresponding to the path.
    """
    if not path:
        return QModelIndex()

    # Start from the root
    current = QModelIndex()

    for part in path:
        # Find the child corresponding to the current part
        current = model.index(part, 0, current)
        if not current.isValid():
            raise KeyError(f"Path {path} not found in model")

    return current

from typing import List
def normalizeSelection(selection:QItemSelection) -> List[QModelIndex]:
    """
    Normalize a selection to only include top-level selected indexes.
    Args:
        selection: The selection to normalize
    Returns:
        A list of QModelIndex representing the top-level selected indexes.
    """
    selected_indexes = selection.indexes()
    if not selected_indexes:
        return []
    
    # force all to column 0
    _ = map(lambda index: index.siblingAtColumn(0), selected_indexes)

    # remove duplicates
    selected_indexes = list(dict.fromkeys(selected_indexes))

    # filter out descendants
    def ancestors(index: QModelIndex):
        current = index.parent()
        while current.isValid():
            yield current
            current = current.parent()
    
    top_level_indexes = list(filter(lambda index: not any(ancestor in selected_indexes for ancestor in ancestors(index)), selected_indexes))

    return top_level_indexes

from typing import Dict
def group_indexes_by_parent(indexes: List[QModelIndex]) -> Dict[QModelIndex, List[QModelIndex]]:
    """
    Group a list of QModelIndex by their parent index.
    Args:
        indexes: The list of QModelIndex to group
    Returns:
        A dictionary mapping parent QModelIndex to a list of its child QModelIndex.
    """
    grouped = {}
    for index in indexes:
        parent = index.parent()
        if parent not in grouped:
            grouped[parent] = []
        grouped[parent].append(index)
    return grouped