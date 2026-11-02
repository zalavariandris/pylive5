from enum import Enum


class NodeExecutionState(Enum):
    """Graph presentation state; EXECUTING includes queued work and script loading."""

    IDLE = "IDLE"
    EXECUTING = "EXECUTING"
    ERROR = "ERROR"
