from collections import deque, defaultdict
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping


import math
from pathlib import Path

from dataclasses import dataclass, field

from .graph import Graph, NodeRef
from .registry import Registry
from .relations import ManyToOneRelation




class Engine:
    def __init__(self, graph, registry):
        self.graph:Graph = graph
        self.registry = registry
    
        self._operator_to_nodes = ManyToOneRelation[NodeRef, Callable]()

        self.graph.nodes_removed.connect(self._on_node_removed)
        self.graph.nodes_updated.connect(self._on_node_updated)

        self.registry.operators_removed.connect(self._on_operators_removed)
        self.registry.operators_changed.connect(self._on_operators_changed)

    def _on_operators_removed(self, operators: list[Callable]) -> None:
        # remove operator from node, but keep the realtaion
        for operator in operators:
            for node_ref in self._operator_to_nodes.children_of(operator):
                args = node_ref.resolve().args
                kwargs = node_ref.resolve().kwargs
                self.graph._update_node(node_ref, None, args, kwargs)

    def _on_operators_changed(self, operators: list[Callable]) -> None:
        # if operator references are added, add back the resolved functions
        for operator in operators:
            for node_ref in self._operator_to_nodes.children_of(operator):
                args = node_ref.resolve().args
                kwargs = node_ref.resolve().kwargs
                func = operator.resolve()
                self.graph._update_node(node_ref, operator, args, kwargs)

    def _on_node_removed(self, node_refs: list[NodeRef]) -> None:
        # remove node from operator relation
        for node_ref in node_refs:
            operator_ref = self._operator_to_nodes.parent_of(node_ref)
            self._operator_to_nodes.delete(node_ref, operator_ref)

    def _on_node_updated(self, node_refs: list[NodeRef]) -> None:
        # update operator relation for updated nodes
        raise NotImplementedError()
        for node_ref in node_refs:
            ...
        

