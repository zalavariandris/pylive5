from pygraphrt.abstract_module_rt import OperatorRef
from qtpy.QtCore import (
    QObject, 
    Signal
)

from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .script_module_registry import ScriptModuleRegistry
from .script_module import ScriptModuleRT

from dataclasses import dataclass




class GraphResolver(QObject):
    resolutions_changed = Signal(set) # set[NodeRef]

    @dataclass
    class ResolutionSuccess:
        pass

    @dataclass
    class ResolutionFailure:
        reason: Exception|str

    NodeResolution = ResolutionSuccess | ResolutionFailure

    def __init__(self, graph: GraphDefinitionRT, module_registry: ScriptModuleRegistry, parent:QObject=None):
        super().__init__(parent=parent)
        self._graph = graph
        self._graph.nodes_added.connect(self._on_nodes_added)
        self._graph.nodes_removed.connect(self._on_nodes_removed)
        self._graph.nodes_changed.connect(self._on_nodes_changed)

        self._module_registry = module_registry
        self._module_registry.modules_added.connect(self._on_modules_added)
        self._module_registry.modules_removed.connect(self._on_modules_removed)
        self._module_registry.modules_changed.connect(self._on_modules_changed)
        self._module_registry.operators_added.connect(self._on_operators_added)
        self._module_registry.operators_removed.connect(self._on_operators_removed)
        self._module_registry.operators_changed.connect(self._on_operators_changed)

        # inverse mapping from operators to nodes
        self._operator_to_nodes: dict[OperatorRef, set[NodeRef]] = dict()
        self._rebuild_operator_index()

        # initial resolution
        self._resolutions: dict[NodeRef, GraphResolver.NodeResolution] = dict()
        for node in self._graph.nodes():
            self._resolutions[node] = self._resolve(node)

    def resolution(self, node:NodeRef) -> NodeResolution|None:
        return self._resolutions.get(node, None)

    def _rebuild_operator_index(self) -> None:
        # todo: need optimization: Either use pre/post change handlers or keep previous state to avoid full rebuild
        # A) With pre/post change handlers, we could remove old index entries before
        #   a mutation and add new entries afterward using only those handlers.
        #   This need a refactor for the events. but pre handlers seem to be 
        #   useful in several situations, as well as seem to be quite a standard.
        # B) Our signals arrive after changes, so we cant clean up the old index entries,
        #   we could keep the previous state here to find which entries need to be removed.
        #   This approach seem to be fragile and may require careful handling of previous state.
        # C) there might be other optimization strategies we could consider... 
        # - For now we simply rebuild the entire index on each node event.
        self._operator_to_nodes.clear()
        for node in self._graph.nodes():
            operator = node.get_operator()
            if operator is not None:
                self._operator_to_nodes.setdefault(operator, set()).add(node)

    def _on_nodes_added(self, nodes:list[NodeRef]) -> None:
        self._rebuild_operator_index()
        affected_nodes = set()
        for node in nodes:
            self._resolutions[node] = self._resolve(node)
            affected_nodes.add(node)
        if affected_nodes:
            self.resolutions_changed.emit(affected_nodes)

    def _on_nodes_removed(self, nodes:list[NodeRef]) -> None:
        self._rebuild_operator_index()
        affected_nodes = set()
        for node in nodes:
            if node in self._resolutions:
                del self._resolutions[node]
                affected_nodes.add(node)

        if affected_nodes:
            self.resolutions_changed.emit(affected_nodes)

    def _on_nodes_changed(self, nodes:list[NodeRef]) -> None:
        self._rebuild_operator_index()
        # resolve the affected nodes
        new_resolutions = dict()
        for node in nodes:
            new_resolutions[node] = self._resolve(node)

        # update the resolutions of the affected nodes
        nodes_affected = set()
        for node, new_resolution in new_resolutions.items():
            if new_resolution != self._resolutions.get(node, None):
                self._resolutions[node] = new_resolution
                nodes_affected.add(node)

        if nodes_affected:
            self.resolutions_changed.emit(nodes_affected)

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
            self.resolutions_changed.emit(nodes_affected)

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
            self.resolutions_changed.emit(nodes_affected)

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
            self.resolutions_changed.emit(nodes_affected)

    def _on_modules_changed(self, modules:list[ScriptModuleRT]) -> None:
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
            self.resolutions_changed.emit(nodes_affected)

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
            self.resolutions_changed.emit(nodes_affected)

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
            self.resolutions_changed.emit(nodes_affected)

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
