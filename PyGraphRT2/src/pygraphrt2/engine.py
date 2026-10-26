from qtpy.QtCore import QObject, Signal

from .graph import Graph, NodeRef
from .registry import Registry
from .script_module import ScriptModule, ScriptOperatorRef
from .relations import ManyToOneRelation
from .inline_executor import InlineExecutor
from .inline_executor import ExecutionFailure


class Engine(QObject):
    nodes_invalidated = Signal(list) # list[NodeRef]
    nodes_executed = Signal(dict) # dict[NodeRef, object]
    execution_failed = Signal(Exception)

    def __init__(self, 
        graph: Graph|None=None,
        registry: ScriptModule|None=None
    ):
        super().__init__()
        self.graph:Graph = graph or Graph()
        self.registry: ScriptModule = registry or ScriptModule()
        self._executor = InlineExecutor(self.graph)

        # 
        self.graph.nodes_removed.connect(lambda nodes: self._invalidate_descendants(nodes))
    
        # keep track of node-operator mappings
        self._operator_to_nodes = ManyToOneRelation[NodeRef, ScriptOperatorRef]()
        self.graph.nodes_removed.connect(lambda nodes: self._remove_node_operator_mappings(nodes))
        self.graph.nodes_changed.connect(lambda nodes: self._sync_node_operator_mappings(nodes))
        self.registry.operators_removed.connect(lambda operators: self._clear_node_operators(operators))
        self.registry.operators_changed.connect(lambda operators: self._refresh_node_operators(operators))

    def execute(self, *targets: NodeRef) -> None:
        try:
            outputs = self._executor.execute(*targets)
            self.nodes_executed.emit(outputs)
        except ExecutionFailure as e:
            self.execution_failed.emit(e)

    def node_operator(self, node_ref: NodeRef) -> ScriptOperatorRef | None:
        return self._operator_to_nodes.parent_of(node_ref)

    def _invalidate_descendants(self, node_refs: list[NodeRef]) -> None:
        all_descendants: set[NodeRef] = set()
        for node_ref in node_refs:
            all_descendants.update(self.graph.descendants(node_ref))
        if all_descendants:
            self.nodes_invalidated.emit(list(all_descendants))

    def _clear_node_operators(self, operators: list[ScriptOperatorRef]) -> None:
        # ... remove operator from node, but keep the realtaion
        for operator in operators:
            for node_ref in self._operator_to_nodes.children_of(operator):
                node_state = node_ref.resolve()
                args = node_state.args
                kwargs = node_state.kwargs
                self.graph._update_node(node_ref, None, args, kwargs)

    def _refresh_node_operators(self, operators: list[ScriptOperatorRef]) -> None:
        # ... if operator references are added, add back the resolved functions
        for operator in operators:
            for node_ref in self._operator_to_nodes.children_of(operator):
                node_state = node_ref.resolve()
                args = node_state.args
                kwargs = node_state.kwargs
                self.graph._update_node(node_ref, operator, args, kwargs)

    def _remove_node_operator_mappings(self, node_refs: list[NodeRef]) -> None:
        # ... remove node from operator relation
        for node_ref in node_refs:
            operator_ref = self._operator_to_nodes.parent_of(node_ref)
            if operator_ref is None:
                continue
            self._operator_to_nodes.delete(node_ref, operator_ref)

    def _sync_node_operator_mappings(self, node_refs: list[NodeRef]) -> None:
        # update operator relation for updated nodes
        for node_ref in node_refs:
            node_state = node_ref.resolve()
            operator_ref = node_state.operator
            if operator_ref is not None:
                self._operator_to_nodes.add(node_ref, operator_ref)
            # ... remove old operator relation
            old_operator_ref = self._operator_to_nodes.parent_of(node_ref)
            if old_operator_ref is not None:
                self._operator_to_nodes.delete(node_ref, old_operator_ref)
            
            # ... add new operator relation if available
            new_operator_ref = node_ref.resolve().operator
            if not isinstance(new_operator_ref, ScriptOperatorRef):
                raise NotImplementedError("Only ScriptOperatorRef is supported for now.")
            if new_operator_ref is not None:
                self._operator_to_nodes.set(node_ref, new_operator_ref)
        