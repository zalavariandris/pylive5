"""Deterministic backend for lifecycle tests, with no worker timing assumptions."""

from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from pygraphrt2 import Graph
from pygraphrt2.execution_plan import NodeStateSnapshot


class ControlledBackend:
    def __init__(self, graph: Graph) -> None:
        self.evaluations: list[Future[dict[str, Callable[..., Any]]]] = []
        self.executions: list[Future[dict[str, Any]]] = []

    def evaluate(
        self, source: str, *, name: str = "<script>",
    ) -> Future[dict[str, Callable[..., Any]]]:
        future: Future[dict[str, Callable[..., Any]]] = Future()
        self.evaluations.append(future)
        return future

    def execute_plan(
        self, plan: dict[str, NodeStateSnapshot],
        initial_outputs: dict[str, Any] | None = None,
    ) -> Future[dict[str, Any]]:
        future: Future[dict[str, Any]] = Future()
        self.executions.append(future)
        return future

    def close(self) -> None:
        pass
