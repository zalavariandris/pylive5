from collections import defaultdict

from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import NodeRef
from pytools import UniqueNameGenerator
from qtpy.QtCore import QPointF, Slot
from typing import Iterable, override

from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel,
    CellIdx, 
    DirectionalLinkId, 
    InletName, 
    NodeName, 
    OutletName
)

import pygraphrt as rt
from qtpy.QtCore import (
    QObject, 
    Qt,
    Signal,
    QPointF
)
from qtpy.QtGui import QColor
from typing import Any

class PyFlowRTModel(AbstractDAGModel):
    def __init__(self, rt: rt.GraphRT):
        super().__init__()
        self._rt = rt
        self._positions: dict[NodeName, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))
        self._observed_modules = set()
        self._connect_runtime()

    def setRT(self, rt: rt.GraphRT, positions=None):
        self._beginResetModel()
        self._disconnect_runtime()
        self._rt = rt
        self._positions = defaultdict(lambda: (0.0, 0.0), positions or {})
        self._connect_runtime()
        self._endResetModel()

    def reset(self) -> None:
        """Recover presentation state from the current runtime without changing it.

        Call after a failed mutation has unwound, not from a mutation signal handler.
        """
        node_names = {node.get_name() for node in self._rt.nodes()}
        positions = {name: position for name, position in self._positions.items()
                     if name in node_names}
        # Recovery deliberately abandons notifications left open by a failed edit.
        self._message_queue.clear()
        self._beginResetModel()
        self._positions = defaultdict(lambda: (0.0, 0.0), positions)
        self._refresh_module_subscriptions()
        self._endResetModel()

    def _connect_runtime(self):
        self._rt.nodes_added.connect(self._refresh_module_subscriptions)
        self._rt.nodes_removed.connect(self._refresh_module_subscriptions)
        self._rt.nodes_changed.connect(self._on_runtime_nodes_changed)
        self._refresh_module_subscriptions()

    def _disconnect_runtime(self):
        self._rt.nodes_added.disconnect(self._refresh_module_subscriptions)
        self._rt.nodes_removed.disconnect(self._refresh_module_subscriptions)
        self._rt.nodes_changed.disconnect(self._on_runtime_nodes_changed)
        for module in self._observed_modules:
            self._disconnect_module(module)
        self._observed_modules.clear()

    def _disconnect_module(self, module):
        for signal in (module.operators_added, module.operators_removed,
                       module.operators_changed):
            signal.disconnect(self._on_operators_changed)

    @Slot(list)
    def _refresh_module_subscriptions(self, nodes=None):
        modules = {ref.module for node in self._rt.nodes()
                   if (ref := node.get_operator()) is not None}
        for module in self._observed_modules - modules:
            self._disconnect_module(module)
        for module in modules - self._observed_modules:
            for signal in (module.operators_added, module.operators_removed,
                           module.operators_changed):
                signal.connect(self._on_operators_changed)
        self._observed_modules = modules

    def _notify_node_presentation(self, names):
        if names:
            self.nodeDataChanged.emit(tuple(names))
            for name in names:
                self.inletsChanged.emit(name)

    @Slot(list)
    def _on_runtime_nodes_changed(self, nodes):
        self._refresh_module_subscriptions()
        self._notify_node_presentation([node.get_name() for node in nodes])

    @Slot(list)
    def _on_operators_changed(self, operators):
        changed = set(operators)
        self._notify_node_presentation([
            node.get_name() for node in self._rt.nodes()
            if node.get_operator() in changed
        ])

    # nodes
    @override
    def nodes(self)->Iterable[NodeName]:
        return [
            node_ref.get_name() 
            for node_ref in self._rt.nodes()
        ]

    def getNode(self, node_name:NodeName)->rt.NodeRef|None:
        # todo: consider caching node references by name for faster lookup
        # find noderef by the name
        for node_ref in self._rt.nodes():
            if node_ref.get_name() == node_name:
                return node_ref
        return None

    @override
    def nodePosition(self, node_name:NodeName)->QPointF:
        if node_name in self._positions:
            x, y = self._positions[node_name]
            return QPointF(x, y)
        else:
            return QPointF(0.0, 0.0)

    @override
    def setNodePosition(self, node_name:NodeName, position:QPointF|None):
        if position:
            self._positions[node_name] = (position.x(), position.y())
        else:
            del self._positions[node_name]

    @override
    def nodeData(self, node: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node_ref = self.getNode(node)
        if node_ref is None:
            return None
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return node_ref.get_operator()
            case Qt.ItemDataRole.BackgroundRole:
                if op_ref:=node_ref.get_operator():
                    if op_ref.get_value() is not None:
                        return None
                return QColor(Qt.GlobalColor.red) # return red color for missing operator
            case _:
                return None

    def removeNodes(self, nodes:Iterable[NodeName]):
        self._beginRemoveNodes(nodes)
        for node_name in list(nodes):
            node_ref = self.getNode(node_name)
            assert node_ref is not None, f"Node '{node_name}' not found"

            self._rt.remove_node(node_ref)
            self._positions.pop(node_name, None)
        self._endRemoveNodes()

    # ports
    def _node_inlets(self, node_ref: NodeRef):
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
    def inlets(self, node:NodeName)->Iterable[InletName]:
        if node_ref := self.getNode(node):
            inlets, _ = self._node_inlets(node_ref)
            yield from inlets

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

    # links
    def _node_input_links(self, node_ref: NodeRef)->Iterable[DirectionalLinkId]:
        _, bindings = self._node_inlets(node_ref)
        for inlet, value in bindings:
            if isinstance(value, NodeRef):
                yield value.get_name(), 'out', node_ref.get_name(), inlet

    @override
    def inLinks(self, node_name:NodeName, inlet_name:InletName)->Iterable[DirectionalLinkId]:
        if node_ref := self.getNode(node_name):
            for link in self._node_input_links(node_ref):
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
        for node_ref in self._rt.nodes():
            yield from self._node_input_links(node_ref)

    @override
    def linkSource(self, link:DirectionalLinkId) -> tuple[NodeName|OutletName]|None:
        source, outlet, target, inlet = link
        return source, outlet

    @override
    def linkTarget(self, link:DirectionalLinkId) -> tuple[NodeName|InletName]|None:
        source, outlet, target, inlet = link
        return target, inlet

    @override
    def removeLinks(self, links:Iterable[DirectionalLinkId])->bool:
        self._beginRemoveLinks(links)
        for link in list(links):
            source, outlet, target, inlet = link
            target_rt:NodeRef = self.getNode(target)
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

    def addLink(self, source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName)->None:
        self._beginAddLinks([(source, outlet, target, inlet)])
        target_ref = self.getNode(target)
        source_ref = self.getNode(source)
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

    def addNode(self, operator:OperatorRef, position:QPointF|None=None)->bool:
        """
        position: QPointF|None, in scene coordinates"""
        assert isinstance(operator, OperatorRef), f"operator must be an instance of OperatorRef, got: {operator}"
        new_node_name = operator.name
        node_names = [ref.get_name() for ref in self._rt.nodes()]
        unique_name = UniqueNameGenerator(existing_names=node_names)(new_node_name)
        self._beginAddNodes([unique_name])
        new_node_ref = self._rt.node()(operator, name=unique_name)
        if position:
            self._positions[new_node_ref.get_name()] = position.x(), position.y()
        self._endAddNodes()
        
        return True
