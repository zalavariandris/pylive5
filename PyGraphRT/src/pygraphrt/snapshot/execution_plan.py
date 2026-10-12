from dataclasses import dataclass
from typing import Any, Callable
from copy import deepcopy
from ..graph_definition_rt import GraphDefinitionRT, NodeRef

@dataclass(frozen=True)
class NodeOutput:
    """Reference to another node's output within this plan."""
    node_name: str

@dataclass(frozen=True)
class OperatorSnapshot:
    """Captured implementation, treated as immutable during execution."""
    function: Callable[..., Any]

@dataclass(frozen=True)
class NodeSnapshot:
    """Captured operator and inputs for one node."""
    name: str
    operator: OperatorSnapshot | None
    args: tuple[Any, ...] = ()
    kwargs: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    """Captured nodes required to evaluate the requested outputs."""

    revision: int
    targets: tuple[str, ...]
    nodes: tuple[NodeSnapshot, ...]                      


def prepare(graph: GraphDefinitionRT, target: NodeRef, *, revision: int) -> ExecutionPlan:
    # validate targets
    if target not in graph.nodes():
        raise ValueError(f"Node {target.get_name()!r} is not in the graph.")

    ordered_nodes = graph.topological_sort(graph.ancestors(target))

    # Preserve shared inputs within this snapshot while copying them.
    memo: dict[int, Any] = {}

    def capture_input(value: Any) -> Any:
        if isinstance(value, NodeRef):
            return NodeOutput(value.get_name())
        return deepcopy(value, memo)

    snapshots: list[NodeSnapshot] = []

    for node in ordered_nodes:
        operator_ref = node.get_operator()
        function = (
            operator_ref.get_callable()
            if operator_ref is not None
            else None
        )
        args, kwargs = node.get_inputs()

        snapshots.append(
            NodeSnapshot(
                name=node.get_name(),
                operator=(
                    OperatorSnapshot(function)
                    if function is not None
                    else None
                ),
                args=tuple(capture_input(value) for value in args),
                kwargs=tuple(
                    (name, capture_input(value))
                    for name, value in kwargs.items()
                ),
            )
        )

    return ExecutionPlan(
        revision=revision,
        targets=(noderef.get_name(),),
        nodes=tuple(snapshots),
    )

def execute(plan: ExecutionPlan) -> dict[str, Any]:
    outputs: dict[str, Any] = {}

    def resolve_input(value: Any) -> Any:
        if isinstance(value, NodeOutput):
            return outputs[value.node_name]
        return value

    for node in plan.nodes:
        try:
            operator = node.operator
            if operator is None:
                raise ValueError("Operator is unavailable.")

            args = tuple(resolve_input(value) for value in node.args)
            kwargs = {
                name: resolve_input(value)
                for name, value in node.kwargs
            }

            outputs[node.name] = operator.function(*args, **kwargs)

        except Exception as error:
            raise RuntimeError(
                f"Execution failed at node {node.name!r}."
            ) from error

    return {
        target: outputs[target]
        for target in plan.targets
    }