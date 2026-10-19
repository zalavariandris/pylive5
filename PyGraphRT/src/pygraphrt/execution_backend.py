"""Execution backends run captured plans without graph or cache lifecycle logic."""

from concurrent.futures import Future
from typing import Protocol

from . import execution_plan
from .execution_plan import ExecutionPlan, ExecutionResults


class ExecutionBackend(Protocol):
    """Dispatch plans and expose their completion through standard futures.

    Call ``submit`` and ``close`` on the backend's owning thread. A returned
    future may already be complete; its callbacks may also run on a worker
    thread. The caller is responsible for delivering outcomes to its own
    thread and deciding whether they remain valid.

    Per-node failures belong in ``ExecutionResults``. Failures of the backend
    itself may raise from ``submit`` or complete the future with an exception.
    Backends must reject new submissions after ``close``. Closing does not
    wait for submitted work and need not interrupt it.
    """

    def submit(self, plan: ExecutionPlan) -> Future[ExecutionResults]:
        """Execute a captured plan without consulting the live graph or cache."""
        ...

    def close(self) -> None:
        """Stop accepting plans; safe to call more than once."""
        ...


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
