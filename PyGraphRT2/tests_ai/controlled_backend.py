"""Deterministic backend for lifecycle tests, with no worker timing assumptions."""

from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from pygraphrt2 import Graph
from pygraphrt2.execution_plan import (
    ContextKey, ContextStateCallback, ExecutionResult, NodeStateSnapshot,
)


class ControlledBackend:
    def __init__(self, graph: Graph) -> None:
        self.evaluations: list[Future[dict[str, Callable[..., Any]]]] = []
        self.executions: list[Future[ExecutionResult]] = []
        self.initial_contextual_outputs: list[dict[ContextKey, Any]] = []
        self.context_callbacks: list[ContextStateCallback | None] = []

    def evaluate(
        self, source: str, *, name: str = "<script>",
    ) -> Future[dict[str, Callable[..., Any]]]:
        future: Future[dict[str, Callable[..., Any]]] = Future()
        self.evaluations.append(future)
        return future

    def execute_plan(
        self, plan: dict[str, NodeStateSnapshot],
        initial_outputs: dict[str, Any] | None = None,
        *,
        initial_contextual_outputs: dict[ContextKey, Any] | None = None,
        on_context_state_changed: ContextStateCallback | None = None,
    ) -> Future[ExecutionResult]:
        future: Future[ExecutionResult] = Future()
        self.executions.append(future)
        self.initial_contextual_outputs.append(initial_contextual_outputs or {})
        self.context_callbacks.append(on_context_state_changed)
        return future

    def close(self) -> None:
        pass
