"""Coordinate graph evaluation using an injected plan execution backend."""

from collections.abc import Iterable
from concurrent.futures import Future
from weakref import ref

from .qtthreadpool_execution_backend import QtThreadPoolExecutionBackend
from qtpy.QtCore import QObject, Qt, Signal, Slot

from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .core import (
    ExecutionBlocked,
    ExecutionFailure,
    ExecutionSuccess,
    NodeExecution,
)
from .graph_invalidator import GraphInvalidator
from .execution_backend_protocol import ExecutionBackend
from . import execution_plan
from .execution_plan import ExecutionPlan, ExecutionResults
from .graph_cache import GraphCache
from .module_registry import ModuleRegistry


class GraphEngine(QObject):
    """Manage requests, cached results, and invalidation around an execution backend.

    Construct and use this object on the graph's owning thread. Requests are
    queued and coalesced, including for backends that compute synchronously.
    One plan runs at a time. Invalidation evicts outputs and makes in-flight
    work obsolete; pending requests survive until current results are accepted.

    Pass the graph's existing invalidator to observe registered module edits
    as well as graph edits. The default invalidator observes graph edits only.
    Invalidation does not request new work: connect the invalidator to request()
    as well if automatic reevaluation is desired.

    Dedicate the backend and cache to this evaluator. close() closes the backend
    without waiting for running work. A supplied cache must contain only valid
    outputs for this graph. Use invalidate() or clear_cache() to evict values so
    obsolete jobs cannot restore them.
    """

    evaluated = Signal(dict)  # Accepted dict[NodeRef, NodeExecution], including hits.
    _start_requested = Signal()
    _backend_finished = Signal(object, object)  # plan, Future[ExecutionResults]

    def __init__(
        self,
        graph: GraphDefinitionRT|None=None,
        registry: ModuleRegistry|None=None,
        backend: ExecutionBackend|None = None,
        parent: QObject | None = None,
        *,
        cache: GraphCache | None = None
    ) -> None:
        super().__init__(parent)
        self._graph = graph or GraphDefinitionRT(parent=self)
        self._registry = registry or ModuleRegistry(parent=self)
        self._backend = backend or QtThreadPoolExecutionBackend()
        self._cache = cache if cache is not None else GraphCache()

        #
        self._invalidator = GraphInvalidator(
            self._graph, 
            self._registry, 
            parent=self
        )

        self._revision = 0
        self._pending: set[NodeRef] = set()
        self._active_plan: ExecutionPlan | None = None
        self._starting = False
        self._start_queued = False
        self._closed = False

        self._start_requested.connect(
            self._start_next, Qt.ConnectionType.QueuedConnection
        )
        self._backend_finished.connect(
            self._on_backend_finished, Qt.ConnectionType.QueuedConnection
        )
        self._invalidator.nodes_invalidated.connect(self._on_nodes_invalidated)
        self._graph.nodes_removed.connect(self._on_nodes_removed)

    def graph(self) -> GraphDefinitionRT:
        return self._graph

    def request_node(self, *targets: NodeRef) -> None:
        """Request outputs asynchronously, reusing valid cached values.

        Requesting again does not invalidate values or obsolete a running plan.
        Duplicate requests may be satisfied by the same result notification.
        """
        self._ensure_open()
        self._validate_nodes(targets)
        self._pending.update(targets)
        self._schedule()

    def invalidate_node(self, *roots: NodeRef) -> None:
        """Invalidate roots and their descendants without requesting new work.

        Use this for external changes that the graph invalidator cannot observe.
        Already pending requests will retry if their active plan becomes stale.
        """
        self._ensure_open()
        self._validate_nodes(roots)
        affected: set[NodeRef] = set()
        for node in roots:
            affected.update(self._graph.descendants(node))
        self._invalidate_nodes(affected)

    def clear_node_cache(self) -> None:
        """Forget every output and obsolete in-flight work, without new requests."""
        self._ensure_open()
        self._revision += 1
        self._cache.clear()
        self._schedule()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("The graph evaluator is closed.")

    def _validate_nodes(self, nodes: Iterable[NodeRef]) -> None:
        existing = set(self._graph.nodes())
        if any(node not in existing for node in nodes):
            raise ValueError("Requested nodes must belong to this graph.")

    def _invalidate_nodes(self, nodes: Iterable[NodeRef]) -> None:
        affected = tuple(nodes)
        if not affected:
            return
        self._revision += 1
        self._cache.invalidate(affected)
        self._schedule()

    @Slot(list)
    def _on_nodes_invalidated(self, nodes: list[NodeRef]) -> None:
        if not self._closed:
            # GraphInvalidator already includes all affected descendants.
            self._invalidate_nodes(nodes)

    @Slot(list)
    def _on_nodes_removed(self, nodes: list[NodeRef]) -> None:
        if self._closed:
            return
        self._pending.difference_update(nodes)
        self._invalidate_nodes(nodes)

    def _schedule(self) -> None:
        """Schedule the next evaluation if conditions allow."""
        if (
            not self._closed
            and self._active_plan is None
            and not self._starting
            and self._pending
            and not self._start_queued
        ):
            self._start_queued = True
            self._start_requested.emit()

    @Slot()
    def _start_next(self) -> None:
        self._start_queued = False
        if self._closed or self._active_plan is not None or self._starting:
            return

        self._starting = True
        try:
            self._prepare_and_submit()
        finally:
            self._starting = False
            self._schedule()

    def _prepare_and_submit(self) -> None:
        """Prepare one request batch while nested event processing is guarded."""

        existing = self._graph.nodes()
        self._pending.intersection_update(existing)
        targets = tuple(node for node in existing if node in self._pending)
        if not targets:
            return

        revision = self._revision
        try:
            plan = execution_plan.prepare(
                self._graph,
                targets,
                revision=revision,
                cached_outputs=self._cache,
            )
        except Exception as error:
            if revision == self._revision and not self._closed:
                self._pending.difference_update(targets)
                self.evaluated.emit({
                    node: ExecutionFailure(node, error) for node in targets
                })
            return

        # Custom input copying may have caused a reentrant graph edit or close.
        if self._closed or revision != self._revision:
            return

        # A backend may return an already completed future.
        self._active_plan = plan
        if not plan.nodes:
            self._accept_results(plan, ExecutionResults())
            return

        try:
            future = self._backend.submit(plan)
        except BaseException as error:
            self._accept_results(plan, execution_plan.plan_failure(plan, error))
            return

        evaluator_ref = ref(self)

        def notify_finished(completed: Future[ExecutionResults]) -> None:
            # Future callbacks may run on a worker. Only signal emission crosses
            # the thread boundary; graph and cache access stay on the owner.
            evaluator = evaluator_ref()
            if evaluator is None:
                return
            try:
                evaluator._backend_finished.emit(plan, completed)
            except RuntimeError:
                # Its QObject parent may have deleted the evaluator meanwhile.
                return

        future.add_done_callback(notify_finished)

    @Slot(object, object)
    def _on_backend_finished(
        self, plan: ExecutionPlan, future: Future[ExecutionResults]
    ) -> None:
        if self._closed or plan is not self._active_plan:
            return
        try:
            results = future.result()
        except BaseException as error:
            # Includes infrastructure failures and a cancelled submission.
            results = execution_plan.plan_failure(plan, error)
        self._accept_results(plan, results)

    def _accept_results(self, plan: ExecutionPlan, results: ExecutionResults) -> None:
        """Accept current outcomes, update the cache, then notify observers."""
        if plan is not self._active_plan:
            return
        self._active_plan = None
        if self._closed:
            return
        if plan.revision != self._revision:
            # Leave every pending target intact, including other branches.
            self._schedule()
            return

        target_names = set(plan.targets)
        self._pending.difference_update(
            node for node in tuple(self._pending)
            if node.get_name() in target_names
        )
        nodes_by_name = {node.get_name(): node for node in self._graph.nodes()}
        executions: dict[NodeRef, NodeExecution] = {}

        for name, output in plan.initial_outputs.items():
            node = nodes_by_name[name]
            executions[node] = ExecutionSuccess(
                node,
                output,
                duration_seconds=self._cache.duration_seconds(node),
                cached=True,
            )
        for name, output in results.outputs.items():
            node = nodes_by_name[name]
            duration_seconds = results.durations_seconds.get(name)
            self._cache.save(node, output, duration_seconds=duration_seconds)
            executions[node] = ExecutionSuccess(
                node,
                output,
                duration_seconds=duration_seconds,
            )
        for name, error in results.failures.items():
            node = nodes_by_name[name]
            executions[node] = ExecutionFailure(node, error)
        for name, dependencies in results.blocked.items():
            node = nodes_by_name[name]
            executions[node] = ExecutionBlocked(
                node,
                frozenset(nodes_by_name[dependency] for dependency in dependencies),
            )

        # Observers can request again; the accepted values are already cached.
        self.evaluated.emit(executions)
        self._schedule()

    def close(self) -> None:
        """Stop scheduling and publishing, without waiting for a running job.

        Close the dedicated backend too; already submitted jobs may finish.
        The cache remains available for inspection but is no longer kept current.
        """
        if self._closed:
            return
        self._closed = True
        self._revision += 1
        self._pending.clear()
        self._active_plan = None
        self._backend.close()