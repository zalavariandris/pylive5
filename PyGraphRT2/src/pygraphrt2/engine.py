from concurrent.futures import Future
from dataclasses import replace
from typing import Any, Callable, Iterable
from pygraphrt2.threaded_backend import ThreadedBackend


from qtpy.QtCore import Qt, QObject, Signal, Slot

from .graph import Graph, NodeRef
from .inline_scriptmodule import InlineScriptModule, ScriptOperatorRef
from .relations import ManyToOneRelation

from .execution_plan import prepare

class Engine(QObject):
    nodes_invalidated = Signal(list)
    nodes_executed = Signal(dict)
    execution_failed = Signal(Exception)
    registry_invalidated = Signal()
    registry_evaluated = Signal()
    registry_failed = Signal(Exception)
    _evaluation_finished = Signal(int, object)
    _execution_finished = Signal(int, object, object)

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
        self._evaluation_id = 0
        self._evaluation_pending = False
        self._evaluation_future: Future[dict[str, Callable[..., Any]]] | None = None
        self._pending_targets: set[NodeRef] = set()
        self._execution_id = 0
        self._execution_future: Future[dict[str, Any]] | None = None
        self._evaluation_finished.connect(
            self._on_evaluation_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._execution_finished.connect(
            self._on_execution_finished,
            Qt.ConnectionType.QueuedConnection,
        )
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
        self._invalidate_execution()
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

        self._invalidate_execution()
        self.nodes_invalidated.emit(invalidated)
        # Call directly after notifying observers so their invalidation handlers
        # clear stale outputs before execution publishes fresh results.
        self._auto_execute_invalidated(invalidated)

    # Execution backend
    def _invalidate_evaluation(self) -> None:
        self._evaluation_id += 1
        self._evaluation_pending = False
        if self._evaluation_future is not None:
            self._evaluation_future.cancel()
            self._evaluation_future = None

    def _invalidate_execution(self) -> None:
        self._execution_id += 1
        if self._execution_future is not None:
            self._execution_future.cancel()
            self._execution_future = None

    def evaluate_registry(self) -> None:
        """Evaluate asynchronously, deferring execution until functions are applied."""
        if self._closed:
            return

        self._invalidate_evaluation()
        self._invalidate_execution()
        self._evaluation_pending = True
        evaluation_id = self._evaluation_id

        try:
            future = self._backend.evaluate(self.registry.get_script(), name="<registry>")
        except Exception as error:
            future = Future()
            future.set_exception(error)
        self._evaluation_future = future

        def on_done(completed: Future[dict[str, Callable[..., Any]]]) -> None:
            self._evaluation_finished.emit(evaluation_id, completed)

        future.add_done_callback(on_done)

    @Slot(int, object)
    def _on_evaluation_finished(
        self,
        evaluation_id: int,
        future: Future[dict[str, Callable[..., Any]]],
    ) -> None:
        if self._closed or evaluation_id != self._evaluation_id:
            return

        self._evaluation_future = None
        if future.cancelled():
            self._evaluation_pending = False
            self._pending_targets.clear()
            return

        try:
            functions = future.result()
        except Exception as error:
            self.registry._apply_functions({}, error)
            if self._closed or evaluation_id != self._evaluation_id:
                return
            self._invalidate_descendants(self.graph.nodes())
            if self._closed or evaluation_id != self._evaluation_id:
                return
            self._evaluation_pending = False
            self._pending_targets.clear()
            self.registry_failed.emit(error)
            return

        # Applying functions emits operator changes. Keep collecting their
        # execution targets until every binding has been updated.
        self.registry._apply_functions(functions, "VALID")
        if self._closed or evaluation_id != self._evaluation_id:
            return
        self.registry_evaluated.emit()
        if self._closed or evaluation_id != self._evaluation_id:
            return

        self._evaluation_pending = False
        targets = tuple(self._pending_targets)
        self._pending_targets.clear()
        if targets:
            self.execute_nodes(*targets)

    def execute_nodes(self, *targets: NodeRef) -> None:
        if self._closed or not targets:
            return

        # Supersede the previous request even if preparing this one fails.
        self._invalidate_execution()
        if self._evaluation_pending:
            self._pending_targets.update(targets)
            return

        execution_id = self._execution_id

        try:
            plan, mapping = prepare(self.graph, targets)
            # Workers use captured callables, never the live GUI registry.
            for name, snapshot in plan.items():
                if isinstance(snapshot.operator, ScriptOperatorRef):
                    plan[name] = replace(snapshot, operator=snapshot.operator.resolve())
            future = self._backend.execute_plan(plan)
        except Exception as error:
            self.execution_failed.emit(error)
            return
        self._execution_future = future

        def on_done(completed: Future[dict[str, Any]]) -> None:
            # This callback only sends a notification across threads.
            self._execution_finished.emit(execution_id, mapping, completed)

        future.add_done_callback(on_done)

    @Slot(int, object, object)
    def _on_execution_finished(
        self,
        execution_id: int,
        mapping: dict[str, NodeRef],
        future: Future[dict[str, Any]],
    ) -> None:
        # This check runs on the GUI thread, immediately before publication.
        if self._closed or execution_id != self._execution_id:
            return

        self._execution_future = None
        if future.cancelled():
            return

        try:
            plan_outputs = future.result()
        except Exception as error:
            self.execution_failed.emit(error)
        else:
            outputs = {
                mapping[name]: value
                for name, value in plan_outputs.items()
            }
            self.nodes_executed.emit(outputs)

    def _prune_auto_execution_targets(self, nodes: list[NodeRef]) -> None:
        self._pending_targets.difference_update(nodes)
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
            # A source edit also supersedes manual evaluation already in flight.
            self._invalidate_evaluation()
            self._invalidate_execution()
            self._pending_targets.clear()
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
        self._invalidate_evaluation()
        self._invalidate_execution()
        self._pending_targets.clear()
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self._backend.close()
