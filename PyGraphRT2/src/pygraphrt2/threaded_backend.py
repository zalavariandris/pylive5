from typing import Any, Callable

from .graph import Graph, NodeRef
from .execution_plan import NodeStateSnapshot, NodeOutput
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
        self._latest_future: Future[dict[str, Any]] | None = None

    def evaluate(self, source:str, *, name: str="<script>") -> Future[dict[str, Callable[..., Any]]]:
        return self._executor.submit(evaluate, source, name=name)
        # future: Future[dict[str, Callable[..., Any]]] = Future()

        # try:
        #     functions = evaluate(source, name=name)
        # except Exception as error:
        #     future.set_exception(error)
        # else:
        #     future.set_result(functions)

        # return future

    def execute_plan(self, plan:dict[str, NodeStateSnapshot]) -> Future[dict[str, Any]]:
        if self._latest_future is not None:
            self._latest_future.cancel()

        future = self._executor.submit(execute, plan)
        self._latest_future = future
        return future

    def close(self) -> None:
        self._executor.shutdown(wait=False)

