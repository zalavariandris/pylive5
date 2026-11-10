"""Editable operator graph with isolated worker cooks, cancellation, and UI events.

Python 3.10+; NumPy is used for immutable array outputs and the example.

Subclass Node and implement compute() to define an operator, or use @cook(...)
as sugar that constructs a Node subclass and an instance. Each submitted
evaluation captures immutable graph bindings and owns its own memo. Graph
edits cancel stale evaluations by default (cooperatively). Events from
workers and graph edits are queued for consumption on the UI thread.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import wraps
from enum import Enum
from pathlib import PurePath
from queue import Empty, SimpleQueue
from threading import Event as ThreadEvent, RLock
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Mapping
from uuid import uuid4

import numpy as np


class CookCancelled(CancelledError):
    """Cooperative cancellation of an evaluation (including queued jobs)."""


def _freeze(value: Any) -> Any:
    """Recursively freeze supported settings AND cooked output values.

    Arrays are copied into immutable bytes-backed storage: unlike setting the
    writeable flag on an owning NumPy array, consumers cannot simply turn that
    flag back on. This is intentionally conservative and costs a copy.

    Custom result types should implement a separate immutable value type or
    extend this function with a domain-specific freezing rule.
    """
    if isinstance(value, Node):
        return value  # Graph edges preserve node identity.
    if value is None or isinstance(value, (bool, int, float, complex, str, bytes,
                                          Enum, PurePath)):
        return value
    if isinstance(value, np.generic):
        if value.dtype.hasobject:
            raise TypeError("Object-dtype NumPy scalars are not supported")
        return value
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise TypeError("Object-dtype arrays cannot be frozen safely")
        # bytes is immutable, including its backing buffer.
        return np.frombuffer(value.tobytes(order="C"), dtype=value.dtype).reshape(value.shape)
    if isinstance(value, Mapping):
        return MappingProxyType({ _freeze(k): _freeze(v) for k, v in value.items() })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    raise TypeError(
        f"Unsupported mutable/unknown value type {type(value).__name__}; "
        "provide a supported immutable value instead"
    )


def _editor_copy(value: Any) -> Any:
    """Return a detached, user-editable copy without cloning graph nodes."""
    if isinstance(value, Node):
        return value
    if isinstance(value, np.ndarray):
        return value.copy()
    if isinstance(value, Mapping):
        return {k: _editor_copy(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_editor_copy(v) for v in value)
    if isinstance(value, frozenset):
        return set(_editor_copy(v) for v in value)
    return value


@dataclass(frozen=True)
class Event:
    kind: str
    revision: int
    evaluation_id: str | None = None
    node_id: str | None = None
    node_name: str | None = None
    frame: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "details", _freeze(self.details))


class EventBus:
    """Thread-safe FIFO mailbox. Consume it exclusively on the UI thread."""

    def __init__(self):
        self._queue: SimpleQueue[Event] = SimpleQueue()

    def publish(self, event: Event) -> None:
        self._queue.put(event)

    def drain(self, limit: int = 100) -> list[Event]:
        results = []
        for _ in range(limit):
            try:
                results.append(self._queue.get_nowait())
            except Empty:
                break
        return results


class Node(ABC):
    """Base class for user-defined operators.

    ``compute()`` is the only computation hook. Mutable bindings belong to
    Graph; compute() receives the *snapshot* bindings for its evaluation.

    For class-defined nodes, declare ``input_ports`` for ports that must
    remain connectable even when initially unconnected::

        class Blend(Node):
            input_ports = {"source"}

            def __init__(self, source=None):
                super().__init__(source=source)

            def compute(self, source, ctx):
                return ctx.cook(source)

    For backwards compatibility, Node-valued initial settings are also
    recognized as input ports when no explicit port list is provided.
    """

    input_ports: ClassVar[frozenset[str] | set[str]] = frozenset()
    operator_name: ClassVar[str | None] = None

    def __init__(self, **settings: Any):
        self.id = uuid4().hex
        self.name = self.operator_name or type(self).__name__

        declared = frozenset(self.input_ports)
        inferred = frozenset(
            name for name, value in settings.items() if isinstance(value, Node)
        )
        # Include connected node-valued bindings even for legacy definitions
        # that only partially declare their ports.
        self.input_names = declared | inferred
        settings = dict(settings)
        for name in self.input_names:
            settings.setdefault(name, None)
            if settings[name] is not None and not isinstance(settings[name], Node):
                raise TypeError(f"Input {name!r} must be a Node or None")
        self._defaults = _freeze(settings)

    @abstractmethod
    def compute(self, *, ctx: Context, **bindings: Any) -> Any:
        """Compute the node's output using snapshot bindings and context.

        Subclasses can declare named arguments instead of **bindings, e.g.
        ``def compute(self, size, ctx): ...``.
        """
        raise NotImplementedError

    def create(self, **overrides: Any) -> Node:
        """Instantiate another independent node of the same operator type.

        Works for @cook-generated nodes and user subclasses whose __init__
        accepts the bound parameter and input names as keyword arguments.
        """
        settings = {name: _editor_copy(value)
                    for name, value in self._defaults.items()}
        settings.update(overrides)
        return type(self)(**settings)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name}, {self.id[:8]})"


def cook(_func: Callable[..., Any] | None = None, **settings: Any):
    """Define an operator using a function (syntactic sugar for a Node class).

    Examples::

        @cook(size=5)
        def cube(size, ctx): ...

        @cook(source=cube)
        def blend(source, ctx): ...

        another_cube = cube.create(size=10)

    The returned object is a real Node instance; ``type(cube)`` is its
    generated operator class. Both class-defined and decorated nodes use
    exactly the same Graph and Engine execution path.
    """
    def decorator(func: Callable[..., Any]) -> Node:
        @wraps(func)
        def compute(self: Node, **bindings: Any) -> Any:
            return func(**bindings)

        operator_type = type(
            f"{func.__name__}Operator",
            (Node,),
            {
                "__module__": func.__module__,
                "__doc__": func.__doc__,
                "operator_name": func.__name__,
                "input_ports": frozenset(
                    name for name, value in settings.items()
                    if isinstance(value, Node)
                ),
                "compute": compute,
                "source_function": staticmethod(func),
            },
        )
        return operator_type(**settings)

    if _func is None:
        return decorator
    if not callable(_func):
        raise TypeError("@cook expects a function")
    return decorator(_func)


@dataclass(frozen=True)
class GraphSnapshot:
    root: Node
    revision: int
    bindings: Mapping[Node, Mapping[str, Any]]


class Graph:
    def __init__(self, events: EventBus):
        self.events = events
        self.revision = 0
        self._lock = RLock()
        self._bindings: dict[Node, Mapping[str, Any]] = {}
        self._change_listeners: set[Callable[[int], None]] = set()

    def add_change_listener(self, listener: Callable[[int], None]) -> None:
        with self._lock:
            self._change_listeners.add(listener)

    def remove_change_listener(self, listener: Callable[[int], None]) -> None:
        with self._lock:
            self._change_listeners.discard(listener)

    def current_revision(self) -> int:
        with self._lock:
            return self.revision

    def _emit(self, kind: str, node: Node, **details: Any) -> None:
        """Under graph lock: maintain ordered revision/change notifications.

        Engine listeners must be quick and must not edit or snapshot the graph.
        """
        self.events.publish(Event(
            kind=kind, revision=self.revision,
            node_id=node.id, node_name=node.name, details=details,
        ))
        for listener in tuple(self._change_listeners):
            listener(self.revision)

    def _collect_new(self, root: Node) -> list[Node]:
        order: list[Node] = []
        visited: set[Node] = set()
        visiting: set[Node] = set()

        def visit(node: Node) -> None:
            if node in visiting:
                raise ValueError(f"Graph cycle involving {node!r}")
            if node in visited:
                return
            visiting.add(node)
            settings = self._bindings.get(node, node._defaults)
            for value in settings.values():
                if isinstance(value, Node):
                    visit(value)
            visiting.remove(node)
            visited.add(node)
            if node not in self._bindings:
                order.append(node)

        visit(root)
        return order

    def _add_unlocked(self, root: Node) -> None:
        for node in self._collect_new(root):
            # Values were already deeply frozen by Node.
            settings = MappingProxyType(dict(node._defaults))
            self._bindings[node] = settings
            self.revision += 1
            self._emit(
                "node_added", node,
                parameters={k: v for k, v in settings.items()
                            if k not in node.input_names},
                inputs={k: v.id if isinstance(v, Node) else None
                        for k, v in settings.items() if k in node.input_names},
            )

    def add(self, node: Node) -> None:
        with self._lock:
            self._add_unlocked(node)

    def get_bindings(self, node: Node) -> dict[str, Any]:
        with self._lock:
            return {k: _editor_copy(v) for k, v in self._bindings[node].items()}

    def _depends_on(self, start: Node, target: Node, seen=None) -> bool:
        if start is target:
            return True
        if seen is None:
            seen = set()
        if start in seen:
            return False
        seen.add(start)
        settings = self._bindings.get(start, start._defaults)
        return any(self._depends_on(v, target, seen)
                   for v in settings.values() if isinstance(v, Node))

    def set_param(self, node: Node, name: str, value: Any) -> None:
        with self._lock:
            if node not in self._bindings:
                raise KeyError(f"Node not in graph: {node!r}")
            if name not in self._bindings[node] or name in node.input_names:
                raise KeyError(f"Not a parameter: {name}")
            if isinstance(value, Node):
                raise TypeError("Use graph.connect() for node inputs")
            frozen = _freeze(value)  # Validate before changing any graph state.
            settings = dict(self._bindings[node])
            old = settings[name]
            settings[name] = frozen
            self._bindings[node] = MappingProxyType(settings)
            self.revision += 1
            self._emit("parameter_changed", node,
                       parameter=name, old=old, new=frozen)

    def connect(self, target: Node, input_name: str, source: Node) -> None:
        with self._lock:
            if target not in self._bindings:
                raise KeyError(f"Node not in graph: {target!r}")
            if input_name not in target.input_names:
                raise KeyError(f"Not an input port: {input_name}")
            if not isinstance(source, Node):
                raise TypeError("source must be a Node")
            if self._depends_on(source, target):
                raise ValueError("Connection would create a graph cycle")
            self._add_unlocked(source)
            settings = dict(self._bindings[target])
            old = settings[input_name]
            settings[input_name] = source
            self._bindings[target] = MappingProxyType(settings)
            self.revision += 1
            self._emit("connection_changed", target, input=input_name,
                       old_source_id=old.id if isinstance(old, Node) else None,
                       new_source_id=source.id)

    def disconnect(self, target: Node, input_name: str) -> None:
        with self._lock:
            if target not in self._bindings:
                raise KeyError(f"Node not in graph: {target!r}")
            if input_name not in target.input_names:
                raise KeyError(f"Not an input port: {input_name}")
            settings = dict(self._bindings[target])
            old = settings[input_name]
            settings[input_name] = None
            self._bindings[target] = MappingProxyType(settings)
            self.revision += 1
            self._emit("connection_changed", target, input=input_name,
                       old_source_id=old.id if isinstance(old, Node) else None,
                       new_source_id=None)

    def remove(self, node: Node) -> None:
        with self._lock:
            if node not in self._bindings:
                raise KeyError(f"Node not in graph: {node!r}")
            if any(value is node
                   for other, settings in self._bindings.items() if other is not node
                   for value in settings.values()):
                raise ValueError("Disconnect downstream inputs before removing node")
            del self._bindings[node]
            self.revision += 1
            self._emit("node_removed", node)

    def snapshot(self, root: Node) -> GraphSnapshot:
        """Capture a stable reachable graph; frozen values can be shared safely."""
        with self._lock:
            if root not in self._bindings:
                raise KeyError(f"Root not in graph: {root!r}")
            bindings: dict[Node, Mapping[str, Any]] = {}
            visiting: set[Node] = set()

            def visit(node: Node) -> None:
                if node in visiting:
                    raise ValueError(f"Graph cycle involving {node!r}")
                if node in bindings:
                    return
                visiting.add(node)
                settings = self._bindings[node]
                for value in settings.values():
                    if isinstance(value, Node):
                        visit(value)
                bindings[node] = settings
                visiting.remove(node)

            visit(root)
            return GraphSnapshot(root, self.revision, MappingProxyType(bindings))


@dataclass(frozen=True)
class EvaluationResult:
    evaluation_id: str
    revision: int
    value: Any


@dataclass
class _EvaluationControl:
    evaluation_id: str
    revision: int
    node: Node
    frame: int
    cancel_event: ThreadEvent = field(default_factory=ThreadEvent)
    reason: str | None = None
    completed: bool = False
    completion_status: str | None = None


@dataclass(frozen=True)
class Context:
    frame: int
    _session: "_Session" = field(repr=False)

    @property
    def evaluation_id(self) -> str:
        return self._session.control.evaluation_id

    @property
    def revision(self) -> int:
        return self._session.snapshot.revision

    def check_cancelled(self) -> None:
        """Long-running nodes should call this periodically."""
        self._session.check_cancelled()

    def cook(self, node: Node, frame: int | None = None) -> Any:
        return self._session.cook(node, self.frame if frame is None else frame)


class _Session:
    """One independent evaluation. Memo is never shared between jobs."""

    def __init__(self, snapshot: GraphSnapshot, control: _EvaluationControl,
                 events: EventBus):
        self.snapshot = snapshot
        self.control = control
        self.events = events
        self.memo: dict[tuple[Node, int], Any] = {}
        self.active: set[tuple[Node, int]] = set()

    def check_cancelled(self) -> None:
        if self.control.cancel_event.is_set():
            raise CookCancelled(self.control.reason or "Cook cancelled")

    def emit(self, kind: str, node: Node, frame: int, **details: Any) -> None:
        self.events.publish(Event(
            kind=kind, revision=self.snapshot.revision,
            evaluation_id=self.control.evaluation_id,
            node_id=node.id, node_name=node.name, frame=frame, details=details,
        ))

    def cook(self, node: Node, frame: int) -> Any:
        self.check_cancelled()
        if node not in self.snapshot.bindings:
            raise ValueError(f"Node not in evaluation snapshot: {node!r}")
        key = (node, frame)
        if key in self.memo:
            self.emit("node_cache_hit", node, frame)
            return self.memo[key]
        if key in self.active:
            raise RuntimeError(f"Recursive cook cycle: {node!r}, frame={frame}")

        self.active.add(key)
        self.emit("node_started", node, frame)
        try:
            ctx = Context(frame=frame, _session=self)
            settings = self.snapshot.bindings[node]
            # Every node sees only immutable parameter values.
            result = node.compute(**settings, ctx=ctx)
            self.check_cancelled()
            result = _freeze(result)  # Cached and returned output is immutable.
            self.check_cancelled()
            self.memo[key] = result
        except CookCancelled:
            self.emit("node_finished", node, frame, status="cancelled")
            raise
        except Exception as exc:
            self.emit("node_finished", node, frame,
                      status="error", error=str(exc))
            raise
        else:
            self.emit("node_finished", node, frame, status="ok")
            return result
        finally:
            self.active.remove(key)


class EvaluationJob:
    """Future-like job. cancel() REQUESTS cooperative cancellation.

    A queued evaluation still runs its short cancellation path so terminal
    events are always emitted; cancel() never kills running Python code.
    """

    def __init__(self, engine: "Engine", control: _EvaluationControl,
                 future: Future):
        self._engine = engine
        self._control = control
        self._future = future
        self.evaluation_id = control.evaluation_id
        self.revision = control.revision
        self.frame = control.frame

    def cancel(self, reason: str = "user") -> bool:
        return self._engine.cancel(self.evaluation_id, reason=reason)

    def done(self) -> bool:
        return self._future.done()

    def result(self, timeout: float | None = None) -> EvaluationResult:
        return self._future.result(timeout=timeout)

    def exception(self, timeout: float | None = None):
        return self._future.exception(timeout=timeout)

    def cancelled(self) -> bool:
        return self.done() and self._control.completion_status == "cancelled"


class Engine:
    def __init__(self, graph: Graph, max_workers: int = 2,
                 *, auto_cancel_on_edit: bool = True):
        self.graph = graph
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="graph-cook")
        self.auto_cancel_on_edit = auto_cancel_on_edit
        self._lock = RLock()
        self._jobs: dict[str, _EvaluationControl] = {}
        self._closed = False
        graph.add_change_listener(self._on_graph_changed)

    def _request_cancel_unlocked(self, ctl: _EvaluationControl,
                                 reason: str) -> bool:
        if ctl.completed or ctl.cancel_event.is_set():
            return False
        ctl.reason = reason
        ctl.cancel_event.set()
        self.graph.events.publish(Event(
            kind="evaluation_cancel_requested", revision=ctl.revision,
            evaluation_id=ctl.evaluation_id, node_id=ctl.node.id,
            node_name=ctl.node.name, frame=ctl.frame,
            details={"reason": reason},
        ))
        return True

    def _on_graph_changed(self, revision: int) -> None:
        if not self.auto_cancel_on_edit:
            return
        with self._lock:
            for ctl in self._jobs.values():
                if ctl.revision < revision:
                    self._request_cancel_unlocked(
                        ctl, f"graph edited (revision {revision})")

    def cancel(self, evaluation_id: str, *, reason: str = "user") -> bool:
        with self._lock:
            ctl = self._jobs.get(evaluation_id)
            return bool(ctl and self._request_cancel_unlocked(ctl, reason))

    def _run(self, snapshot: GraphSnapshot,
             ctl: _EvaluationControl) -> EvaluationResult:
        session = _Session(snapshot, ctl, self.graph.events)
        session.emit("evaluation_started", snapshot.root, ctl.frame)
        outcome = "ok"
        value = None
        error: Exception | None = None
        try:
            session.check_cancelled()
            value = session.cook(snapshot.root, ctl.frame)
            session.check_cancelled()
        except CookCancelled as exc:
            outcome, error = "cancelled", exc
        except Exception as exc:
            outcome, error = "error", exc
        finally:
            # Race-free success/cancel decision: graph edits and completion
            # acquire the same lock. Never emit cancel-request after completion.
            with self._lock:
                if outcome == "ok" and ctl.cancel_event.is_set():
                    outcome = "cancelled"
                    error = CookCancelled(ctl.reason or "Cook cancelled")
                ctl.completed = True
                ctl.completion_status = outcome
                self._jobs.pop(ctl.evaluation_id, None)

            session.emit("evaluation_finished", snapshot.root, ctl.frame,
                         status=outcome,
                         **({"error": str(error)} if error else {}))
            session.memo.clear()
            session.active.clear()

        if error is not None:
            raise error
        return EvaluationResult(ctl.evaluation_id, snapshot.revision, value)

    def submit(self, node: Node, frame: int) -> EvaluationJob:
        snapshot = self.graph.snapshot(node)
        ctl = _EvaluationControl(uuid4().hex, snapshot.revision, node, frame)
        with self._lock:
            if self._closed:
                raise RuntimeError("Engine is shut down")
            self._jobs[ctl.evaluation_id] = ctl
            try:
                future = self.executor.submit(self._run, snapshot, ctl)
            except Exception:
                self._jobs.pop(ctl.evaluation_id, None)
                raise

        # Catch edits that occurred between snapshot() and job registration.
        if self.auto_cancel_on_edit and self.graph.current_revision() > ctl.revision:
            self.cancel(ctl.evaluation_id,
                        reason="graph changed before evaluation was registered")
        return EvaluationJob(self, ctl, future)

    def cook(self, node: Node, frame: int) -> EvaluationResult:
        """Synchronous evaluation on the calling thread (not a pool worker)."""
        snapshot = self.graph.snapshot(node)
        ctl = _EvaluationControl(uuid4().hex, snapshot.revision, node, frame)
        with self._lock:
            if self._closed:
                raise RuntimeError("Engine is shut down")
            self._jobs[ctl.evaluation_id] = ctl
        if self.auto_cancel_on_edit and self.graph.current_revision() > ctl.revision:
            self.cancel(ctl.evaluation_id,
                        reason="graph changed before evaluation was registered")
        return self._run(snapshot, ctl)

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            for ctl in self._jobs.values():
                self._request_cancel_unlocked(ctl, "engine shutdown")
        self.graph.remove_change_listener(self._on_graph_changed)
        self.executor.shutdown(wait=wait)


class UIStatusTracker:
    """UI-thread-only event reducer with per-evaluation, per-frame status.

    Selecting a newer evaluation prevents old (even same-revision) work from
    overwriting visible node statuses. Event history stays available in tasks.
    """

    def __init__(self):
        self.tasks: dict[tuple[str, str, int], str] = {}
        self.evaluations: dict[str, tuple[int, str]] = {}
        self.selected_evaluation_id: str | None = None
        self.selected_revision: int | None = None

    def select(self, job: EvaluationJob) -> None:
        self.selected_evaluation_id = job.evaluation_id
        self.selected_revision = job.revision
        self.evaluations.setdefault(job.evaluation_id, (job.revision, "queued"))

    def invalidate_selection(self) -> None:
        self.selected_evaluation_id = None
        self.selected_revision = None

    def apply(self, event: Event) -> None:
        eid = event.evaluation_id
        if eid is None:
            return
        if event.kind == "evaluation_started":
            current = self.evaluations.get(eid)
            state = "cancelling" if current and current[1] == "cancelling" else "running"
            self.evaluations[eid] = (event.revision, state)
        elif event.kind == "evaluation_cancel_requested":
            self.evaluations[eid] = (event.revision, "cancelling")
        elif event.kind == "evaluation_finished":
            self.evaluations[eid] = (event.revision, event.details["status"])
        if event.node_id is None or event.frame is None:
            return
        key = (eid, event.node_id, event.frame)
        if event.kind == "node_started":
            self.tasks[key] = "running"
        elif event.kind == "node_finished":
            self.tasks[key] = event.details["status"]
        elif event.kind == "node_cache_hit":
            self.tasks.setdefault(key, "ok")

    def status(self, node_id: str, current_revision: int) -> str:
        eid = self.selected_evaluation_id
        if eid is None or self.selected_revision != current_revision:
            return "Idle"
        states = [value for (job, node, _frame), value in self.tasks.items()
                  if job == eid and node == node_id]
        if not states:
            return "Idle"
        if "running" in states:
            current = self.evaluations.get(eid)
            if current and current[1] == "cancelling":
                return "Cancelling"
            count = sum(s == "running" for s in states)
            return f"Cooking ({count} active)"
        if "error" in states:
            return "Error"
        if "cancelled" in states:
            return "Cancelled"
        return f"Done ({len(states)} frame{'s' if len(states) != 1 else ''})"

    def prune(self, keep_evaluation_ids: set[str]) -> None:
        """Discard older history without changing the selected evaluation."""
        self.tasks = {key: value for key, value in self.tasks.items()
                      if key[0] in keep_evaluation_ids}
        self.evaluations = {key: val for key, val in self.evaluations.items()
                            if key in keep_evaluation_ids}


if __name__ == "__main__":
    import time

    @cook(size=5)
    def animated_cube(size, ctx):
        time.sleep(0.04)
        ctx.check_cancelled()
        return np.array([[0., 0., 0.], [size, 0., 0.], [0., size, 0.]]) + ctx.frame * .1

    @cook(source=animated_cube)
    def blend(source, ctx):
        return (.25 * ctx.cook(source, ctx.frame - 1)
                + .5 * ctx.cook(source, ctx.frame)
                + .25 * ctx.cook(source, ctx.frame + 1))

    bus = EventBus()
    graph = Graph(bus)
    graph.add(blend)
    engine = Engine(graph, max_workers=2)
    try:
        first = engine.submit(blend, frame=100)
        graph.set_param(animated_cube, "size", 10)  # Cancels first.
        second = engine.submit(blend, frame=100)
        print("Result revision", second.result().revision)
        try:
            first.result()
        except CookCancelled as exc:
            print("Previous evaluation cancelled:", exc)
        print("Events:", [ev.kind for ev in bus.drain(1000)])
    finally:
        engine.shutdown()
