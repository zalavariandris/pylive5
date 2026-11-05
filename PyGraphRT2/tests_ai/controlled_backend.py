"""Deterministic backend for lifecycle tests, with no worker timing assumptions."""

from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from pygraphrt2 import Graph
from pygraphrt2.execution_plan import (
    RequestKey, RequestStateCallback, ExecutionResult, NodeStateSnapshot,
)


class ControlledBackend:
    def __init__(self, graph: Graph) -> None:
        self.evaluations: list[Future[dict[str, Callable[..., Any]]]] = []
        self.executions: list[Future[ExecutionResult]] = []
        self.initial_request_outputs: list[dict[RequestKey, Any]] = []
        self.request_callbacks: list[RequestStateCallback | None] = []

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
        initial_request_outputs: dict[RequestKey, Any] | None = None,
        on_request_state_changed: RequestStateCallback | None = None,
    ) -> Future[ExecutionResult]:
        future: Future[ExecutionResult] = Future()
        self.executions.append(future)
        self.initial_request_outputs.append(initial_request_outputs or {})
        self.request_callbacks.append(on_request_state_changed)
        return future

    def close(self) -> None:
        pass
