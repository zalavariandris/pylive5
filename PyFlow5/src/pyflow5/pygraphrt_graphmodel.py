from collections import defaultdict
from logging import warning
from textwrap import dedent
from typing import Iterable, override, Any
import warnings

from pytools import UniqueNameGenerator

from qtpy.QtCore import (
    QObject, 
    Qt,
    Signal, Slot,
    QPointF
)
from qtpy.QtGui import QColor

from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel,
    AddNodeMessage,
    RemoveNodeMessage,
    CellIdx, 
    DirectionalLinkId, 
    InletName, 
    NodeName, 
    OutletName
)

import pygraphrt as rt

from qdageditor5.core.item_data_roles import (
    NodeDataRole
)

class PyGraphRTGraphModel(AbstractDAGModel):
    ExecutionRole = Qt.ItemDataRole.UserRole+1
    ResolutionRole = Qt.ItemDataRole.UserRole+2

    def __init__(self, 
        graph: rt.GraphDefinitionRT, 
        registry: rt.ModuleRegistry,
        invalidator: rt.GraphInvalidator,
        executor: rt.GraphExecutorRT
    ):
        super().__init__()
        self._graph: rt.GraphDefinitionRT = graph
        self._registry: rt.ModuleRegistry = registry
        self._invalidator: rt.GraphInvalidator = invalidator
        self._executor: rt.GraphExecutorRT = executor
        self._positions: dict[NodeName, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))

        self._executions: dict[NodeName, rt.NodeExecution] = {}

        # Adapters observe this model, including changes made directly to the RT.
        graph.nodes_added.connect(self._on_rt_nodes_added)
        graph.nodes_removed.connect(self._on_rt_nodes_removed)
        graph.nodes_changed.connect(self._on_rt_nodes_changed)
        for signal in (
            registry.modules_added,
            registry.modules_removed,
            registry.operators_added,
            registry.operators_removed,
            registry.operators_changed,
        ):
            signal.connect(self._on_registry_changed)

        @self._invalidator.nodes_invalidated.connect
        def on_nodes_invalidated(nodes: list[rt.NodeRef]):
            print("Nodes invalidated: ", [node_ref.get_name() for node_ref in nodes])
            for node_ref in nodes:
                if node_ref.get_name() in self._executions:
                    del self._executions[node_ref.get_name()]

            self.nodesDataChanged.emit(
                tuple([self.mapFromSource(node_ref) for node_ref in nodes]), 
                tuple([self.ExecutionRole])
            ) # list[NodeT], roles: list[int]

            for node_ref in nodes:
                self._executor.execute(node_ref)

        @self._executor.executed.connect
        def on_executed(results: dict[rt.NodeRef, rt.NodeExecution]):
            print("Nodes executed: ", [node_ref.get_name() for node_ref in results.keys()])
            changed_nodenames: list[NodeName] = []
            for node_ref, execution in results.items():
                if node_name := self.mapFromSource(node_ref):
                    self._executions[node_name] = execution
                    changed_nodenames.append(node_name)

            self.nodesDataChanged.emit(
                tuple(changed_nodenames), 
                tuple([self.ExecutionRole])
            ) # list[NodeT], roles: list[int]

    def _on_rt_nodes_added(self, nodes: list[rt.NodeRef]) -> None:
        if any(isinstance(msg, AddNodeMessage) for msg in self._message_queue):
            return  # addNode already owns the source notification pair.
        names = tuple(node.get_name() for node in nodes)
        self.nodesAboutToBeAdded.emit(names)
        self.nodesAdded.emit(names)

    def _on_rt_nodes_removed(self, nodes: list[rt.NodeRef]) -> None:
        names = tuple(node.get_name() for node in nodes)
        for name in names:
            self._positions.pop(name, None)
            self._executions.pop(name, None)
        if any(isinstance(msg, RemoveNodeMessage) for msg in self._message_queue):
            return  # removeNodes already owns the source notification pair.
        self.nodesAboutToBeRemoved.emit(names)
        self.nodesRemoved.emit(names)

    def _on_rt_nodes_changed(self, nodes: list[rt.NodeRef]) -> None:
        names = tuple(node.get_name() for node in nodes)
        for name in names:
            # The base tree adapter compares inlet identities and only changes
            # rows when necessary; unchanged rows still receive dataChanged.
            self.inletsChanged.emit(name)
        self.nodesDataChanged.emit(names, ())

    def _on_registry_changed(self, *_: object) -> None:
        self._on_rt_nodes_changed(self._graph.nodes())

    def setRT(self, graph: rt.GraphDefinitionRT, positions=None):
        raise NotImplementedError("setRT method is not implemented yet.")

    def reset_graph_from_scratch(self) -> None:
        """Recover presentation state from the current runtime without changing it.

        Call after a failed mutation has unwound, not from a mutation signal handler.
        """
        node_names = {node.get_name() for node in self._graph.nodes()}
        positions = {name: position for name, position in self._positions.items()
                     if name in node_names}
        # Recovery deliberately abandons notifications left open by a failed edit.
        self._message_queue.clear()
        self._beginResetModel()
        self._positions = defaultdict(lambda: (0.0, 0.0), positions)
        self._endResetModel()

    # = Mapping Source =
    def mapToSource(self, node_name:NodeName)->rt.NodeRef|None:
        # todo: consider caching node references by name for faster lookup
        # find noderef by the name
        for node_ref in self._graph.nodes():
            if node_ref.get_name() == node_name:
                return node_ref
        return None

    def mapFromSource(self, node_ref: rt.NodeRef) -> NodeName | None:
        return node_ref.get_name() if node_ref is not None else None

    # OVERRIDES 
    # - READ
    @override
    def nodes(self)->Iterable[NodeName]:
        return [
            self.mapFromSource(node_ref)
            for node_ref in self._graph.nodes()
        ]

    @override
    def nodeData(self, node_name: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node_ref = self.mapToSource(node_name)
        if node_ref is None:
            return None
        
        match role:
            case Qt.ItemDataRole.DisplayRole:
                if op:=node_ref.get_operator():
                    return op.get_name()
                else:
                    return "-NoOp-"

            case Qt.ItemDataRole.BackgroundRole:
                if op:=node_ref.get_operator():
                    return None
                else:
                    return QColor(200,20,20)

            case NodeDataRole.LeadingRole:
                return f"{node_ref.get_name()}"

            case NodeDataRole.TrailingRole:
                return dedent("""\
                    computed
                    cached""")

            case self.ExecutionRole:
                if node_name in self._executions:
                    match self._executions.get(node_name):
                        case rt.ExecutionBlocked():
                            return None
                        case rt.ExecutionSuccess() as success:
                            return success.result
                        case rt.ExecutionFailure() as failure:
                            return failure.reason
                        case _:
                            return None
                else:
                    warnings.warn(f"No execution result for node: '{node_name}'")
                    return None
            
            case _:
                return None

    @override
    def inlets(self, node:NodeName)->Iterable[InletName]:
        if node_ref := self.mapToSource(node):
            inlets, _ = self.__node_inlets(node_ref)
            yield from inlets

    def __node_inlets(self, node_ref: rt.NodeRef):
        """Return declared inlets and actual bindings, including invalid extras."""
        op = node_ref.get_operator()
        parameters = list(op.get_parameters()) if op is not None else []
        args, kwargs = node_ref.get_inputs()
        bindings = []
        for i, value in enumerate(args):
            inlet = parameters[i] if i < len(parameters) else str(i + 1)
            # Arbitrary keyword names can also be numeric; keep extras distinct.
            if i >= len(parameters):
                while inlet in kwargs or inlet in parameters:
                    inlet = "#" + inlet
            bindings.append((inlet, value))
        bindings.extend(kwargs.items())
        inlets = list(dict.fromkeys([*parameters, *(name for name, _ in bindings)]))
        return inlets, bindings

    @override
    def outlets(self, node:NodeName)->Iterable[OutletName]:
        return ['out']

    @override
    def inletData(self, node: NodeName, inlet: InletName, role:int) -> Any:
        return None

    @override
    def outletData(self, node:NodeName, outlet:OutletName, role:int) -> Any:
        return None

    # cells
    @override
    def nodeCellCount(self, node_name: NodeName) -> int:
        return 0

    @override
    def nodeCellData(self, node_name: NodeName, cell: CellIdx, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return None

    @override
    def nodePosition(self, node_name:NodeName)->QPointF:
        if node_name in self._positions:
            x, y = self._positions[node_name]
            return QPointF(x, y)
        else:
            return QPointF(0.0, 0.0)

    @override
    def inLinks(self, node_name:NodeName, inlet_name:InletName)->Iterable[DirectionalLinkId]:
        if node_ref := self.mapToSource(node_name):
            for link in self.__node_input_links(node_ref):
                if link[3] == inlet_name:
                    yield link

    @override
    def outLinks(self, node:NodeName, outlet:OutletName)->Iterable[DirectionalLinkId]:
        # todo: fix performance here
        for link in self.links():
            source, outlet, target, inlet = link
            if source == node and outlet == outlet:
                yield link
        return []

    @override
    def links(self)->Iterable[DirectionalLinkId]:
        for node_ref in self._graph.nodes():
            yield from self.__node_input_links(node_ref)

    @override
    def linkSource(self, link:DirectionalLinkId) -> tuple[NodeName|OutletName]|None:
        source, outlet, target, inlet = link
        return source, outlet

    @override
    def linkTarget(self, link:DirectionalLinkId) -> tuple[NodeName|InletName]|None:
        source, outlet, target, inlet = link
        return target, inlet

    def __node_input_links(self, node_ref: rt.NodeRef)->Iterable[DirectionalLinkId]:
        _, bindings = self.__node_inlets(node_ref)
        for inlet, value in bindings:
            if isinstance(value, rt.NodeRef):
                yield value.get_name(), 'out', node_ref.get_name(), inlet

    # - WRITES
    @override
    def setNodePosition(self, node_name:NodeName, position:QPointF|None):
        if position:
            self._positions[node_name] = (position.x(), position.y())
        else:
            self._positions.pop(node_name, None)

    # @override
    # def setNodeData(self, node: NodeName, role: int, value: Any) -> bool:
    #     node_ref = self.mapToSource(node)
    #     if node_ref is None:
    #         return False
    #     match role:
    #         case self.ResultsRole:
    #             self._results[node_ref] = value
    #             self.nodeDataChanged.emit((node,), tuple([role]))
    #             return True
    #         case _:
    #             return False

    # - MUTATIONS
    @override
    def removeLinks(self, links:Iterable[DirectionalLinkId])->bool:
        self._beginRemoveLinks(links)
        for link in list(links):
            source, outlet, target, inlet = link
            target_rt:rt.NodeRef = self.mapToSource(target)
            args, kwargs = target_rt.get_inputs()
            op = target_rt.get_operator()
            inlets = op.get_parameters().keys()
            if inlet not in inlets:
                continue

            inlet_idx = list(inlets).index(inlet)
            if inlet_idx < len(args):
                new_args = [
                    arg 
                    for arg in args 
                    if not arg.get_name() == source
                ]
                target_rt.set_inputs(*new_args, **kwargs)

            elif inlet in kwargs:
                new_kwargs = {
                    k: v 
                    for k, v in kwargs.items() 
                    if not (k == inlet and isinstance(v, rt.NodeRef) and v.get_name() == source)
                }
                target_rt.set_inputs(*args, **new_kwargs)

        self._endRemoveLinks() # todo: check if QAbstractItemModel return values for these kind of methods
        return True

    def removeNodes(self, nodes:Iterable[NodeName]):
        self._beginRemoveNodes(nodes)
        for node_name in list(nodes):
            node_ref = self.mapToSource(node_name)
            assert node_ref is not None, f"Node '{node_name}' not found"

            self._graph._delete_node(node_ref)
            self._positions.pop(node_name, None)
        self._endRemoveNodes()

    def addLink(self, source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName)->None:
        self._beginAddLinks([(source, outlet, target, inlet)])
        target_ref = self.mapToSource(target)
        source_ref = self.mapToSource(source)
        assert target_ref is not None, f"Target node '{target}' not found"
        assert source_ref is not None, f"Source node '{source}' not found"
        args, kwargs = target_ref.get_inputs()
        op_ref = target_ref.get_operator()

        # if there are already positional arguments for this inlet, replace that otherwise add it to keyword arguments
        inlets = [name for name in op_ref.get_parameters().keys()]
        if inlet not in inlets:
            print(f"Inlet '{inlet}' not found in operator parameters")
            return
        inlet_idx = inlets.index(inlet)

        new_args = list(args)
        new_kwargs = dict(kwargs)
        if inlet_idx < len(args):
            new_args[inlet_idx] = source_ref
        else:
            new_kwargs[inlet] = source_ref

        target_ref.set_inputs(*new_args, **new_kwargs)
        print(f"Updated inputs for target node '{target}': args={new_args}, kwargs={new_kwargs}")
        self._endAddLinks()

    def addNode(self, operator:rt.AbstractOperator, position:QPointF|None=None)->bool:
        """
        position: QPointF|None, in scene coordinates"""
        assert isinstance(operator, rt.AbstractOperator), f"operator must be an instance of AbstractOperator, got: {operator}"
        new_node_name = operator.get_name()
        node_names = [ref.get_name() for ref in self._graph.nodes()]
        unique_name = UniqueNameGenerator(existing_names=node_names)(new_node_name)
        self._beginAddNodes([unique_name])
        new_node_ref = self._graph._create_node(operator, name=unique_name)
        if position:
            self._positions[new_node_ref.get_name()] = position.x(), position.y()
        self._endAddNodes()
        
        return True
