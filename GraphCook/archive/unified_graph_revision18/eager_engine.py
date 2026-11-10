"""Eager, dependency-first execution of Python callables."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Generic

from graph import Graph, NodeT
from base_engine import BaseEngine, BaseJob, JobEvent, ProviderSnapshot


class EagerJob(BaseJob[NodeT]):
    def evaluate(self, node: NodeT, **kwargs: Any) -> Any:
        if kwargs:
            raise TypeError("EagerEngine.evaluate accepts only a node")
        visiting: set[NodeT] = set()
        return self._compute(node, visiting)

    def _compute(self, node: NodeT, visiting: set[NodeT]) -> Any:
        if node in self.completed:
            return self.completed[node]
        if node in self.cached:
            self.notify("cache_hit", node, result=self.cached[node])
            return self.cached[node]
        if node in visiting:
            raise ValueError(f"Cycle detected at node {node!r}")
        visiting.add(node)
        try:
            operator = self.operator(node)
            # Link values override parameters of the same name.
            arguments = self.parameters(node)
            for link in self.graph.in_links(node):
                arguments[link.input] = self._compute(link.source, visiting)
            self.notify("started", node)
            result = operator(**arguments)
            self.completed[node] = result
            self.notify("computed", node, result=result)
            return result
        except Exception as exc:
            self.notify("failed", node, error=exc)
            raise
        finally:
            visiting.remove(node)


class EagerEngine(BaseEngine[NodeT]):
    def evaluate(self, node: NodeT) -> Any:
        return self._run_job(node)

    def _make_job(self, graph: Graph[NodeT], provider: ProviderSnapshot,
                  cached: Mapping[NodeT, Any], job_id: int,
                  emit: Callable[[JobEvent[NodeT]], None]) -> EagerJob[NodeT]:
        return EagerJob(graph, provider, cached, job_id, emit)
