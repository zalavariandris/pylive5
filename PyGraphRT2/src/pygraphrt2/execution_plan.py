from types import ModuleType
from typing import Any, Iterable
from types import FunctionType
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NodeStateSnapshot:
    """Captured callable and inputs for one computation."""
    operator: Callable|None
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeOutput:
    node_id: str

from .graph import Graph, NodeRef


def evaluate(
    script: str, *, name: str = '<script>'
) -> dict[str, Callable]:
    """Collect Python functions explicitly present in the script namespace.

    Args:
        script: The Python script source code.
        name: The name to assign to the script module.
        defined_only: If True, only include functions defined in the script itself.

    Returns:
        A dictionary mapping function names to function objects.

    Raises:
        ScriptEvaluationError: If the script cannot be compiled or executed.
    """

    module = ModuleType(name)
    module.__package__ = ""
    namespace: dict[str, Any] = module.__dict__

    code = compile(script, f"{name}", "exec")
    exec(code, namespace)


    # if __all__ export names is present, validate it before using
    _export_names: set[str] = set()
    if "__all__" in namespace:
        names_in_all = namespace["__all__"]
        if type(names_in_all) not in (list, tuple):
            raise ValueError("__all__ must be a list or tuple of strings")
        
        for key in names_in_all:
            if type(key) is not str:
                raise ValueError("__all__ entries must be strings")

        for key in names_in_all:
            if key not in namespace:
                raise ValueError(f"__all__ references undefined name {key!r}")
        _export_names = set(names_in_all)

    def is_exported(item: tuple[str, Any]) -> bool:
        """Check if the item is exported according to __all__."""
        key, _ = item
        return key in _export_names

    def is_public(item: tuple[str, Any]) -> bool:
        """Check if the item is a public name (does not start with an underscore)."""
        key, _ = item
        return type(key) is str and not key.startswith("_")

    def is_function(item: tuple[str, Any]) -> bool:
        """Check if the item is a function."""
        _, value = item
        return type(value) is FunctionType

    def is_callable(item: tuple[str, Any]) -> bool:
        """Check if the item is callable."""
        _, value = item
        return callable(value)

    def is_locally_defined(item: tuple[str, Any]) -> bool:
        """Check if the function is defined within the script module itself."""
        _, value = item
        return value.__module__ == name

    objects: Iterable[tuple[str, Any]] = namespace.items()
    objects = filter(is_callable, objects)
    if "__all__" in namespace:
        objects = filter(is_exported, objects)
    else:
        objects = filter(is_public, objects)
        objects = filter(is_locally_defined, objects)
    

    # if defined_only:
    #     objects = filter(is_locally_defined, objects)

    return dict(objects)


def prepare(
    graph: Graph,
    targets: tuple[NodeRef, ...],
) -> tuple[dict[str, NodeStateSnapshot], dict[str, NodeRef]]:
    """
    Prepare an execution plan for the given graph and targets.

    Args:
        graph: The computation graph.
        targets: The target nodes for which to prepare the plan.

    Returns:
        A tuple containing:
        - plan:    A dictionary mapping node names to their state snapshots.
        - mapping: A dictionary mapping node names to their corresponding NodeRef objects.
    """
    all_targets = tuple(dict.fromkeys(targets))
    existing_nodes = set(graph.nodes())
    for target in all_targets:
        if target not in existing_nodes:
            raise ValueError(f"Node {target} is not in the graph.")

    # Determine all nodes that are needed for the execution of the targets.
    needed: set[NodeRef] = set()
    visited: set[NodeRef] = set()
    pending = list(reversed(all_targets))
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)

        needed.add(node)
        node_state = graph._nodes[node]
        for value in (*node_state.args, *node_state.kwargs.values()):
            if isinstance(value, NodeRef):
                pending.append(value)

    # Sorting only uncached work also detects cycles in that remaining work.
    ordered_nodes = graph.topological_sort(needed)

    # # CACHE
    # memo: dict[int, Any] = {}
    # initial_outputs = {
    #     node_ref: deepcopy(cache[node_ref], memo)
    #     for node_ref in cached_nodes
    # }

    plan: dict[str, NodeStateSnapshot] = {}
    mapping: dict[str, NodeRef] = {}
    for node_ref in ordered_nodes:
        node_state = graph._nodes[node_ref]
        func = node_state.operator
        snapshot = NodeStateSnapshot(
            operator=func,
            args=[
                NodeOutput(node_id=val.name()) if isinstance(val, NodeRef) else val
                for val in node_state.args
            ],
            kwargs={
                key: NodeOutput(node_id=val.name()) if isinstance(val, NodeRef) else val
                for key, val in node_state.kwargs.items()
            }
        )
        plan[node_ref.name()] = snapshot
        mapping[node_ref.name()] = node_ref
    return plan, mapping

def execute(
    plan: dict[str, NodeStateSnapshot]
) -> dict[str, Any]:
    """
    Execute the given execution plan on the graph.

    Args:
        graph: The computation graph.
        plan: The execution plan mapping node names to their state snapshots.
        mapping: The mapping from node names to their corresponding NodeRef objects.

    Returns:
        A dictionary mapping node names to their computed outputs.
    """
    outputs: dict[str, Any] = {}
    for node_name, snapshot in plan.items():
        args = [
            outputs[val.node_id] if isinstance(val, NodeOutput) else val
            for val in snapshot.args
        ]
        kwargs = {
            key: outputs[val.node_id] if isinstance(val, NodeOutput) else val
            for key, val in snapshot.kwargs.items()
        }
        outputs[node_name] = snapshot.operator(*args, **kwargs)
    return outputs