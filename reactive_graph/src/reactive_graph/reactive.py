"""Lazy, pull-based reactive composition with asynchronous evaluation.

Python 3.10+. No third-party dependencies.

@reactive calls construct nodes. When a reactive function calls other reactive
functions, those children are memoized by the *parent node* and their inputs.
Only an active @effect pulls frames/computations through the graph.

Run effects from within an asyncio event loop. Signal assignments schedule
re-evaluation automatically; await effect.idle() to wait for the latest render.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from inspect import isawaitable
from itertools import count
from time import perf_counter
from typing import Any, Callable


_ids = count(1)
_current: ContextVar[Computed | Effect | None] = ContextVar("reactive_current", default=None)
_stack: ContextVar[tuple[int, ...]] = ContextVar("reactive_stack", default=())


@dataclass(frozen=True)
class Event:
    kind: str
    node: str
    id: int
    detail: str = ""
    elapsed_ms: float | None = None


class ExecutionTrace:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def clear(self) -> None:
        self.events.clear()

    def add(self, kind: str, node: Any, detail: str = "", elapsed_ms: float | None = None) -> None:
        if not detail and isinstance(node, Computed):
            detail = node.input_summary
        self.events.append(Event(kind, node.name, node.id, detail, elapsed_ms))

    def format(self) -> str:
        return "\n".join(
            f"{entry.kind:8} {entry.node:<23} #{entry.id}"
            + (f" [{entry.detail}]" if entry.detail else "")
            + (f" ({entry.elapsed_ms:.1f} ms)" if entry.elapsed_ms is not None else "")
            for entry in self.events
        )


trace = ExecutionTrace()


def _track(source: Signal | Computed) -> None:
    observer = _current.get()
    if observer is not None and observer is not source:
        source.users.add(observer)
        observer.deps.add(source)


def _cleanup(observer: Computed | Effect) -> None:
    for dependency in tuple(observer.deps):
        dependency.users.discard(observer)
    observer.deps.clear()


def _same_value(old: Any, new: Any) -> bool:
    if old is new:
        return True
    try:
        result = old == new
    except (TypeError, ValueError):
        return False
    return isinstance(result, bool) and result


class Signal:
    def __init__(self, value: Any, *, name: str | None = None) -> None:
        self.id = next(_ids)
        self.name = name or f"edit_{self.id}"
        self._value = value
        self.users: set[Computed | Effect] = set()

    @property
    def value(self) -> Any:
        _track(self)
        return self._value

    @value.setter
    def value(self, new: Any) -> None:
        if _same_value(self._value, new):
            return
        self._value = new
        self.notify()

    def notify(self) -> None:
        """Notify watchers after in-place mutation of a signal's value."""
        for user in tuple(self.users):
            user.invalidate()


def edit(value: Any, *, name: str | None = None) -> Signal:
    return Signal(value, name=name)


def _arg_key(value: Any) -> tuple[Any, ...]:
    """Stable keys for primitive values and node identities; other values by identity.

    Do not hash numpy arrays or mutable OpenCV handles by value.
    """
    if value is None or type(value) in (bool, int, float, str, bytes):
        return (type(value), value)
    if isinstance(value, (Signal, Computed)):
        return (type(value), value.id)
    if isinstance(value, tuple):
        return (tuple, tuple(_arg_key(x) for x in value))
    return (type(value), id(value))


def _node_key(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, ...]:
    return (fn, tuple(_arg_key(a) for a in args),
            tuple((k, _arg_key(v)) for k, v in sorted(kwargs.items())))


def _show_input(value: Any) -> str:
    if isinstance(value, (Computed, Signal)):
        return f"{value.name}#{value.id}"
    if value is None or type(value) in (bool, int, float, str, bytes):
        s = repr(value)
        return s if len(s) <= 36 else s[:33] + "..."
    return type(value).__name__


async def _resolve(value: Any) -> Any:
    """Flatten returned nodes, including nodes returned by other nodes."""
    while True:
        if isinstance(value, Signal):
            value = value.value
        elif isinstance(value, Computed):
            value = await value.get()
        elif isawaitable(value):
            value = await value
        else:
            return value


class Computed:
    def __init__(self, fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]):
        self.id = next(_ids)
        self.name = fn.__name__
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.input_summary = ", ".join(
            [*(_show_input(arg) for arg in args),
             *(f"{key}={_show_input(val)}" for key, val in kwargs.items())]
        )
        self.users: set[Computed | Effect] = set()
        self.deps: set[Signal | Computed] = set()
        self.children: dict[tuple[Any, ...], Computed] = {}
        self._used: set[tuple[Any, ...]] = set()
        self._dirty = True
        self._generation = 0
        self._cache: Any = None
        self.execution_count = 0
        self.cache_hits = 0

    def invalidate(self) -> None:
        self._generation += 1
        self._dirty = True
        # Always propagate. A node can be invalidated while it is computing.
        for user in tuple(self.users):
            user.invalidate()

    async def get(self) -> Any:
        if self.id in _stack.get():
            raise RuntimeError(f"Reactive cycle detected in {self.name!r}")
        _track(self)
        if not self._dirty:
            self.cache_hits += 1
            trace.add("cached", self)
            return self._cache

        started = perf_counter()
        generation = self._generation
        self._used = set()
        _cleanup(self)
        token_observer = _current.set(self)
        token_stack = _stack.set((*_stack.get(), self.id))
        try:
            args = [await _resolve(x) for x in self.args]
            kwargs = {key: await _resolve(x) for key, x in self.kwargs.items()}
            result = self.fn(*args, **kwargs)
            result = await _resolve(result)
            # If inputs changed while the function awaited, never cache a stale result.
            if generation != self._generation:
                raise _Superseded()
        except BaseException:
            # Failed/cancelled nodes remain dirty so a later pull can retry.
            self._dirty = True
            raise
        else:
            self._cache = result
            self._dirty = False
            self.execution_count += 1
            trace.add("execute", self, elapsed_ms=(perf_counter() - started) * 1000)
            # Keep only child calls made during the latest successful evaluation.
            # This is NOT an unbounded cache of previously visited video frames.
            for key in tuple(self.children):
                if key not in self._used:
                    old = self.children.pop(key)
                    _detach_subgraph(old)
            return result
        finally:
            _stack.reset(token_stack)
            _current.reset(token_observer)


def _detach_subgraph(node: Computed) -> None:
    """Release dependencies from child nodes no longer called by their parent."""
    if node.users:
        return  # still referenced by an active graph branch
    _cleanup(node)
    for child in node.children.values():
        _detach_subgraph(child)


class _Superseded(Exception):
    pass


def reactive(fn: Callable[..., Any]) -> Callable[..., Computed]:
    """Build a node; nested @reactive calls are memoized within their parent."""
    @wraps(fn)
    def construct(*args: Any, **kwargs: Any) -> Computed:
        parent = _current.get()
        if isinstance(parent, Computed):
            key = _node_key(fn, args, kwargs)
            parent._used.add(key)
            if key in parent.children:
                return parent.children[key]
            child = Computed(fn, args, kwargs)
            parent.children[key] = child
            return child
        return Computed(fn, args, kwargs)
    return construct


class Effect:
    def __init__(self, fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]):
        self.id = next(_ids)
        self.name = fn.__name__
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.deps: set[Signal | Computed] = set()
        self.active = False
        self._task: asyncio.Task[None] | None = None
        self._revision = 0
        self._error: BaseException | None = None
        self.execution_count = 0

    def start(self) -> Effect:
        asyncio.get_running_loop()  # fail clearly if run() is outside async main
        if not self.active:
            self.active = True
            self.invalidate()
        return self

    def invalidate(self) -> None:
        if not self.active:
            return
        self._revision += 1
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._execute(self._revision))

    async def _execute(self, revision: int) -> None:
        started = perf_counter()
        _cleanup(self)
        token = _current.set(self)
        # New effect tasks must not inherit a parent computation's cycle stack.
        stack_token = _stack.set(())
        self._error = None
        try:
            args = [await _resolve(x) for x in self.args]
            kwargs = {key: await _resolve(x) for key, x in self.kwargs.items()}
            # No awaited work occurred since we last checked? Good: we own this turn.
            if revision != self._revision or not self.active:
                return
            await _resolve(self.fn(*args, **kwargs))
            if revision == self._revision:
                self.execution_count += 1
                trace.add("effect", self, elapsed_ms=(perf_counter() - started) * 1000)
        except asyncio.CancelledError:
            return
        except _Superseded:
            # An edit normally has already scheduled the replacement effect.
            return
        except BaseException as exc:
            if revision == self._revision:
                self._error = exc
        finally:
            _stack.reset(stack_token)
            _current.reset(token)

    async def idle(self) -> None:
        """Wait until the latest scheduled rendering completes (or raises)."""
        while self._task is not None:
            task = self._task
            await asyncio.shield(task)
            if task is self._task:
                if self._error is not None:
                    raise self._error
                return

    def dispose(self) -> None:
        self.active = False
        self._revision += 1
        if self._task is not None and not self._task.done():
            self._task.cancel()
        _cleanup(self)


def effect(fn: Callable[..., Any]) -> Callable[..., Effect]:
    @wraps(fn)
    def construct(*args: Any, **kwargs: Any) -> Effect:
        return Effect(fn, args, kwargs)
    return construct


def run(target: Effect) -> Effect:
    if not isinstance(target, Effect):
        raise TypeError("run expects output(node), with output decorated by @effect")
    return target.start()


def to_dot(root: Effect | Computed | Signal) -> str:
    """Export observed, executed dependencies; evaluate first to populate the graph."""
    lines = ["digraph reactive {", "  rankdir=LR;"]
    visited: set[int] = set()

    def walk(node: Effect | Computed | Signal) -> None:
        if node.id in visited:
            return
        visited.add(node.id)
        shape = "doubleoctagon" if isinstance(node, Effect) else "box" if isinstance(node, Signal) else "ellipse"
        label = node.name.replace('"', '\\"')
        lines.append(f'  n{node.id} [label="{label} #{node.id}", shape={shape}];')
        for dep in sorted(getattr(node, "deps", ()), key=lambda child: child.id):
            walk(dep)
            lines.append(f"  n{dep.id} -> n{node.id};")

    walk(root)
    lines.append("}")
    return "\n".join(lines)
