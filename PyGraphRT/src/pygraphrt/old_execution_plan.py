from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable
from copy import deepcopy
from .graph_definition_rt import GraphDefinitionRT, NodeRef

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
    """Captured nodes required to evaluate the requested outputs. In order."""

    revision: int
    targets: tuple[str, ...]
    nodes: tuple[NodeSnapshot, ...]                      


@dataclass
class ExecutionResults:
    """Worker results keyed by node name, without live graph references."""

    outputs: dict[str, Any] = field(default_factory=dict)
    failures: dict[str, BaseException] = field(default_factory=dict)
    blocked: dict[str, frozenset[str]] = field(default_factory=dict)


def prepare(graph: GraphDefinitionRT, targets: Iterable[NodeRef], *, revision: int) -> ExecutionPlan:
    """
    return an execution plan for the specified target node.
    """
    # validate targets
    all_targets = list(targets)
    for target in all_targets:
        if target not in graph.nodes():
            raise ValueError(f"Node {target} is not in the graph.")

    ordered_nodes = graph.topological_sort(graph.ancestors(*all_targets))

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
        targets=tuple(t.get_name() for t in all_targets),
        nodes=tuple(snapshots),
    )

def execute(plan: ExecutionPlan) -> ExecutionResults:
    """Collect each node's outcome, skipping nodes with unavailable inputs."""
    results = ExecutionResults()

    def resolve_input(value: Any) -> Any:
        if isinstance(value, NodeOutput):
            return results.outputs[value.node_name]
        return value

    for node in plan.nodes:
        inputs = (*node.args, *(value for _, value in node.kwargs))
        unavailable = frozenset(
            value.node_name
            for value in inputs
            if isinstance(value, NodeOutput) and value.node_name not in results.outputs
        )
        if unavailable:
            results.blocked[node.name] = unavailable
            continue

        try:
            operator = node.operator
            if operator is None:
                raise ValueError("Operator is unavailable.")

            args = tuple(resolve_input(value) for value in node.args)
            kwargs = {
                name: resolve_input(value)
                for name, value in node.kwargs
            }

            results.outputs[node.name] = operator.function(*args, **kwargs)

        except BaseException as error:
            # Script-level SystemExit must also produce a node outcome.
            results.failures[node.name] = error

    return results
