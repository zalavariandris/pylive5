from typing import TYPE_CHECKING


from .graph import NodeRef

class ExecutionFailure(Exception):
    def __init__(
        self, node: NodeRef | None, error: Exception, targets: tuple[NodeRef, ...] = (),
    ) -> None:
        self.node = node
        self.error = error
        self.targets = targets
        super().__init__(f"Execution failed for {node}: {error}")