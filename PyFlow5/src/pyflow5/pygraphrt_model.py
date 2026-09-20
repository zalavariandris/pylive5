from collections import defaultdict
from pygraphrt.graph_rt import NodeRef
from qtpy.QtCore import QPointF
from typing import Iterable

from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel, 
    DirectionalLinkId, 
    InletName, 
    NodeName, 
    OutletName
)

import pygraphrt as rt


class PyFlowRTModel(AbstractDAGModel):
    def __init__(self, rt: rt.GraphRT):
        super().__init__()
        self.rt = rt
        self._positions: dict[NodeName, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))

    def setRT(self, rt: rt.GraphRT):
        self._beginResetModel()
        self.rt = rt
        self._endResetModel()

    # nodes
    def nodes(self)->Iterable[NodeName]:
        return [node_ref.get_name() for node_ref in self.rt.nodes()]

    def getNode(self, node_name:NodeName)->rt.NodeRef|None:
        # todo: consider caching node references by name for faster lookup
        # find noderef by the name
        for node_ref in self.rt.nodes():
            if node_ref.get_name() == node_name:
                return node_ref
        return None

    def nodePosition(self, node_name:NodeName)->QPointF:
        return QPointF(*self._positions[node_name])

    def setNodePosition(self, node_name:NodeName, position:QPointF):
        self._positions[node_name] = (position.x(), position.y())

    def nodeData(self, node_name):
        return None

    def removeNodes(self, nodes:Iterable[NodeName]):
        self._beginRemoveNodes(nodes)
        for node in list(nodes):
            node_rt = self.rt.get_node(node)
            if node_rt is not None:
                self.rt.remove_node(node_rt)
        self._endRemoveNodes()

    # ports
    def inlets(self, node:NodeName)->Iterable[InletName]:
        if node_ref := self.getNode(node):
            if op := node_ref.get_operator():
                yield from op.get_parameters().keys()
        # args, kwargs = self.rt.get_node(node).get_inputs()
        # for i, arg in enumerate(args):
        #     yield f'{i+1}'

        # for key in kwargs.keys():
        #     yield key

    def outlets(self, node:NodeName)->Iterable[OutletName]:
        return ['out']

    def inletData(self, node:NodeName, inlet:InletName):
        return None

    def outletData(self, node:NodeName, outlet:OutletName):
        return None

    # cells

    def nodeCellCount(self, node_name):
        return 0

    def nodeCellData(self, node_name, cell):
        return None

    # links

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

    def outLinks(self, node:NodeName, outlet:OutletName)->Iterable[DirectionalLinkId]:
        # todo: fix performance here
        for link in self.links():
            source, outlet, target, inlet = link
            if source == node and outlet == outlet:
                yield link
        return []

    def links(self)->Iterable[DirectionalLinkId]:
        for node_ref in self.rt.nodes():
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

    def linkSource(self, link:DirectionalLinkId):
        source, outlet, target, inlet = link
        return source, outlet

    def linkTarget(self, link:DirectionalLinkId):
        source, outlet, target, inlet = link
        return target, inlet

    def removeLinks(self, links:Iterable[DirectionalLinkId]):
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
                
        self._endRemoveLinks()

    def addLink(self, source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName):

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