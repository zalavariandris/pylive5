from typing import Any, Callable

from .graph import Graph, NodeRef
from .execution_plan import NodeStateSnapshot, NodeOutput
from concurrent.futures import Future
from .inline_scriptmodule import _get_all_callables_from_script

from .execution_plan import evaluate, prepare, execute


class ThreadedBackend:
    def __init__(self, graph: Graph) -> None:
        self.graph = graph

    def evaluate(self, source:str, *, name: str="<script>") -> Future[dict[str, Callable[..., Any]]]:
        future: Future[dict[str, Callable[..., Any]]] = Future()

        try:
            functions = evaluate(source, name=name)
        except Exception as error:
            future.set_exception(error)
        else:
            future.set_result(functions)

        return future

    def execute_plan(self, plan:dict[str, NodeStateSnapshot]) -> Future[dict[str, Any]]:
        future: Future[dict[str, Any]] = Future()


        try:
            outputs = execute(plan)
        except Exception as error:
            future.set_exception(error)
            return future

        future.set_result({name: value for name, value in outputs.items()})
        return future

