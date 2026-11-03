from concurrent.futures import Future
from dataclasses import replace
import logging
from typing import Any, Callable, Iterable, Mapping
from pygraphrt2.threaded_backend import ThreadedBackend


# class ContextOperator:
#     def __init__(self, *args, **kwargs) -> None:
#         ...

#     def compute(self, ctx):
#         ...

# @graph.node(...)
# def blur(img, radius):
#     @graph.context(ctx)
#     def compute(self, ctx):
#         ...

#     return compute


from qtpy.QtCore import Qt, QObject, QTimer, Signal, Slot

from .graph import Graph, NodeRef
from .inline_scriptmodule import InlineScriptModule, ScriptOperatorRef
from .relations import ManyToOneRelation

from .execution_plan import prepare
from .execution_plan import ContextKey, ExecutionResult, NodeExecutionError
from .exceptions import ExecutionFailure
from .graph_cache import GraphCache

logger = logging.getLogger(__name__)


class Subscription:
    """One registration, independent of other registrations of the same callback."""

    def __init__(
        self, engine: "Engine", node: NodeRef, callback: Callable[[Any], None],
    ) -> None:
        self._engine: Engine | None = engine
        self._node = node
        self._callback: Callable[[Any], None] | None = callback

    @property
    def node(self) -> NodeRef:
        return self._node

    @property
    def active(self) -> bool:
        return self._engine is not None

    def unsubscribe(self) -> None:
        """Release this registration; repeated calls are harmless."""
        if self._engine is not None:
            self._engine._unsubscribe(self)


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
    _context_state_changed = Signal(int, object, bool)

    def __init__(
        self, 
        graph: Graph | None = None, 
        registry: InlineScriptModule | None = None,
        backend: ThreadedBackend | None = None,
    ) -> None:
        super().__init__()
        self._registry = registry if registry is not None else InlineScriptModule()
        self._graph = graph if graph is not None else Graph()

        self._backend = backend if backend is not None else ThreadedBackend(self._graph)
        self._cache = GraphCache()
        self._closed = False
        self._evaluation_id = 0
        self._evaluation_pending = False
        self._evaluation_future: Future[dict[str, Callable[..., Any]]] | None = None
        self._pending_targets: set[NodeRef] = set()
        self._execution_id = 0
        self._execution_future: Future[ExecutionResult] | None = None
        self._executing_nodes: set[NodeRef] = set()
        self._contextual_counts: dict[NodeRef, int] = {}
        self._auto_execute = True
        self._subscriptions: dict[NodeRef, list[Subscription]] = {}
        self._pending_notifications: set[Subscription] = set()
        self._subscription_timer = QTimer(self)
        self._subscription_timer.setSingleShot(True)
        self._subscription_timer.timeout.connect(self._execute_subscriptions)
        self._evaluation_finished.connect(
            self._on_evaluation_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._execution_finished.connect(
            self._on_execution_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._context_state_changed.connect(
            self._on_context_state_changed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._operator_to_nodes = ManyToOneRelation[NodeRef, ScriptOperatorRef]()
        self._preserve_operator_bindings: set[NodeRef] = set()
        self._sync_node_operator_mappings(self._graph.nodes())
        self._connections = [
            (self._graph.nodes_added, self._on_nodes_changed),
            (self._graph.nodes_changed, self._on_nodes_changed),
            (self._graph.nodes_removed, self._remove_node_operator_mappings),
            (self._graph.nodes_removed, self._prune_subscriptions),
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

    def evaluation_pending(self) -> bool:
        """Whether script evaluation is queued, running, or being applied."""
        return self._evaluation_pending

    def pending_nodes(self) -> frozenset[NodeRef]:
        """Snapshot of requested work, including targets waiting for evaluation."""
        pending = self._executing_nodes | self._pending_targets
        pending.update(self._contextual_counts)
        if self._evaluation_pending or self._subscription_timer.isActive():
            pending.update(node for node in self._subscription_targets() if node not in self._cache)
        return frozenset(pending)

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

    def add_node(
        self,
        operator: Callable[..., Any] | None,
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        *,
        name: str | None = None,
    ) -> NodeRef:
        return self._graph._create_node(
            operator, args, kwargs if kwargs is not None else {}, name=name,
        )

    def remove_node(self, node: NodeRef) -> None:
        self._graph._delete_node(node)

    def _on_operators_changed(self, operators: list[ScriptOperatorRef]) -> None:
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
        self._schedule_subscriptions()
 
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
        had_pending_execution = bool(self._executing_nodes or self._contextual_counts)
        if self._execution_future is not None:
            self._execution_future.cancel()
            self._execution_future = None
        self._executing_nodes.clear()
        self._contextual_counts.clear()
        if had_pending_execution:
            self.execution_pending_changed.emit()
        return execution_id

    def evaluate_registry(self) -> None:
        """Evaluate asynchronously, deferring execution until functions are applied."""
        if self._closed:
            return

        self._invalidate_evaluation()
        self._evaluation_pending = True
        self._subscription_timer.stop()
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

        # Applying functions emits operator changes. Subscription demand is
        # collected only after every binding has been updated.
        self._registry._apply_functions(functions, "VALID")
        if self._closed or evaluation_id != self._evaluation_id:
            return
        self.registry_evaluated.emit()
        if self._closed or evaluation_id != self._evaluation_id:
            return

        self._evaluation_pending = False
        targets = tuple(dict.fromkeys((*self._pending_targets, *self._subscription_targets())))
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
            # Only explicit requests are retained here. Automatic demand is
            # derived from live subscriptions when evaluation completes.
            self._pending_targets.update(targets)
            self.execution_pending_changed.emit()
            return

        self._subscription_timer.stop()
        targets = tuple(dict.fromkeys((*targets, *self._subscription_targets())))
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
                        operator:Callable = snapshot.operator.resolve()
                    except Exception as error:
                        raise ExecutionFailure(mapping[name], error, targets) from error
                    plan[name] = replace(
                        snapshot,
                        operator=operator
                    )
            self._executing_nodes = {mapping[name] for name in plan}

            # Cached contextual callables can request ancestors outside the plan.
            mapping.update({
                node.name(): node
                for node in self._graph.ancestors(*targets)
            })

            initial_contextual_outputs = {
                (node.name(), context): value
                for (node, context), value
                in self._cache.contextual_outputs().items()
                if node.name() in mapping
            }

            def on_context_state_changed(key: ContextKey, running: bool) -> None:
                # Only the queued Qt slot mutates execution state.
                self._context_state_changed.emit(execution_id, mapping[key[0]], running)

            future = self._backend.execute_plan(
                plan,
                initial_outputs=initial_outputs,
                initial_contextual_outputs=initial_contextual_outputs,
                on_context_state_changed=on_context_state_changed,
            )
        except Exception as error:
            self._executing_nodes.clear()
            self.execution_pending_changed.emit()
            if not self._closed and execution_id == self._execution_id:
                failure = error if isinstance(error, ExecutionFailure) else ExecutionFailure(None, error, targets)
                self.execution_failed.emit(failure)
            return
        self._execution_future = future

        def on_done(completed: Future[ExecutionResult]) -> None:
            # This callback only sends a notification across threads.
            self._execution_finished.emit(execution_id, mapping, completed)

        future.add_done_callback(on_done)
        if self._executing_nodes:
            self.execution_pending_changed.emit()

    @Slot(int, object, bool)
    def _on_context_state_changed(
        self, execution_id: int, node: NodeRef, running: bool,
    ) -> None:
        if self._closed or execution_id != self._execution_id:
            return

        # One node may have nested contextual computations in progress.
        was_running = node in self._contextual_counts
        count = self._contextual_counts.get(node, 0) + (1 if running else -1)
        if count > 0:
            self._contextual_counts[node] = count
        else:
            self._contextual_counts.pop(node, None)

        if was_running != (count > 0):
            self.execution_pending_changed.emit()

    @Slot(int, object, object)
    def _on_execution_finished(
        self,
        execution_id: int,
        mapping: dict[str, NodeRef],
        future: Future[ExecutionResult],
    ) -> None:
        # This check runs on the GUI thread, immediately before publication.
        if self._closed or execution_id != self._execution_id:
            return

        self._execution_future = None
        had_pending_execution = bool(self._executing_nodes or self._contextual_counts)
        executing_nodes = self._executing_nodes
        self._executing_nodes = set()
        self._contextual_counts.clear()
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
                for name, value in plan_outputs.outputs.items()
            }

            for node, value in outputs.items():
                self._cache.save(node, value)

            for (name, context), value in plan_outputs.contextual_outputs.items():
                self._cache.save_context(mapping[name], context, value)

            subscriptions = [
                subscription
                for node in outputs
                for subscription in self._subscriptions.get(node, ())
                if node in executing_nodes or subscription in self._pending_notifications
            ]
            # A callback may edit an unrelated node and supersede publication.
            # Keep undelivered notifications eligible for a cached replay.
            self._pending_notifications.update(subscriptions)
            if had_pending_execution:
                self.execution_pending_changed.emit()
            if not self._closed and execution_id == self._execution_id:
                self.nodes_executed.emit(outputs)
                for subscription in subscriptions:
                    if self._closed or execution_id != self._execution_id:
                        break
                    callback = subscription._callback
                    if callback is None:
                        continue
                    self._pending_notifications.discard(subscription)
                    try:
                        callback(outputs[subscription.node])
                    except Exception:
                        logger.exception("Subscription callback failed for %s", subscription.node)

    def _prune_subscriptions(self, nodes: list[NodeRef]) -> None:
        self._pending_targets.difference_update(nodes)
        for node in nodes:
            for subscription in tuple(self._subscriptions.get(node, ())):
                subscription.unsubscribe()
        self.execution_pending_changed.emit()
        # Removing a node also supersedes work on surviving subscriptions.
        self._schedule_subscriptions()

    def subscribe(self, node: NodeRef, callback: Callable[[Any], None]) -> Subscription:
        """Watch a node and queue its initial result when auto-execution is enabled.

        Callbacks receive the node's output on the engine's Qt thread, after
        the cache and nodes_executed observers have been updated. Values are
        borrowed from the cache, including None; do not mutate them. Later
        notifications follow recomputation; cached dependencies are not repeated.
        """
        if self._closed:
            raise RuntimeError("Engine is closed")
        if node not in self._graph.nodes():
            raise ValueError(f"Node {node} is not in the graph")
        if not callable(callback):
            raise TypeError("Subscription callback must be callable")
        subscription = Subscription(self, node, callback)
        self._subscriptions.setdefault(node, []).append(subscription)
        self._pending_notifications.add(subscription)
        self._schedule_subscriptions()
        return subscription

    def _unsubscribe(self, subscription: Subscription) -> None:
        subscriptions = self._subscriptions.get(subscription.node)
        if subscriptions is not None and subscription in subscriptions:
            subscriptions.remove(subscription)
            if not subscriptions:
                del self._subscriptions[subscription.node]
        self._pending_notifications.discard(subscription)
        subscription._engine = None
        subscription._callback = None
        self.execution_pending_changed.emit()

    def unsubscribe(self, node: NodeRef, callback: Callable[[Any], None]) -> None:
        """Remove the first matching registration; handles identify exact registrations."""
        for subscription in tuple(self._subscriptions.get(node, ())):
            if subscription._callback == callback:
                subscription.unsubscribe()
                break

    def auto_execute(self) -> bool:
        return self._auto_execute

    def set_auto_execute(self, value: bool) -> None:
        """Toggle automatic execution, refreshing watched nodes when enabled."""
        if self._auto_execute == value:
            return

        self._auto_execute = value
        if value:
            self.evaluate_registry()
        else:
            self._subscription_timer.stop()
            self.execution_pending_changed.emit()

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

    def _subscription_targets(self) -> tuple[NodeRef, ...]:
        if self._closed or not self._auto_execute:
            return ()
        return tuple(
            node for node, subscriptions in self._subscriptions.items()
            if node not in self._cache
            or any(subscription in self._pending_notifications for subscription in subscriptions)
        )

    def _schedule_subscriptions(self) -> None:
        if self._closed or not self._auto_execute:
            return
        if not self._evaluation_pending and self._subscription_targets():
            self._subscription_timer.start(0)
        self.execution_pending_changed.emit()

    def _execute_subscriptions(self) -> None:
        if self._evaluation_pending:
            return
        targets = self._subscription_targets()
        if targets:
            # A new subscriber must not discard unrelated manual work in flight.
            self.execute_nodes(*targets, *self._executing_nodes)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._subscription_timer.stop()
        for subscriptions in tuple(self._subscriptions.values()):
            for subscription in tuple(subscriptions):
                subscription.unsubscribe()
        self._invalidate_evaluation()
        self._pending_targets.clear()
        self._invalidate_execution()
        self.evaluation_pending_changed.emit()
        self.execution_pending_changed.emit()
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self._backend.close()
