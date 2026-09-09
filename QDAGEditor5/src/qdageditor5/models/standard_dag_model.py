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
    Signal,
    QPointF
)

from qdageditor5.core.item_data_roles import (
    ShapeDataRole, 
    ShapeData
)

from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel,
    NodeName,
    InletName,
    OutletName,
    CellIdx,
    DirectionalLinkId
)

from dataclasses import dataclass

@dataclass
class _InletData:
    label: str

@dataclass
class _OutletData:
    label: str

@dataclass
class _NodeData:
    header: Any
    inlets: dict[InletName, _InletData]
    outlets: dict[OutletName, _OutletData]  # Placeholder for outlet-specific data; can be extended as needed
    cells: list[Any]  # List of cell data for each column
    pos: tuple[float, float]|None = (0.0, 0.0)  # Default position; can be updated as needed

@dataclass
class _LinkData:
    # Placeholder for link-specific data; can be extended as needed
    pass

class StandardDAGModel(AbstractDAGModel):
    """A standard implementation of a Directed Acyclic Graph (DAG) model."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        # nodes
        self._nodes: dict[NodeName, _NodeData] = dict()
  
        # links
        # v<-in<-u<-out<-v
        self._predecessors: dict[NodeName, dict[InletName,  dict[NodeName, dict[OutletName, _LinkData]]]] = dict()
        # u->out->v->in->u
        self._successors:   dict[NodeName, dict[OutletName, dict[NodeName, dict[InletName, _LinkData]]]]  = dict()

    # == NODES API ==
    def nodes(self) -> tuple[NodeName, ...]:
        return tuple(self._nodes)

    def nodePosition(self, node_key: NodeName)-> QPointF|None:
        if node_key in self._nodes:
            node_data = self._nodes[node_key]
            x, y = node_data.pos
            return QPointF(x, y)
        else:
            return None
        
    def setNodePosition(self, node: NodeName, position: QPointF|None) -> bool:
        if node not in self._nodes:
            return False
        self.nodeAboutToMove.emit(node)
        self._nodes[node].pos = position.x(), position.y()
        self.nodeMoved.emit(node)
        return True

    def addNodes(self, count:int) -> tuple[NodeName, ...]:
        """Add multiple nodes at once."""
        from qdageditor4.utils.unique import make_unique_id

        nodes = [make_unique_id() for _ in range(count)]
        new_nodes = [node for node in nodes if node not in self._nodes]
        if not new_nodes:
            return tuple()

        self._beginAddNodes(new_nodes)
        for node in new_nodes:
            self._nodes[node] = _NodeData(header=None, inlets={}, outlets={}, cells=[])

        self._endAddNodes()
        return tuple(new_nodes)

    def removeNodes(self, nodes: Iterable[NodeName]) -> bool:
        nodes_to_remove = tuple(node for node in nodes if node in self._nodes)
        if not nodes_to_remove:
            return False

        self._beginRemoveNodes(nodes_to_remove)

        # Remove associated links
        associated_links_to_remove = set()
        for node in nodes_to_remove:
            for inlet in self.inlets(node):
                for link in self.inLinks(node, inlet):
                    associated_links_to_remove.add(link)
            for outlet in self.outlets(node):
                for link in self.outLinks(node, outlet):
                    associated_links_to_remove.add(link)

        for link in associated_links_to_remove:
            self.__unregister_link(*link)

        for node in nodes_to_remove:
            del self._nodes[node]

        self._endRemoveNodes()
        return True

    def nodeData(self, node: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return str(node)

    def setNodeHeaderData(self, node: NodeName, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if node not in self._nodes:
            return False
        
        return False

    # == CELLS API ==
    def nodeCellCount(self, node: NodeName) -> int:
        """Returns the number of cells for the given node."""
        if node_data := self._nodes.get(node):
            return len(node_data.cells)
        else:
            return 0
    
    def nodeCellData(self, node: NodeName, column: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Returns the data for the cell at the given index."""
        if node not in self._nodes:
            return None
        
        if column < 0 or column >= len(self._nodes[node].cells):
            return None
        
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._nodes[node].cells[column]

    def nodeCellFlags(self, node: NodeName, column: CellIdx) -> Qt.ItemFlags:
        """Returns the item flags for the cell at the given index."""
        if node not in self._nodes:
            return Qt.ItemFlag.NoItemFlags
        
        if column < 0 or column >= self.nodeCellCount(node):
            return Qt.ItemFlag.NoItemFlags
        
        return Qt.ItemFlag.ItemIsEditable

    def setNodeCellData(self, node: NodeName, column: CellIdx, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """Sets the data for the cell at the given index."""

        if node not in self._nodes:
            return False  # BUG 7 fixed: was returning None
        
        if column < 0 or column >= len(self._nodes[node].cells):
            return False  # BUG 7 fixed: was returning None
        
        try:
            self._nodes[node].cells[column] = value
            self.cellsDataChanged.emit(node, column, column)
            return True
        except IndexError:
            warnings.warn(f"Attempted to set cell data for node {node} at invalid column {column}.")
            return False
    
    def insertCells(self, position: CellIdx, count: int, node: NodeName) -> bool:
        self._beginInsertCells(node, position, position + count - 1)
        self._nodes[node].cells[position:position] = [None] * count  # Insert None or a default value
        self._endInsertCells()
        return True
    
    def removeCells(self, first: CellIdx, last: CellIdx, node: NodeName) -> bool:
        self._beginRemoveCells(node, first, last)
        del self._nodes[node].cells[first:last + 1]
        self._endRemoveCells()
        return True
    
    # == INLETS API ==
    def inlets(self, node: NodeName) -> tuple[InletName]:
        if node_data := self._nodes.get(node):
            return tuple(node_data.inlets.keys())
        return tuple()

    def inletData(self, node: NodeName, inlet: InletName, role:int) -> Any:
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return str(inlet)
        if role == Qt.ItemDataRole.ForegroundRole:
            return None
        if role == ShapeDataRole:
            return ShapeData.Circle
        return None

    def setInlets(self, node: NodeName, inlets: Iterable[InletName]) -> bool:
        """Set the inlets for a specific node. This will remove any existing inlets not in the new list and add new ones.
        note: you must call beginResetInlets and endResetInlets, while changing the underlying data structure."""
        assert node in self._nodes, f"Node {node} does not exist in the model."
        
        self._beginResetInlets(node)
        # remove links
        for inlet in self.inlets(node):
            if inlet not in inlets:
                for link in self.inLinks(node, inlet):
                    u, out_, v, in_ = link
                    self.__unregister_link(u, out_, v, in_)

        # update inlets
        self._nodes[node].inlets = {inlet: _InletData(label=str(inlet)) for inlet in inlets}
        self._endResetInlets()
        return True

    # == OUTLETS API ==
    def outlets(self, node: NodeName) -> tuple[OutletName, ...]:
        if node_data := self._nodes.get(node):
            return tuple(node_data.outlets.keys())
        return tuple()

    def outletData(self, node: NodeName, outlet: OutletName, role:int) -> Any:
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return str(outlet)
        if role == Qt.ItemDataRole.ForegroundRole:
            return None
        if role == ShapeDataRole:
            return ShapeData.Circle
        return None

    def setOutlets(self, node: NodeName, outlets: Iterable[OutletName]) -> bool:
        assert node in self._nodes, f"Node {node} does not exist in the model."

        self._beginResetOutlets(node)
        # remove links
        for outlet in self.outlets(node):
            if outlet not in outlets:
                for link in self.outLinks(node, outlet):
                    u, out_, v, in_ = link
                    self.__unregister_link(u, out_, v, in_)

        # update outlets
        self._nodes[node].outlets = {outlet: _OutletData(label=str(outlet)) for outlet in outlets}
        self._endResetOutlets()
        return True

    # == LINKS API ==
    def inLinks(self, target_node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        assert target_node in self._nodes, f"Target node {target_node} does not exist in the model."
        assert inlet in self._nodes[target_node].inlets, f"Inlet '{inlet}' does not exist for target node {target_node}."

        for source_node in self._predecessors.get(target_node, {}).get(inlet, {}).keys():
            for outlet in self._predecessors[target_node][inlet][source_node].keys():
                yield source_node, outlet, target_node, inlet
        
    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        assert outlet == 'out', f"Outlet must be 'out', got '{outlet}' instead."
        assert source_node in self._nodes, f"Source node {source_node} does not exist in the model."

        for target_node in self._successors.get(source_node, {}).get(outlet, {}).keys():
            for inlet in self._successors[source_node][outlet][target_node].keys():
                yield source_node, outlet, target_node, inlet
        
    def links(self) -> tuple[DirectionalLinkId]:
        existing_links = []
        for source_node in self._successors:
            for outlet in self._successors[source_node]:
                for target_node in self._successors[source_node][outlet]:
                    for inlet in self._successors[source_node][outlet][target_node]:
                        existing_links.append((source_node, outlet, target_node, inlet))
        return tuple(existing_links)

    def linkSource(self, link: DirectionalLinkId) -> tuple[NodeName|OutletName]|None:
        u, out_, v, in_ = link
        if u in self._successors and out_ in self._successors[u] and v in self._successors[u][out_] and in_ in self._successors[u][out_][v]:
            return u, out_
        return None
    
    def linkTarget(self, link: DirectionalLinkId) -> tuple[NodeName|InletName]|None:
        u, out_, v, in_ = link
        if v in self._predecessors and in_ in self._predecessors[v] and u in self._predecessors[v][in_] and out_ in self._predecessors[v][in_][u]:
            return v, in_
        return None

    def __register_link(self, u: NodeName, out_: OutletName, v: NodeName, in_: InletName) -> None:

        link_data = _LinkData()
        if u not in self._successors:
            self._successors[u] = {}
        if out_ not in self._successors[u]:
            self._successors[u][out_] = {}
        if v not in self._successors[u][out_]:
            self._successors[u][out_][v] = {}
        if in_ not in self._successors[u][out_][v]:
            self._successors[u][out_][v][in_] = {}
        self._successors[u][out_][v][in_] = link_data

        if v not in self._predecessors:
            self._predecessors[v] = {}
        if in_ not in self._predecessors[v]:
            self._predecessors[v][in_] = {}
        if u not in self._predecessors[v][in_]:
            self._predecessors[v][in_][u] = {}
        if out_ not in self._predecessors[v][in_][u]:
            self._predecessors[v][in_][u][out_] = {}
        self._predecessors[v][in_][u][out_] = link_data

    def addLinks(self, links: Iterable[DirectionalLinkId]) -> bool:
        """Insert multiple links at once, returning the number of successfully inserted links."""
        new_links = set(links)

        if not new_links:
            warnings.warn("No new links to add. All provided links already exist in the model.")
            return False

        self._beginAddLinks(new_links)
        for u, out_, v, in_ in new_links:
            self.__register_link(u, out_, v, in_)
        self._endAddLinks()

        return True

    def __unregister_link(self, u: NodeName, out_: OutletName, v: NodeName, in_: InletName) -> None:
        """Helper method to remove a link from the internal data structures without emitting signals."""

        del self._successors[u][out_][v][in_]
        if not self._successors[u][out_][v]:  # If no more inlets for this target node, remove the target node entry
            del self._successors[u][out_][v]
        if not self._successors[u][out_]:  # If no more inlets for this target node, remove the target node entry
            del self._successors[u][out_]
        if not self._successors[u]:  # If no more target nodes for this source node, remove the source node entry
            del self._successors[u]

        del self._predecessors[v][in_][u][out_]
        if not self._predecessors[v][in_][u]:  # If no more outlets for this source node, remove the source node entry
            del self._predecessors[v][in_][u]
        if not self._predecessors[v][in_]:  # If no more source nodes for this inlet, remove the inlet entry
            del self._predecessors[v][in_]
        if not self._predecessors[v]:  # If no more inlets for this target node, remove the target node entry
            del self._predecessors[v]

    def removeLinks(self, links: Iterable[DirectionalLinkId]) -> bool:
        links_to_remove = tuple(links)

        self._beginRemoveLinks(links_to_remove)

        for u, out_, v, in_ in links_to_remove:
            self.__unregister_link(u, out_, v, in_)

        self._endRemoveLinks()
        return True

    # == CUSTOMIZE BEHAVIOUR ==
    def canCompleteLink(self, source_node: NodeName, outlet: OutletName, target_node: NodeName, inlet: InletName) -> bool:
        if source_node not in self._nodes or target_node not in self._nodes:
            return False
        if source_node == target_node:
            return False

        visited = set()
        def dfs(current):
            if current == source_node:
                return True
            visited.add(current)
            for succ in self._successors.get(current, {}):
                if succ not in visited:
                    if dfs(succ):
                        return True
            return False

        if dfs(target_node):
            warnings.warn(f"Link from {source_node} to {target_node} creates a cycle.")
            return False

        return True
