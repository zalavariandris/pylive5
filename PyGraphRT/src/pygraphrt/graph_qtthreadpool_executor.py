"""Execute captured graph plans on Qt's thread pool without polling."""

from qtpy.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot

from . import execution_plan
from .execution_plan import ExecutionPlan, ExecutionResults
from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .graph_executor import (
    ExecutionBlocked,
    ExecutionFailure,
    ExecutionSuccess,
    NodeExecution,
)


class _JobSignals(QObject):
    finished = Signal(object, object)  # plan, results


class _ExecutionJob(QRunnable):
    """Evaluate one captured plan; only run() executes on a worker thread."""

    def __init__(self, plan: ExecutionPlan) -> None:
        super().__init__()
        self.plan = plan
        # The runnable owns this unparented emitter so it can outlive the executor.
        self.signals = _JobSignals()

    def run(self) -> None:
        # print("Executing plan")
        print("Executing Plan...")
        try:
            results = execution_plan.execute(self.plan)
        except BaseException as error:
            # Even an unexpected plan-level failure must release the running job.
            results = ExecutionResults(
                failures={node.name: error for node in self.plan.nodes}
            )
        self.signals.finished.emit(self.plan, results)
        print("Finished executing plan.")


class GraphQtThreadPoolExecutorRT(QObject):
    """Prepare plans on the GUI thread and submit one execution job at a time.

    Call request() for invalidated nodes, including downstream nodes. Requests
    accumulate until a current execution finishes; obsolete results are ignored.
    Preparation and completion are dispatched through queued signals, not timers.

    Create and use this object on the graph's GUI thread. Results map NodeRef
    objects to NodeExecution objects, matching GraphExecutorRT.executed.
    Worker outcomes are converted on the GUI thread. Preparation failures are
    reported as ExecutionFailure for each requested target. No cache is added here.
    """

    executed = Signal(dict)  # dict[NodeRef, NodeExecution]
    _start_requested = Signal()

    def __init__(
        self,
        graph: GraphDefinitionRT,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._graph = graph
        self._pool = QThreadPool.globalInstance()
        self._revision = 0
        self._dirty: set[str] = set()
        self._job: _ExecutionJob | None = None
        self._start_queued = False
        self._closed = False

        self._start_requested.connect(
            self._start_next, Qt.ConnectionType.QueuedConnection
        )
        graph.nodes_removed.connect(self._on_nodes_removed)

    def request(self, *roots: NodeRef) -> None:
        """Request evaluation without waiting; an empty request does nothing."""
        if self._closed:
            raise RuntimeError("The graph executor is closed.")

        if not roots:
            return

        requested = tuple(roots)
        existing = set(self._graph.nodes())
        if any(node not in existing for node in requested):
            raise ValueError("Requested nodes must belong to this graph.")

        self._revision += 1
        self._dirty.update(node.get_name() for node in requested)
        self._schedule()

    def _schedule(self) -> None:
        if (
            not self._closed
            and self._job is None
            and self._dirty
            and not self._start_queued
        ):
            self._start_queued = True
            self._start_requested.emit()

    @Slot()
    def _start_next(self) -> None:
        self._start_queued = False
        if self._closed or self._job is not None:
            return

        targets = [
            node for node in self._graph.nodes()
            if node.get_name() in self._dirty
        ]
        self._dirty = {node.get_name() for node in targets}
        if not targets:
            return

        try:
            plan = execution_plan.prepare(
                self._graph, targets, revision=self._revision
            )
        except Exception as error:
            self._dirty.clear()
            self.executed.emit({
                node: ExecutionFailure(node, error) for node in targets
            })
            return

        job = _ExecutionJob(plan)
        job.signals.finished.connect(
            self._on_finished, Qt.ConnectionType.QueuedConnection
        )
        self._job = job
        self._pool.start(job)

    @Slot(object, object)
    def _on_finished(
        self,
        plan: ExecutionPlan,
        results: ExecutionResults,
    ) -> None:
        self._job = None
        if self._closed:
            return

        if plan.revision == self._revision:
            # Keep dirty nodes across obsolete jobs, including other branches.
            self._dirty.difference_update(plan.targets)
            nodes_by_name = {
                node.get_name(): node for node in self._graph.nodes()
            }
            executions: dict[NodeRef, NodeExecution] = {}
            for name, output in results.outputs.items():
                node = nodes_by_name.get(name)
                if node is not None:
                    executions[node] = ExecutionSuccess(node, output)
            for name, error in results.failures.items():
                node = nodes_by_name.get(name)
                if node is not None:
                    executions[node] = ExecutionFailure(node, error)
            for name, dependencies in results.blocked.items():
                node = nodes_by_name.get(name)
                if node is not None:
                    executions[node] = ExecutionBlocked(
                        node,
                        frozenset(
                            nodes_by_name[dependency] for dependency in dependencies
                        ),
                    )
            self.executed.emit(executions)

        self._schedule()

    @Slot(list)
    def _on_nodes_removed(self, nodes: list[NodeRef]) -> None:
        if self._closed:
            return
        self._revision += 1
        self._dirty.difference_update(node.get_name() for node in nodes)
        self._schedule()

    def close(self) -> None:
        """Stop scheduling and publishing results without waiting for the worker.

        An already running job finishes normally. The shared Qt pool may wait
        for it during application shutdown.
        """
        self._closed = True
        self._revision += 1
        self._dirty.clear()
