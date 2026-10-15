"""Run captured execution plans using a Qt thread pool."""

from concurrent.futures import Future

from qtpy.QtCore import QRunnable, QThreadPool

from . import execution_plan
from .execution_plan import ExecutionPlan, ExecutionResults


class _ExecutionJob(QRunnable):
    def __init__(
        self,
        plan: ExecutionPlan,
        future: Future[ExecutionResults],
    ) -> None:
        super().__init__()
        self._plan = plan
        self._future = future

    def run(self) -> None:
        if not self._future.set_running_or_notify_cancel():
            return

        try:
            results = execution_plan.execute(self._plan)
        except BaseException as error:
            self._future.set_exception(error)
        else:
            self._future.set_result(results)


class QtThreadPoolExecutionBackend:
    """Submit independent plans to an injected or global Qt thread pool.

    Call ``submit`` and ``close`` on the owning thread. Futures usually finish
    on pool threads; their callbacks must arrange any required thread handoff.
    Cancelling a future before its job starts skips execution. Running Python
    code is not interrupted.

    The pool may be shared with other backends. ``close`` only rejects future
    submissions: it never clears, shuts down, or waits for that pool. Already
    submitted work may finish after this backend is closed.
    """

    def __init__(self, pool: QThreadPool | None = None) -> None:
        self._pool = pool if pool is not None else QThreadPool.globalInstance()
        self._closed = False

    def submit(self, plan: ExecutionPlan) -> Future[ExecutionResults]:
        if self._closed:
            raise RuntimeError("The execution backend is closed.")

        future: Future[ExecutionResults] = Future()
        job = _ExecutionJob(plan, future)
        self._pool.start(job)
        return future

    def close(self) -> None:
        self._closed = True
