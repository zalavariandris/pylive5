"""Small operator graph: cooks run on worker threads, UI reads events.

Three rules make the threading easy to reason about:

1. Only the UI thread edits the Graph.
2. A job evaluates a private snapshot taken on the UI thread at submit time.
3. "Is this job stale?" is answered by one integer: graph.version.
   Workers never get notified; they just compare the number.

Workers talk to the UI only through a Queue of small immutable events.
"""
from __future__ import annotations

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import count
from queue import Empty, Queue
from typing import Any, Callable, NamedTuple


class Cancelled(Exception):
    pass


class Event(NamedTuple):
    job_id: int
    node: str | None      # None = the whole job
    frame: int
    status: str           # running | ok | error | cancelled


class Node:
    def __init__(self, fn: Callable, **params: Any):
        self.fn = fn
        self.name = fn.__name__
        self.params = params                 # plain editable values
        self.inputs: dict[str, Node] = {}    # port name -> upstream node


class Graph:
    """Edited on the UI thread only. Every edit bumps `version`."""

    def __init__(self):
        self.version = 0

    def set_param(self, node: Node, key: str, value: Any) -> None:
        if key not in node.params:
            raise KeyError(f"{node.name} has no parameter {key!r}")
        node.params[key] = value
        self.version += 1

    def connect(self, node: Node, port: str, upstream: Node) -> None:
        if self._reaches(upstream, node):
            raise ValueError("Connection would create a cycle")
        node.inputs[port] = upstream
        self.version += 1

    def disconnect(self, node: Node, port: str) -> None:
        node.inputs.pop(port)
        self.version += 1

    def _reaches(self, start: Node, target: Node) -> bool:
        return start is target or any(
            self._reaches(up, target) for up in start.inputs.values())


class Ctx:
    """What a node function receives as its first argument."""

    def __init__(self, job: Job, inputs: dict[str, Node], frame: int):
        self._job, self._inputs, self.frame = job, inputs, frame

    def check(self) -> None:
        """Call in long loops so cancellation is noticed promptly."""
        if self._job.is_stale():
            raise Cancelled

    def input(self, port: str, frame: int | None = None) -> Any:
        upstream = self._inputs[port]
        return self._job.cook(upstream, self.frame if frame is None else frame)


class Job:
    _ids = count(1)

    def __init__(self, graph: Graph, root: Node, frame: int, events: Queue):
        self.id = next(Job._ids)
        self.graph, self.root, self.frame, self.events = graph, root, frame, events
        self.version = graph.version
        self.stop = threading.Event()        # explicit cancel (user, shutdown)
        self.memo: dict[tuple[Node, int], Any] = {}
        # Snapshot (UI thread): copy params so later edits can't leak in.
        self.snap: dict[Node, tuple[dict, dict]] = {}
        self._snapshot(root)
        self.future = None                   # set by Engine.submit

    def _snapshot(self, node: Node) -> None:
        if node in self.snap:
            return
        self.snap[node] = (copy.deepcopy(node.params), dict(node.inputs))
        for upstream in node.inputs.values():
            self._snapshot(upstream)

    # -- called from the UI thread -------------------------------------
    def cancel(self) -> None:
        self.stop.set()

    def result(self, timeout: float | None = None) -> Any:
        return self.future.result(timeout)

    # -- called from the worker thread ---------------------------------
    def is_stale(self) -> bool:
        # Reading an int is atomic in CPython; no lock needed.
        return self.stop.is_set() or self.graph.version != self.version

    def emit(self, node: Node | None, frame: int, status: str) -> None:
        self.events.put(Event(self.id, node.name if node else None, frame, status))

    def cook(self, node: Node, frame: int) -> Any:
        if self.is_stale():
            raise Cancelled
        key = (node, frame)
        if key in self.memo:
            return self.memo[key]
        params, inputs = self.snap[node]
        self.emit(node, frame, "running")
        try:
            value = node.fn(Ctx(self, inputs, frame), **params)
        except Cancelled:
            self.emit(node, frame, "cancelled")
            raise
        except Exception:
            self.emit(node, frame, "error")
            raise
        self.memo[key] = value
        self.emit(node, frame, "ok")
        return value

    def run(self) -> Any:
        status = "ok"
        try:
            return self.cook(self.root, self.frame)
        except Cancelled:
            status = "cancelled"
            raise
        except Exception:
            status = "error"
            raise
        finally:
            self.emit(None, self.frame, status)


class Engine:
    def __init__(self, graph: Graph, workers: int = 2):
        self.graph = graph
        self.events: Queue[Event] = Queue()
        self.pool = ThreadPoolExecutor(workers, thread_name_prefix="cook")

    def submit(self, root: Node, frame: int) -> Job:
        job = Job(self.graph, root, frame, self.events)   # snapshot here
        job.future = self.pool.submit(job.run)
        return job

    def drain(self, limit: int = 100) -> list[Event]:
        """UI thread: call from a QTimer."""
        out = []
        for _ in range(limit):
            try:
                out.append(self.events.get_nowait())
            except Empty:
                break
        return out

    def shutdown(self) -> None:
        self.pool.shutdown(wait=True, cancel_futures=True)


class StatusBoard:
    """UI thread only. Shows the status of one followed job."""

    def __init__(self):
        self.job_id: int | None = None
        self.status: dict[tuple[str | None, int], str] = {}

    def follow(self, job: Job) -> None:
        self.job_id = job.id
        self.status.clear()

    def apply(self, ev: Event) -> None:
        if ev.job_id == self.job_id:         # ignore every other job
            self.status[(ev.node, ev.frame)] = ev.status


if __name__ == "__main__":
    def animated_cube(ctx, size):
        time.sleep(0.04)
        ctx.check()
        return size + ctx.frame * 0.1

    def blend(ctx):
        f = ctx.frame
        return (0.25 * ctx.input("source", f - 1)
                + 0.50 * ctx.input("source", f)
                + 0.25 * ctx.input("source", f + 1))

    cube = Node(animated_cube, size=5)
    mix = Node(blend)
    graph = Graph()
    graph.connect(mix, "source", cube)

    engine = Engine(graph)
    board = StatusBoard()
    try:
        first = engine.submit(mix, frame=100)
        board.follow(first)
        graph.set_param(cube, "size", 10)        # first is now stale
        second = engine.submit(mix, frame=100)
        board.follow(second)

        print("second ->", round(second.result(), 3))     # 10 + 10.0 = 20.0
        try:
            first.result()
        except Cancelled:
            print("first  -> cancelled")

        for ev in engine.drain(1000):
            board.apply(ev)
        print("board  ->", board.status[(None, 100)], board.status[("blend", 100)])
    finally:
        engine.shutdown()