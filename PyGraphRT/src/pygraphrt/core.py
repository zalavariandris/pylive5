from dataclasses import dataclass
from typing import Any


from .graph_definition_rt import (
    NodeRef
)
@dataclass(frozen=True)
class ExecutionPending:
    """Represents node execution state that is pending."""
    node: NodeRef

@dataclass(frozen=True)
class ExecutionRunning:
    """Represents node execution state that is currently running."""
    node: NodeRef

@dataclass(frozen=True)
class ExecutionSuccess:
    """A successful result, retaining the timing of its original computation."""
    node: NodeRef
    result: Any
    duration_seconds: float | None = None
    cached: bool = False

    @property
    def duration_ms(self) -> float | None:
        """Original execution time in milliseconds, or None when unmeasured."""
        if self.duration_seconds is None:
            return None
        return self.duration_seconds * 1000.0

@dataclass(frozen=True)
class ExecutionFailure:
    """Represents node execution state that has failed
    due to an error."""
    node: NodeRef
    reason: str | BaseException
    duration_seconds: float | None = None

@dataclass(frozen=True)
class ExecutionBlocked:
    """Represents node execution state that is blocked
    due to unavailable dependencies."""
    node: NodeRef
    blocked_by: frozenset[NodeRef]

NodeExecution = (
    ExecutionPending
    | ExecutionRunning
    | ExecutionSuccess
    | ExecutionFailure
    | ExecutionBlocked
)