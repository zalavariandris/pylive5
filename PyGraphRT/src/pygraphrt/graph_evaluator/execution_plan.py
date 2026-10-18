"""Capture graph work on the owning thread and execute without a live cache."""

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from myutils.profiler import Profiler

from ..abstract_operator import AbstractOperator
from ..function_operator import FunctionOperator
from ..graph_definition_rt import GraphDefinitionRT, NodeRef


@dataclass(frozen=True)
class NodeOutput:
    """Reference to an output computed or supplied within this plan."""

    node_name: str


@dataclass(frozen=True)
class OperatorSnapshot:
    """Captured callable, independent of live operator lookup."""

    function: Callable[..., Any]


@dataclass(frozen=True)
class NodeSnapshot:
    """Captured callable and inputs for one computation."""

    name: str
    operator: OperatorSnapshot | None
    args: tuple[Any, ...] = ()
    kwargs: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class ExecutionPlan:
    """One execution's computations and copies of required cached outputs.

    ``nodes`` contains only uncached work, in dependency order. Initial outputs
    include cached targets and cached dependencies at which traversal stopped.
    Values inside this shallowly frozen plan must be treated as read-only by
    operators. Callable globals and closures are not deep-copied.
    """

    revision: int
    targets: tuple[str, ...]
    nodes: tuple[NodeSnapshot, ...]
    initial_outputs: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass
class ExecutionResults:
    """New computation outcomes, keyed by name without live graph references.

    Cached inputs are deliberately absent from ``outputs``. Consumers combine
    it with ``plan.initial_outputs`` when delivering requested results.
    Durations measure successful operator calls, excluding input preparation.
    """

    outputs: dict[str, Any] = field(default_factory=dict)
    failures: dict[str, BaseException] = field(default_factory=dict)
    blocked: dict[str, frozenset[str]] = field(default_factory=dict)
    durations_seconds: dict[str, float] = field(default_factory=dict)


def _capture_operator(operator: AbstractOperator | None) -> OperatorSnapshot | None:
    if operator is None:
        return None

    get_callable = getattr(operator, "get_callable", None)
    if callable(get_callable):
        function = get_callable()
    elif isinstance(operator, FunctionOperator):
        # Compatibility adapter: the existing FunctionOperator has no public
        # get_callable(). Capture its function, not its live wrapper.
        function = operator._func
    else:
        raise TypeError(
            f"Operator {operator.get_name()!r} must expose get_callable() "
            "to be captured in an execution plan."
        )

    if not callable(function):
        raise TypeError(f"Operator {operator.get_name()!r} has no callable implementation.")
    return OperatorSnapshot(function)


def prepare(
    graph: GraphDefinitionRT,
    targets: Iterable[NodeRef],
    *,
    revision: int,
    cached_outputs: Mapping[NodeRef, Any] | None = None,
) -> ExecutionPlan:
    """Capture needed computations, stopping each branch at valid cached nodes.

    Call on the graph/cache owning thread. Literal inputs and required cached
    values must support ``deepcopy``; a shared memo preserves their aliases
    within this execution while isolating them from the persistent cache.
    """
    all_targets = tuple(dict.fromkeys(targets))
    existing_nodes = set(graph.nodes())
    for target in all_targets:
        if target not in existing_nodes:
            raise ValueError(f"Node {target} is not in the graph.")

    cache = cached_outputs if cached_outputs is not None else {}
    needed: set[NodeRef] = set()
    visited: set[NodeRef] = set()
    cached_nodes: list[NodeRef] = []
    pending = list(reversed(all_targets))
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)

        if node in cache:
            cached_nodes.append(node)
            continue

        needed.add(node)
        args, kwargs = node.get_inputs()
        for value in (*args, *kwargs.values()):
            if isinstance(value, NodeRef):
                pending.append(value)

    # Sorting only uncached work also detects cycles in that remaining work.
    ordered_nodes = graph.topological_sort(needed)
    memo: dict[int, Any] = {}
    initial_outputs = {
        node.get_name(): deepcopy(cache[node], memo)
        for node in cached_nodes
    }

    def capture_input(value: Any) -> Any:
        if isinstance(value, NodeRef):
            return NodeOutput(value.get_name())
        return deepcopy(value, memo)

    snapshots: list[NodeSnapshot] = []
    for node in ordered_nodes:
        args, kwargs = node.get_inputs()
        snapshots.append(
            NodeSnapshot(
                name=node.get_name(),
                operator=_capture_operator(node.get_operator()),
                args=tuple(capture_input(value) for value in args),
                kwargs=tuple(
                    (name, capture_input(value)) for name, value in kwargs.items()
                ),
            )
        )

    return ExecutionPlan(
        revision=revision,
        targets=tuple(node.get_name() for node in all_targets),
        nodes=tuple(snapshots),
        initial_outputs=MappingProxyType(initial_outputs),
    )


def execute(plan: ExecutionPlan) -> ExecutionResults:
    """Run the captured computations, reusing supplied outputs as dependencies."""
    results = ExecutionResults()
    profiler = Profiler()
    available = dict(plan.initial_outputs)

    def resolve_input(value: Any) -> Any:
        if isinstance(value, NodeOutput):
            return available[value.node_name]
        return value

    for node in plan.nodes:
        inputs = (*node.args, *(value for _, value in node.kwargs))
        unavailable = frozenset(
            value.node_name
            for value in inputs
            if isinstance(value, NodeOutput) and value.node_name not in available
        )
        if unavailable:
            results.blocked[node.name] = unavailable
            continue

        try:
            if node.operator is None:
                raise ValueError("Operator is unavailable.")
            args = tuple(resolve_input(value) for value in node.args)
            kwargs = {name: resolve_input(value) for name, value in node.kwargs}
            with profiler.profile(node.name):
                output = node.operator.function(*args, **kwargs)
            duration_seconds = profiler[node.name]
            if duration_seconds is not None:
                results.durations_seconds[node.name] = duration_seconds
            available[node.name] = output
            results.outputs[node.name] = output
        except BaseException as error:
            # Script-level SystemExit must also produce a node outcome.
            results.failures[node.name] = error

    return results


def plan_failure(plan: ExecutionPlan, error: BaseException) -> ExecutionResults:
    """Represent a backend failure before per-node outcomes are available."""
    return ExecutionResults(failures={node.name: error for node in plan.nodes})
