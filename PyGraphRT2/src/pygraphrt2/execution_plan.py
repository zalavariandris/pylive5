"""Turn a graph into an execution plan, and run it.

Execution has two stages:

* push: `execute` walks the plan in topological order and calls every node's
  operator with its inputs. This is plain forward evaluation.
* pull: an operator can return a `Requestable`. Calling it later, from another
  node or from the engine, is a request. Requests are cached per node and
  arguments, and reported through a state callback.

The module is organised in that order: plan data, script operators, planning,
errors and result types, request machinery, execution.
"""

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, ClassVar, Generator, Hashable, Mapping

from .graph import Graph, NodeRef


@dataclass(frozen=True)
class NodeOutput:
    """Placeholder for the output of another node in the plan."""
    node_id: str


@dataclass(frozen=True)
class NodeStateSnapshot:
    """Captured callable and inputs for one computation."""
    operator: Callable | None
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)


def evaluate(script: str, *, name: str = "<script>") -> dict[str, Callable]:
    """Run a script and collect the callables it exposes as operators.

    With `__all__`, exactly the listed names are exposed. Without it, the
    public callables defined in the script itself are exposed.

    Raises:
        Exception: whatever the script raises, or ValueError for a bad `__all__`.
    """
    module = ModuleType(name)
    module.__package__ = ""
    namespace: dict[str, Any] = module.__dict__
    exec(compile(script, name, "exec"), namespace)

    callables = {key: value for key, value in namespace.items() if callable(value)}

    if "__all__" in namespace:
        _validate_exported_names(namespace)
        exported = set(namespace["__all__"])
        return {key: value for key, value in callables.items() if key in exported}
    else:
        return {
            key: value
            for key, value in callables.items()
            if isinstance(key, str)
            and not key.startswith("_")
            and getattr(value, "__module__", None) == name
        }

def _validate_exported_names(namespace: Mapping[str, Any]) -> None:
    """Return exported names used by `__all__`. """
    if "__all__" not in namespace:
        raise ValueError("__all__ is not defined in the namespace.")

    names = namespace["__all__"]
    if type(names) not in (list, tuple):
        raise ValueError("__all__ must be a list or tuple of strings")
    
    for key in names:
        if type(key) is not str:
            raise ValueError("__all__ entries must be strings")
        
    for key in names:
        if key not in namespace:
            raise ValueError(f"__all__ references undefined name {key!r}")


def prepare(
    graph: Graph,
    targets: tuple[NodeRef, ...],
    cached_outputs: dict[NodeRef, Any] | None = None,
) -> tuple[dict[str, NodeStateSnapshot], dict[str, NodeRef], dict[str, Any]]:
    """Prepare an execution plan for the given graph and targets.

    Nodes with a cached output are not planned again; their outputs are handed
    to `execute` as initial outputs.

    Args:
        graph: The computation graph.
        targets: The nodes whose outputs are wanted.
        cached_outputs: Already known outputs, by node.

    Returns:
        A tuple of
        - plan: snapshots of the nodes to run, by node name, in execution order.
        - mapping: node name to NodeRef, for planned and cached nodes.
        - initial_outputs: cached outputs by node name.
    """
    cache = cached_outputs if cached_outputs is not None else {}
    targets = tuple(dict.fromkeys(targets))

    existing_nodes = set(graph.nodes())
    for target in targets:
        if target not in existing_nodes:
            raise ValueError(f"Node {target} is not in the graph.")

    needed, cached_nodes = _find_required_nodes(graph, targets, cache)

    # Sorting only the uncached work also detects cycles in that remaining work.
    ordered_nodes = graph.topological_sort(needed)

    initial_outputs = {node.name(): cache[node] for node in cached_nodes}

    mapping = {node.name(): node for node in cached_nodes}
    plan: dict[str, NodeStateSnapshot] = {}
    for node in ordered_nodes:
        plan[node.name()] = _snapshot(graph, node)
        mapping[node.name()] = node
    return plan, mapping, initial_outputs


def _find_required_nodes(
    graph: Graph,
    targets: tuple[NodeRef, ...],
    cache: Mapping[NodeRef, Any],
) -> tuple[set[NodeRef], list[NodeRef]]:
    """Walk upstream from the targets, stopping at cached nodes.

    Returns the nodes that must run and the cached nodes that were reached.
    """
    needed: set[NodeRef] = set()
    cached_nodes: list[NodeRef] = []
    visited: set[NodeRef] = set()
    pending = list(reversed(targets))

    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)

        if node in cache:
            cached_nodes.append(node)
            continue

        needed.add(node)
        state = graph._nodes[node]
        pending.extend(
            value
            for value in (*state.args, *state.kwargs.values())
            if isinstance(value, NodeRef)
        )

    return needed, cached_nodes


def _snapshot(graph: Graph, node: NodeRef) -> NodeStateSnapshot:
    """Capture a node's operator, replacing node inputs with NodeOutput markers."""
    state = graph._nodes[node]

    def as_input(value: Any) -> Any:
        return NodeOutput(value.name()) if isinstance(value, NodeRef) else value

    return NodeStateSnapshot(
        operator=state.operator,
        args=[as_input(value) for value in state.args],
        kwargs={key: as_input(value) for key, value in state.kwargs.items()},
    )


class NodeExecutionError(Exception):
    def __init__(self, node_name: str, error: Exception) -> None:
        self.node_name = node_name
        self.error = error
        super().__init__(f"Execution failed for {node_name}: {error}")


type RequestKey = tuple[str, Hashable]
type RequestStateCallback = Callable[[RequestKey, bool], None]


@dataclass
class ExecutionResult:
    outputs: dict[str, Any]
    request_outputs: dict[RequestKey, Any] = field(default_factory=dict)


@dataclass
class _RequestRuntime:
    """Request storage and reporting for one execution."""
    cached_outputs: Mapping[RequestKey, Any]
    on_request_state_changed: RequestStateCallback | None = None
    computed_outputs: dict[RequestKey, Any] = field(default_factory=dict)

    # Lets a Requestable find the runtime of the execution that is running now,
    # even when it was created, and cached, by an earlier one.
    _current: ClassVar[ContextVar["_RequestRuntime | None"]] = ContextVar(
        "pygraphrt2_request_runtime",
        default=None,
    )

    @classmethod
    def current(cls) -> "_RequestRuntime | None":
        """The runtime of the execution running in this context, if any."""
        return cls._current.get()

    @contextmanager
    def activate(self) -> Generator["_RequestRuntime", None, None]:
        """Make this runtime the current one for the duration of the block."""
        token = self._current.set(self)
        try:
            yield self
        finally:
            self._current.reset(token)

    def request(self, key: RequestKey, compute: Callable[[], Any]) -> Any:
        """Return the stored result for `key`, computing and storing it if missing."""
        if key in self.computed_outputs:
            return self.computed_outputs[key]
        if key in self.cached_outputs:
            return self.cached_outputs[key]

        self._notify(key, True)
        try:
            value = compute()
            self.computed_outputs[key] = value
            return value
        finally:
            self._notify(key, False)

    def _notify(self, key: RequestKey, running: bool) -> None:
        if self.on_request_state_changed is not None:
            self.on_request_state_changed(key, running)


class Requestable:
    """Base class for operators whose instances are pulled by calling them.

    The constructor is the push stage: the engine calls the operator with the
    node's inputs and keeps the instance as the node's output. Calling the
    instance is the pull stage. During an execution, calls on an instance that
    belongs to a node are cached per (node, arguments) and reported through the
    request state callback. Other calls are plain calls.
    """

    _node_name: str | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        compute = cls.__dict__.get("__call__")
        if compute is not None:
            cls.__call__ = _managed(compute)

    def __call__(self, *args: Hashable, **kwargs: Hashable) -> Any:
        raise NotImplementedError(f"{type(self).__name__} must implement __call__")

    def _bind(self, node_name: str) -> None:
        # A node that returns an upstream instance keeps the original owner.
        if self._node_name is None:
            self._node_name = node_name


def _managed(compute: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a `__call__` implementation so the active runtime manages its calls."""

    @functools.wraps(compute)
    def call(self: Requestable, *args: Hashable, **kwargs: Hashable) -> Any:
        runtime = _RequestRuntime.current()
        node_name = self._node_name
        if runtime is None or node_name is None:
            return compute(self, *args, **kwargs)

        key: RequestKey = (node_name, (args, tuple(kwargs.items())))
        try:
            return runtime.request(key, lambda: compute(self, *args, **kwargs))
        except NodeExecutionError:
            raise
        except Exception as error:
            raise NodeExecutionError(node_name, error) from error

    return call


def execute(
    plan: dict[str, NodeStateSnapshot],
    initial_outputs: Mapping[str, Any] | None = None,
    *,
    initial_request_outputs: Mapping[RequestKey, Any] | None = None,
    on_request_state_changed: RequestStateCallback | None = None,
) -> ExecutionResult:
    """Run the plan in order and return every node output and computed request."""
    outputs = dict(initial_outputs) if initial_outputs is not None else {}
    runtime = _RequestRuntime(
        cached_outputs=dict(initial_request_outputs or {}),
        on_request_state_changed=on_request_state_changed,
    )

    with runtime.activate():
        for node_name, snapshot in plan.items():
            ## Run Node
            try:
                args = [
                    outputs[value.node_id] 
                    if isinstance(value, NodeOutput) else value 
                    for value in snapshot.args
                ]
                kwargs = {
                    key: outputs[value.node_id] 
                    if isinstance(value, NodeOutput) else value 
                    for key, value in snapshot.kwargs.items()
                }

                if snapshot.operator is None:
                    raise ValueError("Node has no operator")

                value = snapshot.operator(*args, **kwargs)
            except NodeExecutionError:
                raise
            except Exception as error:
                raise NodeExecutionError(node_name, error) from error

            if isinstance(value, Requestable):
                value._bind(node_name)
            outputs[node_name] = value

    return ExecutionResult(outputs=outputs, request_outputs=runtime.computed_outputs)



