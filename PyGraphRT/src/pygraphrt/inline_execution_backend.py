from concurrent.futures import Future
from qtpy.QtCore import QRunnable, QThreadPool
from . import execution_plan
from .execution_plan import ExecutionPlan, ExecutionResults

class InlineExecutionBackend:
    """Execute immediately on the caller's thread, returning a finished future.

    This backend uses the same completion contract as asynchronous backends.
    It is useful for small graphs and for inspecting execution without workers.
    """

    def __init__(self) -> None:
        self._closed = False

    def submit(self, plan: ExecutionPlan) -> Future[ExecutionResults]:
        if self._closed:
            raise RuntimeError("The execution backend is closed.")

        future: Future[ExecutionResults] = Future()
        future.set_running_or_notify_cancel()
        try:
            results = execution_plan.execute(plan)
        except BaseException as error:
            future.set_exception(error)
        else:
            future.set_result(results)
        return future

    def close(self) -> None:
        self._closed = True