from collections.abc import Iterable

from pygraphrt.abstract_module_rt import AbstractModule, OperatorRef
from qtpy.QtCore import (
    QObject, 
    Signal
)

from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .module_registry import ModuleRegistry
from .script_module import ScriptModuleRT

from dataclasses import dataclass


class _GraphModuleMapper:
    """Index declared operator references without checking their availability."""

    def __init__(self, graph: GraphDefinitionRT) -> None:
        self._graph = graph
        self._node_to_operator: dict[NodeRef, OperatorRef | None] = {}
        self._operator_to_nodes: dict[OperatorRef, set[NodeRef]] = {}

        self._index_nodes(graph.nodes())
        graph.nodes_added.connect(self._index_nodes)
        graph.nodes_changed.connect(self._index_nodes)
        graph.nodes_removed.connect(self._unindex_nodes)

    def operator_for_node(self, node: NodeRef) -> OperatorRef | None:
        """Return the reference, or None for an untracked or operatorless node."""
        return self._node_to_operator.get(node)

    def nodes_for_operator(self, operator: OperatorRef) -> set[NodeRef]:
        """Return a copy of the nodes referencing this operator."""
        return set(self._operator_to_nodes.get(operator, ()))

    def nodes_for_operators(self, operators: Iterable[OperatorRef]) -> set[NodeRef]:
        """Return the union of nodes referencing the supplied operators."""
        nodes: set[NodeRef] = set()
        for operator in operators:
            nodes.update(self._operator_to_nodes.get(operator, ()))
        return nodes

    def nodes_for_module(self, module: AbstractModule) -> set[NodeRef]:
        """Include references to operators that are currently missing, too."""
        nodes: set[NodeRef] = set()
        for operator, related_nodes in self._operator_to_nodes.items():
            if operator.module == module:
                nodes.update(related_nodes)
        return nodes

    def _index_nodes(self, nodes: list[NodeRef]) -> None:
        for node in nodes:
            operator = node.get_operator()
            self._unindex_node(node)
            self._node_to_operator[node] = operator
            if operator is not None:
                self._operator_to_nodes.setdefault(operator, set()).add(node)

    def _unindex_nodes(self, nodes: list[NodeRef]) -> None:
        for node in nodes:
            self._unindex_node(node)

    def _unindex_node(self, node: NodeRef) -> None:
        # Removed nodes can no longer supply their previous operator.
        operator = self._node_to_operator.pop(node, None)
        if operator is None:
            return

        nodes = self._operator_to_nodes[operator]
        nodes.remove(node)
        if not nodes:
            del self._operator_to_nodes[operator]


class GraphResolver(QObject):
    nodes_invalidated = Signal(set) # set[NodeRef]

    @dataclass
    class ResolutionSuccess:
        pass

    @dataclass
    class ResolutionFailure:
        reason: Exception|str

    NodeResolution = ResolutionSuccess | ResolutionFailure

    def __init__(self, graph: GraphDefinitionRT, module_registry: ModuleRegistry, parent:QObject=None):
        super().__init__(parent=parent)
        self._graph = graph
        self._graph.nodes_added.connect(self._on_nodes_added)
        self._graph.nodes_removed.connect(self._on_nodes_removed)
        self._graph.nodes_changed.connect(self._on_nodes_changed)

        self._module_registry = module_registry
        self._module_registry.modules_added.connect(self._on_modules_added)
        self._module_registry.modules_removed.connect(self._on_modules_removed)
        # self._module_registry.modules_changed.connect(self._on_modules_changed)
        self._module_registry.operators_added.connect(self._on_operators_added)
        self._module_registry.operators_removed.connect(self._on_operators_removed)
        self._module_registry.operators_changed.connect(self._on_operators_changed)

        # Track each node's indexed operator, including after changes or deletion.
        self._node_to_operator: dict[NodeRef, OperatorRef | None] = {}
        self._operator_to_nodes: dict[OperatorRef, set[NodeRef]] = dict()

        # initial resolution
        self._resolutions: dict[NodeRef, GraphResolver.NodeResolution] = dict()
        for node in self._graph.nodes():
            self._index_node(node)
            self._resolutions[node] = self._resolve(node)

    def resolution(self, node:NodeRef) -> NodeResolution|None:
        return self._resolutions.get(node, None)

    def _index_node(self, node: NodeRef) -> None:
        self._unindex_node(node)
        operator = node.get_operator()
        self._node_to_operator[node] = operator
        if operator is not None:
            self._operator_to_nodes.setdefault(operator, set()).add(node)

    def _unindex_node(self, node: NodeRef) -> None:
        operator = self._node_to_operator.pop(node, None)
        if operator is None:
            return

        nodes = self._operator_to_nodes[operator]
        nodes.remove(node)
        if not nodes:
            del self._operator_to_nodes[operator]

    def _on_nodes_added(self, nodes:list[NodeRef]) -> None:
        affected_nodes = set()
        for node in nodes:
            self._index_node(node)
            self._resolutions[node] = self._resolve(node)
            affected_nodes.add(node)

        if affected_nodes:
            self.nodes_invalidated.emit(affected_nodes)

    def _on_nodes_removed(self, nodes:list[NodeRef]) -> None:
        affected_nodes = set()
        for node in nodes:
            self._unindex_node(node)
            if node in self._resolutions:
                del self._resolutions[node]
                affected_nodes.add(node)

        if affected_nodes:
            self.nodes_invalidated.emit(affected_nodes)

    def _on_nodes_changed(self, nodes:list[NodeRef]) -> None:
        # resolve the affected nodes
        new_resolutions = dict()
        for node in nodes:
            self._index_node(node)
            new_resolutions[node] = self._resolve(node)

        # update the resolutions of the affected nodes
        nodes_affected = set()
        for node, new_resolution in new_resolutions.items():
            if new_resolution != self._resolutions.get(node, None):
                self._resolutions[node] = new_resolution
                nodes_affected.add(node)

        if nodes_affected:
            self.nodes_invalidated.emit(nodes_affected)

    def _on_modules_added(self, modules:list[ScriptModuleRT]) -> None:
        # Include references to operators that are currently missing, too.
        related_nodes: set[NodeRef] = set()
        for operator, nodes in self._operator_to_nodes.items():
            if operator.module in modules:
                related_nodes.update(nodes)

        # resolve the affected nodes
        new_resolutions = dict()
        for node in related_nodes:
            new_resolutions[node] = self._resolve(node)

        # update the resolutions of the affected nodes
        nodes_affected = set()
        for node, new_resolution in new_resolutions.items():
            if new_resolution != self._resolutions.get(node, None):
                self._resolutions[node] = new_resolution
                nodes_affected.add(node)

        if nodes_affected:
            self.nodes_invalidated.emit(nodes_affected)

    def _on_operators_added(self, operators:list[OperatorRef]) -> None:
        # find nodes related to the added operators
        related_nodes = set()
        for op in operators:
            if op in self._operator_to_nodes:
                for node in self._operator_to_nodes[op]:
                    related_nodes.add(node)

        # resolve the affected nodes
        new_resolutions = dict()
        for node in related_nodes:
            new_resolutions[node] = self._resolve(node)

        # update the resolutions of the affected nodes
        nodes_affected = set()
        for node, new_resolution in new_resolutions.items():
            if new_resolution != self._resolutions.get(node, None):
                self._resolutions[node] = new_resolution
                nodes_affected.add(node)

        if nodes_affected:
            self.nodes_invalidated.emit(nodes_affected)

    def _on_modules_removed(self, modules:list[ScriptModuleRT]) -> None:
        # Include references to operators that are currently missing, too.
        related_nodes: set[NodeRef] = set()
        for operator, nodes in self._operator_to_nodes.items():
            if operator.module in modules:
                related_nodes.update(nodes)

        # resolve the affected nodes
        nodes_affected = set()
        for node in related_nodes:
            new_resolution = self._resolve(node)
            if new_resolution != self._resolutions.get(node, None):
                self._resolutions[node] = new_resolution
                nodes_affected.add(node)

        if nodes_affected:
            self.nodes_invalidated.emit(nodes_affected)

    def _on_operators_removed(self, operators:list[OperatorRef]) -> None:
        related_nodes = set()
        for op in operators:
            if op in self._operator_to_nodes:
                for node in self._operator_to_nodes[op]:
                    related_nodes.add(node)

        # compute new resolutions for the related nodes
        new_resolutions = dict()
        for node in related_nodes:
            new_resolutions[node] = self._resolve(node)

        # update the resolutions for the affected nodes
        nodes_affected = set()
        for node, new_resolution in new_resolutions.items():
            if new_resolution != self._resolutions.get(node, None):
                self._resolutions[node] = new_resolution
                nodes_affected.add(node)

        if nodes_affected:
            self.nodes_invalidated.emit(nodes_affected)

    def _on_operators_changed(self, operators:list[OperatorRef]) -> None:
        nodes_affected = set()

        # compute new resolutions for the nodes affected by the changed operators
        new_resolutions = dict()
        for op in operators:
            if op in self._operator_to_nodes:
                for node in self._operator_to_nodes[op]:
                    new_resolutions[node] = self._resolve(node)

        # update the resolutions for the affected nodes
        for node, new_resolution in new_resolutions.items():
            if new_resolution != self._resolutions.get(node):
                self._resolutions[node] = new_resolution
                nodes_affected.add(node)

        if nodes_affected:
            self.nodes_invalidated.emit(nodes_affected)

    def _resolve(self, node:NodeRef)->"GraphResolver.NodeResolution":
        assert node is not None
        assert node in self._graph.nodes()

        operator: OperatorRef | None = node.get_operator()
        if operator is None:
            return self.ResolutionFailure(reason="Node has no operator")

        module = operator.module

        if module not in self._module_registry.modules():
            return self.ResolutionFailure(reason=f"Module {module} not found in registry")

        if operator not in module.operators():
            return self.ResolutionFailure(reason=f"Operator {operator} not found in module {module}")

        return self.ResolutionSuccess()
