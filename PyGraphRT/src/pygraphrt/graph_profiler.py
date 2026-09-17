from contextlib import contextmanager
import time
from pygraphrt.node_rt import NodeRT

class GraphProfiler:
    """Profiles the execution time of nodes in the graph. with a context manager interface."""
    def __init__(self):
        self._execution_times: dict[NodeRT, float] = dict()

    def __getitem__(self, node: NodeRT) -> float | None:
        return self._execution_times.get(node)

    def clear(self, node:NodeRT|None=None):
        if node is None:
            self._execution_times.clear()
        else:
            self._execution_times.pop(node, None)

    @contextmanager
    def profile(self, node: NodeRT):
        start_time = time.time()
        current_node = node
        try:
            yield
        finally:
            elapsed_time = time.time() - start_time
            self._execution_times[current_node] = elapsed_time