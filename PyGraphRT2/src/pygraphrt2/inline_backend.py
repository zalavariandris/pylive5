from typing import Any, Callable

from .graph import Graph, NodeRef
from .execution_plan import NodeStateSnapshot, NodeOutput
from concurrent.futures import Future
from .inline_scriptmodule import _get_all_callables_from_script

from .execution_plan import evaluate, prepare, execute

class ExecutionFailure(Exception):
    def __init__(
        self, node: NodeRef | None, error: Exception, targets: tuple[NodeRef, ...] = (),
    ) -> None:
        self.node = node
        self.error = error
        self.targets = targets
        super().__init__(f"Execution failed for {node}: {error}")


class InlineBackend:
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

    def execute(self, *targets: NodeRef) -> dict[NodeRef, Any]:
        if not targets:
            return {}
        try:
            required = self.graph.ancestors(*targets)
            ordered = self.graph.topological_sort(required)
        except Exception as error:
            raise ExecutionFailure(None, error, targets) from error

        outputs: dict[NodeRef, Any] = {}
        for node in ordered:
            try:
                state = node.resolve()
                args = [outputs[value] if isinstance(value, NodeRef) else value for value in state.args]
                kwargs = {
                    name: outputs[value] if isinstance(value, NodeRef) else value
                    for name, value in state.kwargs.items()
                }
                if state.operator is None:
                    raise ValueError(f"Operator for {node} is missing")
                outputs[node] = state.operator(*args, **kwargs)
            except Exception as error:
                raise ExecutionFailure(node, error, targets) from error
        return outputs
