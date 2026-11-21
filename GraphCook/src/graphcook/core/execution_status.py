from dataclasses import dataclass
from typing import TypeVar, Any


T = TypeVar("T")

@dataclass(frozen=True)
class DirtyStatus:
    pass


@dataclass(frozen=True)
class RunningStatus:
    progress: float | None = None  # 0–1; None means unknown


@dataclass(frozen=True)
class SucceededStatus[T]:
    value: T
    duration_seconds: float | None = None


@dataclass(frozen=True)
class FailedStatus:
    reason: Exception

type ExecutionStatus[T] = (
    DirtyStatus | RunningStatus | SucceededStatus[T] | FailedStatus
)
