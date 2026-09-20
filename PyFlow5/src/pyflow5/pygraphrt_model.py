from collections import defaultdict
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import NodeRef
from pytools import UniqueNameGenerator
from qtpy.QtCore import QPointF
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
from typing import Any

class PyFlowRTModel(AbstractDAGModel):
    def __init__(self, rt: rt.GraphRT):
        super().__init__()
        self._rt = rt
        self._positions: dict[NodeName, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))

    def setRT(self, rt: rt.GraphRT):
        self._beginResetModel()
        self._rt = rt
        self._endResetModel()

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
        return None

    def removeNodes(self, nodes:Iterable[NodeName]):
        self._beginRemoveNodes(nodes)
        for node_name in list(nodes):
            node_ref = self.getNode(node_name)
            if node_ref is not None:
                self._rt.remove_node(node_ref)
        self._endRemoveNodes()

    # ports
    @override
    def inlets(self, node:NodeName)->Iterable[InletName]:
        if node_ref := self.getNode(node):
            if op := node_ref.get_operator():
                yield from op.get_parameters().keys()

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
    @override
    def inLinks(self, node_name:NodeName, inlet_name:InletName)->Iterable[DirectionalLinkId]:
        node_ref:rt.NodeRef = self.getNode(node_name)
        op = node_ref.get_operator()
        if op is None:
            return

        args, kwargs = node_ref.get_inputs()
        for i, key in enumerate(op.get_parameters().keys()):
            if key == inlet_name:
                if i<len(args):
                    if isinstance(args[i], rt.NodeRef):
                        yield args[i].get_name(), 'out', node_name, inlet_name
                else:
                    if key in kwargs and isinstance(kwargs[key], rt.NodeRef):
                        yield kwargs[key].get_name(), 'out', node_name, inlet_name

        # args, kwargs = node_rt.get_inputs()
        # for arg in args:
        #     if arg == inlet_name:
        #         ...

        # for kwarg, m_value in kwargs.items():
        #     if kwarg == inlet_name:
        #         if isinstance(m_value, rt.NodeRT):
        #             yield m_value.get_name(), 'out', node_name, inlet_name
        # return []

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
            op = node_ref.get_operator()
            # positional args bind to parameters by position, same as a real Python call
            param_names = list(op.get_parameters().keys()) if op is not None else []
            args, kwargs = node_ref.get_inputs()
            
            for i, value in enumerate(args):
                if isinstance(value, rt.NodeRef):
                    inlet_name = param_names[i] if i < len(param_names) else f'{i+1}'
                    yield value.get_name(), 'out', node_ref.get_name(), inlet_name

            for key, value in kwargs.items():
                if isinstance(value, rt.NodeRef):
                    yield value.get_name(), 'out', node_ref.get_name(), key

        yield from []

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
        if inlet_idx < len(args):
            args[inlet_idx] = source_ref
        else:
            kwargs[inlet] = source_ref

            target_ref.set_inputs(*args, **kwargs)
            print(f"Updated inputs for target node '{target}': args={args}, kwargs={kwargs}")
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