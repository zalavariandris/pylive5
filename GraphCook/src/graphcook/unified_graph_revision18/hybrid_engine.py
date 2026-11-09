"""Two-phase hybrid: propagate demand, then pull values during computation.

Context must support merge(other) for union. ContextualValue must support
select(context), raising KeyError for unavailable demand, and merge(other).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, Self

from graph import Graph, NodeT
from base_engine import BaseEngine, BaseJob, JobEvent, ProviderSnapshot, UNSET


class Context(Protocol):
    def merge(self, other: Self) -> Self: ...


class ContextualValue(Protocol):
    def select(self, context: Context) -> Self: ...
    def merge(self, other: Self) -> Self: ...


class HybridOperator(Protocol):
    def request(self, context: Context, /, **parameters: Any) -> Mapping[str, Context]: ...
    def compute(self, context: Context,
                get: Callable[[str, Context], ContextualValue],
                /, **parameters: Any) -> ContextualValue: ...


class HybridJob(BaseJob[NodeT]):
    def __init__(self, graph: Graph[NodeT], provider: ProviderSnapshot,
                 cached: Mapping[NodeT, Any], job_id: int,
                 emit: Callable[[JobEvent[NodeT]], None]) -> None:
        super().__init__(graph, provider, cached, job_id, emit)
        self.requested: dict[NodeT, Context] = {}
        self._planning: set[NodeT] = set()
        self._computing: set[NodeT] = set()

    def evaluate(self, node: NodeT, **kwargs: Any) -> ContextualValue:
        context = kwargs.pop("context")
        if kwargs:
            raise TypeError(f"Unexpected execution options: {tuple(kwargs)}")
        self._plan(node, context)
        return self._pull(node, context)

    def _plan(self, node: NodeT, context: Context) -> None:
        if node in self._planning:
            raise ValueError(f"Cycle detected during request at {node!r}")
        previous = self.requested.get(node)
        combined = context if previous is None else previous.merge(context)
        if previous is not None and combined == previous:
            return
        self.requested[node] = combined
        self._planning.add(node)
        try:
            try:
                operator: HybridOperator = self.operator(node)
                demands = operator.request(combined, **self.parameters(node))
            except Exception as exc:
                self.notify("failed", node, error=exc)
                raise
            inputs = {link.input: link.source for link in self.graph.in_links(node)}
            for name, demanded_context in demands.items():
                if name not in inputs:
                    error = KeyError(f"Unconnected requested input {name!r} on {node!r}")
                    self.notify("failed", node, error=error)
                    raise error
                self._plan(inputs[name], demanded_context)
        finally:
            self._planning.remove(node)

    def _pull(self, node: NodeT, context: Context) -> ContextualValue:
        existing = self.completed.get(node, self.cached.get(node, UNSET))
        if existing is not UNSET:
            try:
                selected = existing.select(context)
            except KeyError:
                pass  # Cache contains only part of the requested context.
            else:
                self.notify("cache_hit", node, result=selected)
                return selected

        # Supports extra input requests discovered dynamically in compute().
        self._plan(node, context)
        if node in self._computing:
            raise ValueError(f"Cycle detected during compute at {node!r}")
        self._computing.add(node)
        try:
            operator: HybridOperator = self.operator(node)
            inputs = {link.input: link.source for link in self.graph.in_links(node)}

            def get(input_name: str, wanted: Context) -> ContextualValue:
                if input_name not in inputs:
                    raise KeyError(f"Unconnected input {input_name!r} on {node!r}")
                return self._pull(inputs[input_name], wanted)

            self.notify("started", node)
            fresh = operator.compute(self.requested[node], get, **self.parameters(node))
            result = fresh if existing is UNSET else existing.merge(fresh)
            selected = result.select(context)  # Ensure this demand is satisfied.
            self.completed[node] = result
            self.notify("computed", node, result=result)
            return selected
        except Exception as exc:
            self.notify("failed", node, error=exc)
            raise
        finally:
            self._computing.remove(node)


class HybridEngine(BaseEngine[NodeT]):
    def evaluate(self, node: NodeT, context: Context) -> ContextualValue:
        return self._run_job(node, context=context)

    def _make_job(self, graph: Graph[NodeT], provider: ProviderSnapshot,
                  cached: Mapping[NodeT, Any], job_id: int,
                  emit: Callable[[JobEvent[NodeT]], None]) -> HybridJob[NodeT]:
        return HybridJob(graph, provider, cached, job_id, emit)
