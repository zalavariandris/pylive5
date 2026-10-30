from concurrent.futures import Future
from typing import Any, Callable, Iterable
from pygraphrt2.inline_backend import InlineBackend, ExecutionFailure
from pygraphrt2.threaded_backend import ThreadedBackend


from qtpy.QtCore import QObject, Signal

from .graph import Graph, NodeRef
from .inline_scriptmodule import InlineScriptModule, ScriptOperatorRef
from .relations import ManyToOneRelation

from .execution_plan import evaluate, prepare, execute

class Engine(QObject):
    nodes_invalidated = Signal(list)
    nodes_executed = Signal(dict)
    execution_failed = Signal(Exception)
    registry_invalidated = Signal()
    registry_evaluated = Signal()
    registry_failed = Signal(Exception)

    def __init__(
        self, 
        graph: Graph | None = None, 
        registry: InlineScriptModule | None = None
    ) -> None:
        super().__init__()
        self.graph = graph if graph is not None else Graph()
        self.registry = registry if registry is not None else InlineScriptModule()

        self._backend = ThreadedBackend(self.graph)
        self._closed = False
        self._operator_to_nodes = ManyToOneRelation[NodeRef, ScriptOperatorRef]()
        self._preserve_operator_bindings: set[NodeRef] = set()
        self._sync_node_operator_mappings(self.graph.nodes())
        self._connections = [
            (self.graph.nodes_added, self._on_nodes_changed),
            (self.graph.nodes_changed, self._on_nodes_changed),
            (self.graph.nodes_removed, self._remove_node_operator_mappings),
            (self.graph.nodes_removed, self._prune_auto_execution_targets),
            (self.registry.registry_invalidated, self.registry_invalidated.emit),
            (self.registry.registry_invalidated, self._auto_evaluate_registry),
            (self.registry.operators_changed, self._on_operators_changed),
            (self.registry.operators_removed, self._on_operators_removed),
            (self.registry.operators_added, self._on_operators_added)
            
        ]
        for signal, slot in self._connections:
            signal.connect(slot)

        # auto evaluate and execution flags
        self._auto_execute = True
        self._auto_execute_targets: set[NodeRef] | None = None

    def _on_operators_changed(self, operators: list[ScriptOperatorRef]) -> None:
        print("Operators changed:", [op.name() for op in operators])
        affected_nodes: set[NodeRef] = set()
        for operator in operators:
            affected_nodes.update(self._operator_to_nodes.children_of(operator))
        if affected_nodes:
            self._invalidate_descendants(list(affected_nodes))

    def _on_operators_removed(self, operators: list[ScriptOperatorRef]) -> None:
        for operator in operators:
            for node in self._operator_to_nodes.children_of(operator):
                state = node.resolve()
                self._preserve_operator_bindings.add(node)
                try:
                    self.graph._update_node(
                        node,
                        func=None,
                        args=state.args,
                        kwargs=state.kwargs,
                    )
                finally:
                    self._preserve_operator_bindings.discard(node)

    def _on_operators_added(self, operators: list[ScriptOperatorRef]) -> None:
        for operator in operators:
            for node in self._operator_to_nodes.children_of(operator):
                state = node.resolve()
                binding = self._operator_to_nodes.parent_of(node)
                if binding is None:
                    continue
                self.graph._update_node(
                    node,
                    func=binding,
                    args=state.args,
                    kwargs=state.kwargs,
                )

    # node operator binding
    def node_operator(self, node_ref: NodeRef) -> ScriptOperatorRef | None:
        """Return the node's script binding, including unavailable references."""
        return self._operator_to_nodes.parent_of(node_ref)

    def _on_nodes_changed(self, nodes: list[NodeRef]) -> None:
        self._sync_node_operator_mappings(nodes)
        self._invalidate_descendants(nodes)

    def _sync_node_operator_mappings(self, nodes: list[NodeRef]) -> None:
        # Retain script bindings while registry-driven updates clear operators.
        for node in nodes:
            operator = node.resolve().operator
            if node in self._preserve_operator_bindings and operator is None:
                continue
            previous = self._operator_to_nodes.parent_of(node)
            if isinstance(operator, ScriptOperatorRef):
                self._operator_to_nodes.set(node, operator)
            elif previous is not None:
                self._operator_to_nodes.delete(node, previous)

    def _remove_node_operator_mappings(self, nodes: list[NodeRef]) -> None:
        # Graph emits nodes_changed for surviving consumers after removing links.
        for node in nodes:
            operator = self._operator_to_nodes.parent_of(node)
            if operator is not None:
                self._operator_to_nodes.delete(node, operator)

    def _invalidate_descendants(self, nodes: list[NodeRef]) -> None:
        affected: set[NodeRef] = set()
        for node in nodes:
            affected.update(self.graph.descendants(node))

        invalidated = [
            node for node in self.graph.nodes()
            if node in affected
        ]

        if not invalidated:
            return

        self.nodes_invalidated.emit(invalidated)
        # Call directly after notifying observers so their invalidation handlers
        # clear stale outputs before execution publishes fresh results.
        self._auto_execute_invalidated(invalidated)

    # Execution backend
    def evaluate_registry(self) -> None:
        if self._closed:
            return

        evaluate_future = self._backend.evaluate(self.registry.get_script(), name="<registry>")
        def _on_done(fut: Future[dict[str, Callable[..., Any]]]) -> None:
            try:
                functions = fut.result()
                
            except Exception as error:
                self.registry_failed.emit(error)
                self.registry._apply_functions(dict(), error)
                # todo: here we should update the nodes that are relevant to the changed registry entries.
                #       here we need to know what operators have actually changed
                #       the above code is syncronus by the way. an async backend would need to have a signal.
                self._invalidate_descendants(self.graph.nodes())
            else:
                self.registry_evaluated.emit()
                self.registry._apply_functions(functions, "VALID")
                # self._invalidate_descendants(self.graph.nodes())

        evaluate_future.add_done_callback(_on_done)

    def execute_nodes(self, *targets: NodeRef) -> None:
        if self._closed:
            return
        if not targets:
            return
        
        plan, mapping = prepare(self.graph, targets)
        output_future = self._backend.execute_plan(plan)
        def _on_done(fut: Future[dict[str, Any]]) -> None:
            try:
                plan_outputs = fut.result()
            except Exception as error:
                self.execution_failed.emit(error)
            else:
                outputs = {mapping[name]: value for name, value in plan_outputs.items()}
                self.nodes_executed.emit(outputs)

        output_future.add_done_callback(_on_done)
        # try:
            
        # except ExecutionFailure as error:
        #     self.execution_failed.emit(error)
        # else:
        #     self.nodes_executed.emit(outputs)

    def _prune_auto_execution_targets(self, nodes: list[NodeRef]) -> None:
        if self._auto_execute_targets is not None:
            self._auto_execute_targets.difference_update(nodes)

    def auto_execute(self) -> bool:
        return self._auto_execute

    def set_auto_execute(self, value: bool) -> None:
        """Toggle automatic execution, refreshing watched nodes when enabled."""
        if self._auto_execute == value:
            return

        self._auto_execute = value
        if value:
            self.evaluate_registry()

    def set_auto_execute_targets(
        self, targets: Iterable[NodeRef] | None
    ) -> None:
        """Watch all nodes with None, or a selection; refresh newly watched nodes."""
        previous = self._auto_execute_targets
        updated = None if targets is None else set(targets)
        if previous == updated:
            return

        self._auto_execute_targets = updated
        if self._closed or not self._auto_execute:
            return
        if previous is None:
            return  # Every node was already watched.

        new_targets = [
            node for node in self.graph.nodes()
            if node not in previous and (updated is None or node in updated)
        ]
        if new_targets:
            self.execute_nodes(*new_targets)

    def _auto_evaluate_registry(self) -> None:
        """Automatically evaluate the registry if auto-execute is enabled."""
        if self._closed:
            return

        if not self._auto_execute:
            return

        self.evaluate_registry()

    def _auto_execute_invalidated(
        self, invalidated: list[NodeRef]
    ) -> None:
        """Automatically execute invalidated nodes if auto-execute is enabled."""
        if self._closed or not self._auto_execute:
            return

        watched = self._auto_execute_targets
        targets = [
            node
            for node in invalidated
            if watched is None or node in watched
        ]

        if not targets:
            return

        self.execute_nodes(*targets)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
