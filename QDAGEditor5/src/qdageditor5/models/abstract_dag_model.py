import warnings
from abc import ABCMeta, abstractmethod
from typing import (
    Any, 
    Hashable, 
    Iterable
)

from qtpy.QtCore import (
    QObject, 
    Qt,
    Signal,
    QPointF
)

import networkx as nx


class _AbstractQObjectMeta(type(QObject), ABCMeta):
    pass

type NodeName = Hashable
type InletName = Hashable
type OutletName = Hashable
type CellIdx = int

type DirectionalLinkId = tuple[NodeName, OutletName, NodeName, InletName]  # (source_node, source_outlet, target_node, target_inlet)
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class AddNodeMessage:
    nodes: tuple[NodeName, ...]

@dataclass(frozen=True, slots=True)
class RemoveNodeMessage:
    nodes: tuple[NodeName, ...]

@dataclass(frozen=True, slots=True)
class ResetModelMessage:
    pass

@dataclass(frozen=True, slots=True)
class AddLinkMessage:
    links: tuple[DirectionalLinkId, ...]

@dataclass(frozen=True, slots=True)
class RemoveLinkMessage:
    links: tuple[DirectionalLinkId, ...]

@dataclass(frozen=True, slots=True)
class ResetLinksMessage:
    pass

@dataclass(frozen=True, slots=True)
class ResetInletsMessage:
    node: NodeName

@dataclass(frozen=True, slots=True)
class ResetOutletsMessage:
    node: NodeName

@dataclass(frozen=True, slots=True)
class InsertCellsMessage:
    node: NodeName
    first: CellIdx
    last: CellIdx

@dataclass(frozen=True, slots=True)
class RemoveCellsMessage:
    node: NodeName
    first: CellIdx
    last: CellIdx

@dataclass(frozen=True, slots=True)
class ResetCellsMessage:
    node: NodeName

type GraphMessage = (
    AddNodeMessage
    | RemoveNodeMessage
    | ResetModelMessage
    | AddLinkMessage
    | RemoveLinkMessage
    | ResetLinksMessage
    | ResetInletsMessage
    | ResetOutletsMessage
    | InsertCellsMessage
    | RemoveCellsMessage
    | ResetCellsMessage
)


class AbstractDAGModel(QObject, metaclass=_AbstractQObjectMeta):
    nodesAboutToBeAdded = Signal(tuple) # list[NodeT]
    nodesAdded = Signal(tuple) # list[NodeT]
    nodesAboutToBeRemoved = Signal(tuple) # list[NodeT]
    nodesRemoved = Signal(tuple) # list[NodeT]
    nodeDataChanged = Signal(tuple) # list[NodeT]
    nodeAboutToMove = Signal(object) # NodeT
    nodeMoved = Signal(object) # NodeT
    
    inletsChanged = Signal(object) # NodeT
    inletDataChanged = Signal(object, tuple, list) # NodeT, tuple[InletT...], roles: list[int]
    outletsChanged = Signal(object) # NodeT

    cellsAboutToBeInserted = Signal(object, int, int) # NodeT, first, last
    cellsInserted = Signal(object, int, int) # # NodeT, first, last
    cellsAboutToBeRemoved = Signal(object, int, int) # NodeT, first, last
    cellsRemoved = Signal(object, int, int) # NodeT, first, last
    cellsDataChanged = Signal(object, int, int) # NodeT, first, last

    linksAboutToBeAdded = Signal(tuple) # list[DirectionalLinkId]
    linksAdded = Signal(tuple) # list[DirectionalLinkId]
    linksAboutToBeRemoved = Signal(tuple) # list[DirectionalLinkId]
    linksRemoved = Signal(tuple) # list[DirectionalLinkId]
    linksAboutToBeReset = Signal()
    linksReset = Signal()
    
    modelAboutToBeReset = Signal()
    modelReset = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        # message queue for batching operations
        self._message_queue: list[GraphMessage] = []

    def _beginResetModel(self) -> None:
        assert len(self._message_queue) == 0, "Message queue should be empty before resetting the model."
        self._message_queue.append(ResetModelMessage())
        self.modelAboutToBeReset.emit()

    def _endResetModel(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, ResetModelMessage), f"Expected ResetModelMessage, got {type(msg)}"
        self.modelReset.emit()

    # == NODES API ==
    @abstractmethod
    def nodes(self) -> Iterable[NodeName]:
        """Return an iterable of all node keys in the model."""
        pass
    
    def has_node(self, node: NodeName) -> bool:
        """Check if a node exists in the model."""
        return node in self.nodes()

    @abstractmethod
    def nodeData(self, node: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return the header data for the given node and role."""
        pass
    
    def nodePosition(self, node: NodeName) -> QPointF:
        """Return the position of the given node as a QPointF."""
        return QPointF(0, 0)
    
    def setNodePosition(self, node: NodeName, position: QPointF|None) -> bool:
        return False

    def _beginAddNodes(self, nodes: Iterable[NodeName]) -> None:
        assert len(self._message_queue) == 0, "Message queue should be empty before inserting cells."
        new_nodes = tuple(nodes)
        self._message_queue.append(AddNodeMessage(new_nodes))
        self.nodesAboutToBeAdded.emit(new_nodes)

    def _endAddNodes(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, AddNodeMessage), f"Expected AddNodeMessage, got {type(msg)}"
        self.nodesAdded.emit(msg.nodes)

    def _beginRemoveNodes(self, nodes: Iterable[NodeName]) -> None:
        assert len(self._message_queue) == 0, "Message queue should be empty before inserting cells."
        nodes_to_remove = tuple(nodes)
        if not nodes_to_remove:
            return

        self._message_queue.append(RemoveNodeMessage(nodes_to_remove))
        self.nodesAboutToBeRemoved.emit(nodes_to_remove)

    def _endRemoveNodes(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, RemoveNodeMessage), f"Expected RemoveNodeMessage, got {type(msg)}"
        self.nodesRemoved.emit(msg.nodes)

    # == CELLS API ==
    @abstractmethod
    def nodeCellCount(self, node: NodeName) -> int:
        """Returns the number of cells for the given node."""
        pass
    
    @abstractmethod
    def nodeCellData(self, node: NodeName, column: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Returns the data for the cell at the given index."""
        pass

    def setNodeCellData(self, node: NodeName, column: CellIdx, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """Sets the data for the cell at the given index. Returns True if
        successful, False otherwise. Default implementation does nothing and 
        returns False. Subclasses should override this method to provide actual
        functionality."""
        return False

    def nodeCellFlags(self, node: NodeName, column: CellIdx) -> Qt.ItemFlags:
        """Returns the item flags for the cell at the given index."""
        return Qt.ItemFlag.NoItemFlags

    def insertCells(self, position: CellIdx, count: int, node: NodeName) -> bool:
        return False
    
    def removeCells(self, first: CellIdx, last: CellIdx, node: NodeName) -> bool:
        return False
    
    def _beginInsertCells(self, node: NodeName, first: CellIdx, last: CellIdx) -> None:
        assert len(self._message_queue) == 0, "Message queue should be empty before inserting cells."
        assert 0 <= first <= last <= self.nodeCellCount(node), f"Invalid cell range: first={first}, last={last}, cellCount={self.nodeCellCount(node)}"

        self._message_queue.append(InsertCellsMessage(node, first, last))
        self.cellsAboutToBeInserted.emit(node, first, last)
    
    def _endInsertCells(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, InsertCellsMessage), f"Expected InsertCellsMessage, got {type(msg)}"
        node, first, last = msg.node, msg.first, msg.last
        self.cellsInserted.emit(node, first, last)

    def _beginRemoveCells(self, node: NodeName, first: CellIdx, last: CellIdx) -> None:
        assert len(self._message_queue) == 0, "Message queue should be empty before removing cells."
        assert 0 <= first <= last < self.nodeCellCount(node), f"Invalid cell range: first={first}, last={last}, cellCount={self.nodeCellCount(node)}"

        self._message_queue.append(RemoveCellsMessage(node, first, last))
        self.cellsAboutToBeRemoved.emit(node, first, last)

    def _endRemoveCells(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, RemoveCellsMessage), f"Expected RemoveCellsMessage, got {type(msg)}"
        node, first, last = msg.node, msg.first, msg.last
        self.cellsRemoved.emit(node, first, last)
    
    # == INLETS API ==
    @abstractmethod
    def inlets(self, node: NodeName) -> Iterable[InletName]:
        pass

    @abstractmethod
    def inletData(self, node: NodeName, inlet: InletName, role:int) -> Any:
        pass

    def setInletData(self, node: NodeName, inlet: InletName, value: Any, role:int) -> bool:
        """Sets the data for the given inlet. Returns True if successful, False otherwise.
        Default implementation does nothing and returns False. Subclasses should override
        this method to provide actual functionality."""
        return False

    def _beginResetInlets(self, node: NodeName) -> None:
        """Begin the process of resetting inlets for a specific node.
        Raises ValueError if the node does not exist in the model."""
    
        if node not in self.nodes():
            raise ValueError(f"Node {node} does not exist in the model.")
        assert len(self._message_queue) == 0, "Message queue should be empty before inserting cells."
        msg = ResetInletsMessage(node)
        self._message_queue.append(msg)

    def _endResetInlets(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, ResetInletsMessage), f"Expected ResetInletsMessage, got {type(msg)}"
        node = msg.node
        self.inletsChanged.emit(node)

    # == OUTLETS API ==
    @abstractmethod
    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        """Return a tuple of all outlet keys for the given node."""
        pass

    @abstractmethod
    def outletData(self, node: NodeName, outlet: OutletName, role:int) -> Any:
        """Return the data for the given outlet and role."""
        pass

    def _beginResetOutlets(self, node: NodeName) -> None:
        """Begin the process of resetting the outlets for a specific node.
        Raises ValueError if the node does not exist in the model."""
        
        if node not in self.nodes():
            raise ValueError(f"Node {node} does not exist in the model.")
        
        assert len(self._message_queue) == 0, "Message queue should be empty before inserting cells."
        msg = ResetOutletsMessage(node)
        self._message_queue.append(msg)

    def _endResetOutlets(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, ResetOutletsMessage), f"Expected ResetOutletsMessage, got {type(msg)}"
        self.outletsChanged.emit(msg.node)

    # == LINKS API ==
    @abstractmethod
    def inLinks(self, target_node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        pass
        
    @abstractmethod
    def outLinks(self, source_node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        pass

    @abstractmethod
    def links(self) -> Iterable[DirectionalLinkId]:
        pass

    @abstractmethod
    def linkSource(self, link: DirectionalLinkId) -> tuple[NodeName,OutletName]:
        pass

    @abstractmethod
    def linkTarget(self, link: DirectionalLinkId) -> tuple[NodeName,InletName]:
        pass

    def _beginAddLinks(self, links: Iterable[DirectionalLinkId]) -> None:
        """Begin the process of adding multiple links at once.
        Raises ValueError if any of the links already exist in the model."""
        assert len(self._message_queue) == 0, "Message queue should be empty before inserting cells."
        new_links = tuple(links)
        for u, out_, v, in_ in new_links:
            if u not in self.nodes():
                raise ValueError(f"Source node {u} does not exist in the model.")
            if out_ not in self.outlets(u):
                raise ValueError(f"Outlet {out_} does not exist for source node {u}.")
            if v not in self.nodes():
                raise ValueError(f"Target node {v} does not exist in the model.")
            if in_ not in self.inlets(v):
                raise ValueError(f"Inlet {in_} does not exist for target node {v}.")

        msg = AddLinkMessage(new_links)
        self._message_queue.append(msg)
        self.linksAboutToBeAdded.emit(new_links)

    def _endAddLinks(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, AddLinkMessage), f"Expected AddLinkMessage, got {type(msg)}" 
        self.linksAdded.emit(msg.links)

    def _beginRemoveLinks(self, links: Iterable[DirectionalLinkId]) -> None:
        """Begin the process of removing multiple links at once.
        raises ValueError if any of the links do not exist in the model."""
        assert len(self._message_queue) == 0, "Message queue should be empty before removing links."
        links_to_remove = tuple(links)
        for link in links_to_remove:
            assert isinstance(link, tuple)
            assert len(link) == 4

        for link in links_to_remove:
            if link not in set(self.links()): #todo: what about performance? do we really need this here in the abstract class?
                raise ValueError(f"Link {link} does not exist in the model.")

        msg = RemoveLinkMessage(links_to_remove)
        self._message_queue.append(msg)
        self.linksAboutToBeRemoved.emit(links_to_remove)

    def _endRemoveLinks(self) -> None:
        msg = self._message_queue.pop()
        assert isinstance(msg, RemoveLinkMessage), f"Expected RemoveLinkMessage, got {type(msg)}"
        self.linksRemoved.emit(msg.links)

    # == CUSTOMIZATION API ==
    def canCompleteLink(self, source_node: NodeName, outlet: OutletName, target_node: NodeName, inlet: InletName) -> bool:
        return True

    # == UTILITY METHODS ==
    def topological_sort(self, root: NodeName|None=None) -> list[NodeName]:
        """
        Perform a topological sort of the nodes in the graph model starting from the root node.
        """
        # TODO: Move this to a utility function in qdageditor4, or add it to the AbstractDAGModel class itself.
        
        G = nx.DiGraph()
        for node in self.nodes():
            G.add_node(node)
            for inlet in self.inlets(node):
                for link in self.inLinks(node, inlet):
                    source_node, source_outlet = self.linkSource(link)
                    if source_node:
                        G.add_edge(source_node, node)

        if root is None:
            # Sort whole graph
            return list(nx.topological_sort(G))
        else:
            # Sort ancestors only
            ancestors = nx.ancestors(G, root)
            subgraph = G.subgraph(ancestors | {root})
            return list(nx.topological_sort(subgraph))

    def removeLinks(self, links:Iterable[DirectionalLinkId])->bool:
        return False