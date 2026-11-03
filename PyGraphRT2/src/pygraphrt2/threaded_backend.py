from typing import Any, Callable

from .graph import Graph, NodeRef
from .execution_plan import (
    ContextKey, ContextStateCallback, ExecutionResult, NodeStateSnapshot, NodeOutput,
)
from concurrent.futures import Future, ThreadPoolExecutor
from .inline_scriptmodule import _get_all_callables_from_script

from .execution_plan import evaluate, prepare, execute


class ThreadedBackend:
    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="graph"
        )
        self._latest_future: Future[ExecutionResult] | None = None

    def evaluate(self, source:str, *, name: str="<script>") -> Future[dict[str, Callable[..., Any]]]:
        return self._executor.submit(evaluate, source, name=name)

    def execute_plan(
        self,
        plan: dict[str, NodeStateSnapshot],
        initial_outputs: dict[str, Any] | None = None,
        *,
        initial_contextual_outputs: dict[ContextKey, Any] | None = None,
        on_context_state_changed: ContextStateCallback | None = None,
    ) -> Future[ExecutionResult]:
        if self._latest_future is not None:
            self._latest_future.cancel()

        future = self._executor.submit(
            execute,
            plan,
            initial_outputs=initial_outputs,
            initial_contextual_outputs=initial_contextual_outputs,
            on_context_state_changed=on_context_state_changed,
        )

        self._latest_future = future
        return future

    def close(self) -> None:
        self._executor.shutdown(wait=False)

