"""Eager operators, operator graph, Job, Engine and a runnable example."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from base_engine import (
    CacheProtocol, Engine, ExecutionResult, GraphProtocol, MemoryCache,
    ObservableGraph, copy_graph, descendants, topological_sort,
)

from abc import ABC, abstractmethod

class EagerOperator(ABC):
    @abstractmethod
    def compute(self, **bindings: Any) -> Any: ...

def eager_operator(fn: Callable[..., Any]) -> type[EagerOperator]:
    return type(fn.__name__, (EagerOperator,), {
        '__module__': fn.__module__, '__doc__': fn.__doc__, 'compute': staticmethod(fn)
    })

class EagerGraph(ObservableGraph[EagerOperator]):
    """Keep EagerOperator input bindings synchronized with graph links."""

    def _validate(self, node: EagerOperator, bindings: Mapping[str, Any]) -> None:
        existing = set(self.nodes())
        for value in bindings.values():
            if isinstance(value, EagerOperator):
                if value not in existing:
                    raise ValueError('Referenced operator is not in graph')
                if value is node or (node in existing and value in descendants(self, node)):
                    raise ValueError('Link would create a cycle')

    def add(self, node: EagerOperator, **bindings: Any) -> EagerOperator:
        if not isinstance(node, EagerOperator):
            raise TypeError(f'Expected {EagerOperator.__name__}')
        if node in self.nodes():
            raise ValueError('Node already in graph')
        self._validate(node, bindings)
        super().add(node, **bindings)
        for name, value in bindings.items():
            if isinstance(value, EagerOperator):
                super().add_link(value, node, name)
        return node

    def set(self, node: EagerOperator, **bindings: Any) -> None:
        self._require(node)
        self._validate(node, bindings)
        super().set(node, **bindings)
        incoming = {link.input: link.source for link in self.in_links(node)}
        for name, value in bindings.items():
            if isinstance(value, EagerOperator):
                super().add_link(value, node, name)
            elif name in incoming:
                super().remove_link(incoming[name], node, name)

    def unset(self, node: EagerOperator, *names: str) -> None:
        self._require(node)
        names = tuple(dict.fromkeys(names))
        if any(name not in self.attributes(node) for name in names):
            raise KeyError('Binding does not exist')
        incoming = {link.input: link.source for link in self.in_links(node)}
        super().unset(node, *names)
        for name in names:
            if name in incoming:
                super().remove_link(incoming[name], node, name)

    def add_link(self, source: EagerOperator, target: EagerOperator, input: str) -> None:
        self.set(target, **{input: source})

    def remove_link(self, source: EagerOperator, target: EagerOperator, input: str) -> None:
        if not any(link.source == source and link.input == input
                   for link in self.in_links(target)):
            raise ValueError('Link does not exist')
        self.unset(target, input)

    def remove(self, node: EagerOperator) -> None:
        self._require(node)
        for link in self.out_links(node):
            self.unset(link.target, link.input)
        super().remove(node)

def resolved_bindings(graph: GraphProtocol[NodeT], node: NodeT,
                      values: Mapping[NodeT, Any]) -> dict[str, Any]:
    bindings = dict(graph.attributes(node))
    for link in graph.in_links(node):
        bindings[link.input] = values[link.source]
    return bindings

class EagerJob:
    """Evaluate ancestors in dependency-first order, memoized for one run."""
    def __init__(self, graph: GraphProtocol[EagerOperator], node: EagerOperator,
                 cached: Mapping[EagerOperator, Any]):
        self.graph = graph
        self.node = node
        self._memo = dict(cached)
        self.results: list[ExecutionResult[EagerOperator, Any]] = []

    def run(self) -> Any:
        for node in topological_sort(self.graph, self.node):
            if node in self._memo:
                continue
            value = node.compute(**resolved_bindings(self.graph, node, self._memo))
            self._memo[node] = value
            self.results.append(ExecutionResult(node, value))
        return self._memo[self.node]

class EagerEngine(Engine[EagerOperator, Any]):
    def __init__(self, graph: EagerGraph,
                 cache: CacheProtocol[EagerOperator, Any] | None = None):
        super().__init__(graph, cache if cache is not None else MemoryCache())

    def evaluate(self, node: EagerOperator) -> Any:
        generation = self._generation
        job = EagerJob(copy_graph(self.graph), node, dict(self.cache))
        try:
            value = job.run()
        except Exception:
            self._commit(job.results, generation)
            raise
        self._commit(job.results, generation)
        return value

    def results(self, node: EagerOperator) -> Any:
        return self.cache.get(node)

    def _evict(self, nodes: set[EagerOperator]) -> None:
        for node in nodes:
            self.cache.remove(node)

    def _store(self, result: ExecutionResult[EagerOperator, Any]) -> None:
        self.cache.save(result.node, result.value)

@eager_operator
def Add(a: int, b: int) -> int:
    return a + b

if __name__ == "__main__":
    graph = EagerGraph()
    left = graph.add(Add(), a=1, b=2)
    right = graph.add(Add(), a=left, b=3)
    engine = EagerEngine(graph)
    engine.listen(lambda change: print("Eager event:", change))
    print("Eager:", engine.evaluate(right))  # 6
    graph.set(left, a=10)
    print("Eager updated:", engine.evaluate(right))  # 15
