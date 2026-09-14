from collections import defaultdict
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


class PyFlowRtModel(AbstractDAGModel):
    def __init__(self, rt: rt.GraphRT):
        super().__init__()
        self.rt = rt
        self._positions: dict[NodeName, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))

    def setRT(self, rt: rt.GraphRT):
        self._beginResetModel()
        self.rt = rt
        self._endResetModel()

    def nodes(self)->Iterable[NodeName]:
        return [key for key, data in self.rt.nodes().items()]

    def nodePosition(self, node:NodeName)->QPointF:
        return QPointF(*self._positions[node])

    def setNodePosition(self, node:NodeName, position:QPointF):
        self._positions[node] = (position.x(), position.y())

    def nodeCellCount(self, node):
        return 0

    def nodeCellData(self, node, cell):
        return None

    def nodeData(self, node):
        return None

    def inLinks(self, node_name:NodeName, inlet_name:InletName)->Iterable[DirectionalLinkId]:
        node_rt:rt.NodeRT = self.rt.get_node(node_name)
        op = self.rt.get_operator(node_rt.get_operator().get_name())

        args, kwargs = node_rt.get_inputs()
        for i, key in enumerate(op.get_parameters().keys()):
            if key == inlet_name:
                if i<len(args):
                    if isinstance(args[i], rt.NodeRT):
                        yield node_rt._args[i].get_name(), 'out', node_name, inlet_name
                else:
                    if key in kwargs and isinstance(kwargs[key], rt.NodeRT):
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

    def inlets(self, node:NodeName)->Iterable[InletName]:
        node_rt = self.rt.get_node(node)
        if op := node_rt.get_operator():
            if resolved_op := self.rt.get_operator(op.get_name()):
                for key in resolved_op.get_parameters().keys():
                    yield key
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

    def links(self)->Iterable[DirectionalLinkId]:
        for node_name, node_rt in self.rt.nodes().items():
            op = node_rt.get_operator()
            # positional args bind to parameters by position, same as a real Python call
            param_names = list(op.get_parameters().keys()) if op is not None else []
            args, kwargs = node_rt.get_inputs()
            
            for i, arg in enumerate(args):
                if isinstance(arg, rt.NodeRT):
                    inlet_name = param_names[i] if i < len(param_names) else f'{i+1}'
                    yield arg.get_name(), 'out', node_name, inlet_name

            for key, value in kwargs.items():
                if isinstance(value, rt.NodeRT):
                    yield value.get_name(), 'out', node_name, key
        return []

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
            target_rt = self.rt.get_node(target)
            args, kwargs = target_rt.get_inputs()
            op = target_rt.get_operator()
            inlets = op.get_parameters().keys()
            if inlet not in inlets:
                continue

            inlet_idx = list(inlets).index(inlet)
            if inlet_idx < len(args):
                new_args = [arg for arg in args if not arg.get_name() == source]
                target_rt.set_inputs(*new_args, **kwargs)
            elif inlet in kwargs:
                new_kwargs = {k: v for k, v in kwargs.items() if not (k == inlet and isinstance(v, rt.NodeRT) and v.get_name() == source)}
                target_rt.set_inputs(*args, **new_kwargs)
        self._endRemoveLinks()

    def removeNodes(self, nodes:Iterable[NodeName]):
        self._beginRemoveNodes(nodes)
        for node in list(nodes):
            node_rt = self.rt.get_node(node)
            if node_rt is not None:
                self.rt.remove_node(node_rt)
        self._endRemoveNodes()