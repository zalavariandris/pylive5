from pygraphrt.abstract_module_rt import OperatorRef
from qtpy.QtCore import (
    QObject, 
    Signal
)

from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .script_module_registry import ModuleRegistry
from .inline_module import InlineModuleRT
from .import_module import ImportModuleRT
from .script_module import ScriptModuleRT

from dataclasses import dataclass

@dataclass
class ResolutionSuccess:
    pass

@dataclass
class ResolutionFailure:
    reason: Exception|str

NodeResolution = ResolutionSuccess | ResolutionFailure


class GraphResolver(QObject):
    resolutions_changed = Signal(set[NodeRef])

    def __init__(self, graph: GraphDefinitionRT, module_registry: ModuleRegistry):
        self._graph = graph
        self._graph.nodes_added.connect(self._on_nodes_added)
        self._graph.nodes_removed.connect(self._on_nodes_removed)
        self._graph.nodes_changed.connect(self._on_nodes_changed)

        self._module_registry = module_registry
        self._module_registry.modules_added.connect(self._on_modules_added)
        self._module_registry.modules_removed.connect(self._on_modules_removed)
        self._module_registry.modules_changed.connect(self._on_modules_changed)

        self._resolutions: dict[NodeRef, NodeResolution] = dict()
        self._operator_to_nodes: dict[OperatorRef, set[NodeRef]] = dict()

        for node in self._graph.nodes():
            operator = node.get_operator()
            if operator not in self._operator_to_nodes:
                self._operator_to_nodes[operator] = set()
            self._operator_to_nodes[operator].add(node)

        # initial resolution
        for node in self._graph.nodes():
            self._resolutions[node] = self._resolve(node)

    def resolution(self, node:NodeRef) -> NodeResolution|None:
        return self._resolutions.get(node, None)

    def _on_nodes_added(self, nodes:list[NodeRef]):
        affected_nodes = set()
        for node in nodes:
            self._resolutions[node] = self._resolve(node)
            affected_nodes.add(node)
        if affected_nodes:
            self.resolutions_changed.emit(affected_nodes)

    def _on_nodes_removed(self, nodes:list[NodeRef]):
        affected_nodes = set()
        for node in nodes:
            if node in self._resolutions:
                del self._resolutions[node]
                affected_nodes.add(node)
        if affected_nodes:
            self.resolutions_changed.emit(affected_nodes)

    def _on_nodes_changed(self, nodes:list[NodeRef]):
        affected_nodes = set()
        for node in nodes:
            new_resolution = self._resolve(node)
            if new_resolution != self._resolutions.get(node, None):
                self._resolutions[node] = new_resolution
                affected_nodes.add(node)
        if affected_nodes:
            self.resolutions_changed.emit(affected_nodes)

    def _on_modules_added(self, modules:list[ImportModuleRT]):
        # find related nodes and mark them as resolved
        nodes_affected = set()
        for module in modules:
            if module not in self._operator_to_nodes:
                self._operator_to_nodes[module] = set()

            for node in self._operator_to_nodes[module]:
                new_resolution = self._resolve(node)
                if new_resolution != self._resolutions[node]:
                    self._resolutions[node] = self._resolve(node)
                    nodes_affected.add(node)

        if nodes_affected:
            self.resolutions_changed.emit(nodes_affected)

    def _on_modules_removed(self, modules:list[ImportModuleRT]):
        # find related nodes and mark them as unresolved
        nodes_affected = set()
        for module in modules:
            if module in self._operator_to_nodes:
                for node in self._operator_to_nodes[module]:
                    new_resolution = self._resolve(node)
                    if new_resolution != self._resolutions[node]:
                        nodes_affected.add(node)

        if nodes_affected:
            self.resolutions_changed.emit(nodes_affected)

    def _on_modules_changed(self, modules:list[ImportModuleRT]):
        nodes_affected = set()
        for module in modules:
            if module in self._operator_to_nodes:
                for node in self._operator_to_nodes[module]:
                    new_resolution = self._resolve(node)
                    if new_resolution != self._resolutions[node]:
                        self._resolutions[node] = new_resolution
        self.resolutions_changed.emit(nodes_affected)

    def _resolve(self, node:NodeRef)->NodeResolution:
        assert node is not None
        assert node in self._graph.nodes()

        operator:OperatorRef = node.get_operator()
        module = operator.module

        if module not in self._module_registry.imports():
            return ResolutionFailure(reason=f"Module {module} not found in registry")

        if operator not in module.operators():
            return ResolutionFailure(reason=f"Operator {operator} not found in module {module}")

        return ResolutionSuccess()
    