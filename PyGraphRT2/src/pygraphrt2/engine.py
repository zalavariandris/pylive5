from concurrent.futures import Future
from dataclasses import replace
from typing import Any, Callable, Iterable
from pygraphrt2.threaded_backend import ThreadedBackend


from qtpy.QtCore import Qt, QObject, Signal, Slot

from .graph import Graph, NodeRef
from .inline_scriptmodule import InlineScriptModule, ScriptOperatorRef
from .relations import ManyToOneRelation

from .execution_plan import prepare
from .execution_plan import NodeExecutionError
from .exceptions import ExecutionFailure
from .graph_cache import GraphCache


class Engine(QObject):
    script_changed = Signal(str)

    operators_added = Signal(list)
    operators_removed = Signal(list)
    operators_changed = Signal(list)
    nodes_added = Signal(list)
    nodes_removed = Signal(list)
    nodes_changed = Signal(list)

    nodes_invalidated = Signal(list)
    evaluation_pending_changed = Signal()
    execution_pending_changed = Signal()
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
        self._registry = registry if registry is not None else InlineScriptModule()
        self._graph = graph if graph is not None else Graph()
        

        self._backend = ThreadedBackend(self._graph)
        self._cache = GraphCache()
        self._closed = False
        self._evaluation_id = 0
        self._evaluation_pending = False
        self._evaluation_future: Future[dict[str, Callable[..., Any]]] | None = None
        self._pending_targets: set[NodeRef] = set()
        self._execution_id = 0
        self._execution_future: Future[dict[str, Any]] | None = None
        self._executing_nodes: set[NodeRef] = set()
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
        self._sync_node_operator_mappings(self._graph.nodes())
        self._connections = [
            (self._graph.nodes_added, self._on_nodes_changed),
            (self._graph.nodes_changed, self._on_nodes_changed),
            (self._graph.nodes_removed, self._remove_node_operator_mappings),
            (self._graph.nodes_removed, self._prune_auto_execution_targets),
            (self._registry.registry_invalidated, self.registry_invalidated.emit),
            (self._registry.registry_invalidated, self._auto_evaluate_registry),
            (self._registry.operators_added, self._on_operators_added),
            (self._registry.operators_removed, self._on_operators_removed),
            (self._registry.operators_changed, self._on_operators_changed),
        ]
        self._connections.extend([
            (self._graph.nodes_added, self.nodes_added.emit),
            (self._graph.nodes_changed, self.nodes_changed.emit),
            (self._graph.nodes_removed, self.nodes_removed.emit),
            (self._registry.operators_added, self.operators_added.emit),
            (self._registry.operators_removed, self.operators_removed.emit),
            (self._registry.operators_changed, self.operators_changed.emit)
        ])
        for signal, slot in self._connections:
            signal.connect(slot)

        # auto evaluate and execution flags
        self._auto_execute = True
        self._auto_execute_targets: set[NodeRef] | None = None

    def evaluation_pending(self) -> bool:
        """Whether script evaluation is queued, running, or being applied."""
        return self._evaluation_pending

    def pending_nodes(self) -> frozenset[NodeRef]:
        """Snapshot of requested work, including targets waiting for evaluation."""
        return frozenset(self._executing_nodes | self._pending_targets)

    def set_script(self, script:str):
        self._registry.set_script(script)
        self.script_changed.emit(script)

    def get_script(self) -> str:
        return self._registry.get_script()

    def operators(self) -> list[ScriptOperatorRef]:
        return self._registry.operators()

    def get_operator_by_name(self, name: str) -> ScriptOperatorRef | None:
        return self._registry.get_operator_by_name(name)

    def nodes(self) -> list[NodeRef]:
        return self._graph.nodes()

    def add_node(self, operator: ScriptOperatorRef, *args, **kwargs):
        return self._graph.add_node(operator, *args, **kwargs)

    def remove_node(self, node: NodeRef) -> None:
        self._graph.remove_node(node)

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
                    self._graph._update_node(
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
                if state.operator is binding:
                    # Loading resolves an existing binding without editing the graph.
                    self._invalidate_descendants([node])
                    continue
                self._graph._update_node(
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
        self._cache.invalidate(nodes)
        for node in nodes:
            operator = self._operator_to_nodes.parent_of(node)
            if operator is not None:
                self._operator_to_nodes.delete(node, operator)

    def _invalidate_descendants(self, nodes: list[NodeRef]) -> None:
        affected: set[NodeRef] = set()
        for node in nodes:
            affected.update(self._graph.descendants(node))

        invalidated = [
            node for node in self._graph.nodes()
            if node in affected
        ]

        if not invalidated:
            return

        self._cache.invalidate(invalidated)
        self._invalidate_execution()
        self.nodes_invalidated.emit(invalidated)
        self._auto_execute_invalidated(invalidated)
 
    # Execution backend
    def _invalidate_evaluation(self) -> None:
        self._evaluation_id += 1
        self._evaluation_pending = False
        if self._evaluation_future is not None:
            self._evaluation_future.cancel()
            self._evaluation_future = None

    def _invalidate_execution(self) -> int:
        self._execution_id += 1
        execution_id = self._execution_id
        had_pending_execution = bool(self._executing_nodes)
        if self._execution_future is not None:
            self._execution_future.cancel()
            self._execution_future = None
        self._executing_nodes.clear()
        if had_pending_execution:
            self.execution_pending_changed.emit()
        return execution_id

    def evaluate_registry(self) -> None:
        """Evaluate asynchronously, deferring execution until functions are applied."""
        if self._closed:
            return

        self._invalidate_evaluation()
        self._evaluation_pending = True
        evaluation_id = self._evaluation_id
        self._invalidate_execution()
        self.evaluation_pending_changed.emit()
        if self._closed or evaluation_id != self._evaluation_id:
            return

        try:
            future = self._backend.evaluate(self._registry.get_script(), name="<registry>")
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
            self.evaluation_pending_changed.emit()
            self.execution_pending_changed.emit()
            return

        try:
            functions = future.result()
        except Exception as error:
            self._registry._apply_functions({}, error)
            if self._closed or evaluation_id != self._evaluation_id:
                return
            self._invalidate_descendants(self._graph.nodes())
            if self._closed or evaluation_id != self._evaluation_id:
                return
            self._evaluation_pending = False
            self._pending_targets.clear()
            self.evaluation_pending_changed.emit()
            self.execution_pending_changed.emit()
            if self._closed or evaluation_id != self._evaluation_id:
                return
            self.registry_failed.emit(error)
            return

        # Applying functions emits operator changes. Keep collecting their
        # execution targets until every binding has been updated.
        self._registry._apply_functions(functions, "VALID")
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
        if not self._closed and evaluation_id == self._evaluation_id:
            self.evaluation_pending_changed.emit()
            self.execution_pending_changed.emit()

    def execute_nodes(self, *targets: NodeRef) -> None:
        if self._closed or not targets:
            return

        # Supersede the previous request even if preparing this one fails.
        execution_id = self._invalidate_execution()
        if self._closed or execution_id != self._execution_id:
            return
        if self._evaluation_pending:
            self._pending_targets.update(targets)
            self.execution_pending_changed.emit()
            return

        try:
            plan, mapping, initial_outputs = prepare(
                self._graph, 
                targets,
                cached_outputs=self._cache
            )
            # Workers use captured callables, never the live GUI registry.
            for name, snapshot in plan.items():
                if isinstance(snapshot.operator, ScriptOperatorRef):
                    try:
                        operator = snapshot.operator.resolve()
                    except Exception as error:
                        raise ExecutionFailure(mapping[name], error, targets) from error
                    plan[name] = replace(snapshot, operator=operator)
            self._executing_nodes = {mapping[name] for name in plan}
            future = self._backend.execute_plan(plan, initial_outputs=initial_outputs)
        except Exception as error:
            self._executing_nodes.clear()
            self.execution_pending_changed.emit()
            if not self._closed and execution_id == self._execution_id:
                failure = error if isinstance(error, ExecutionFailure) else ExecutionFailure(None, error, targets)
                self.execution_failed.emit(failure)
            return
        self._execution_future = future

        def on_done(completed: Future[dict[str, Any]]) -> None:
            # This callback only sends a notification across threads.
            self._execution_finished.emit(execution_id, mapping, completed)

        future.add_done_callback(on_done)
        if self._executing_nodes:
            self.execution_pending_changed.emit()

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
        executing_nodes = self._executing_nodes
        self._executing_nodes = set()
        if future.cancelled():
            self.execution_pending_changed.emit()
            return

        try:
            plan_outputs = future.result()
        except NodeExecutionError as error:
            node = mapping[error.node_name]
            failure = ExecutionFailure(node, error.error)
            self.execution_pending_changed.emit()
            if not self._closed and execution_id == self._execution_id:
                self.execution_failed.emit(failure)
        except Exception as error:
            self.execution_pending_changed.emit()
            if not self._closed and execution_id == self._execution_id:
                self.execution_failed.emit(ExecutionFailure(None, error, tuple(executing_nodes)))
        else:
            outputs = {
                mapping[name]: value
                for name, value in plan_outputs.items()
            }
            for node, value in outputs.items():
                self._cache.save(node, value)
            if executing_nodes:
                self.execution_pending_changed.emit()
            if not self._closed and execution_id == self._execution_id:
                self.nodes_executed.emit(outputs)

    def _prune_auto_execution_targets(self, nodes: list[NodeRef]) -> None:
        had_pending_targets = bool(self._pending_targets.intersection(nodes))
        self._pending_targets.difference_update(nodes)
        if self._auto_execute_targets is not None:
            self._auto_execute_targets.difference_update(nodes)
        if had_pending_targets:
            self.execution_pending_changed.emit()

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
            node for node in self._graph.nodes()
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
            self._pending_targets.clear()
            self._invalidate_execution()
            self.evaluation_pending_changed.emit()
            self.execution_pending_changed.emit()
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
        self._pending_targets.clear()
        self._invalidate_execution()
        self.evaluation_pending_changed.emit()
        self.execution_pending_changed.emit()
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self._backend.close()
