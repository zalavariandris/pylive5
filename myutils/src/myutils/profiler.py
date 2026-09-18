from contextlib import contextmanager
import time
from typing import Hashable

class Profiler:
    """Profiles the execution time of nodes in the graph. with a context manager interface."""
    def __init__(self):
        self._execution_times: dict[Hashable, float] = dict()

    def __getitem__(self, key: Hashable) -> float | None:
        return self._execution_times.get(key)

    def clear(self, key:Hashable|None=None):
        if key is None:
            self._execution_times.clear()
        else:
            self._execution_times.pop(key, None)

    @contextmanager
    def profile(self, key: Hashable):
        start_time = time.time()
        current_node = key
        try:
            yield
        finally:
            elapsed_time = time.time() - start_time
            self._execution_times[current_node] = elapsed_time