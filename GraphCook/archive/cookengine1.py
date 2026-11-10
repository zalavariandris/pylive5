
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, replace
import logging
from typing import Any, Callable

import numpy as np


@dataclass(frozen=True)
class Context:
    frame: int

class Node(ABC):
    @abstractmethod
    def compute(self, ctx: Context) -> Any:
         raise NotImplementedError


@dataclass
class _CookSession:
    memo: dict
    active: set

from threading import Lock
@dataclass(frozen=True)
class CookEvent:
    node: Node
    frame: int
    error: Exception | None = None

class Engine:
    _current: ContextVar["Engine | None"] = ContextVar(
        "current_engine", default=None
    )

    def __init__(self):
        self._session: ContextVar[_CookSession | None] = (
            ContextVar("cook_session", default=None)
        )
        self._listeners = {
            "cook_started": [],
            "cook_finished": [],
        }
        self._listeners_lock = Lock()

    @classmethod
    def current(cls) -> "Engine":
        engine = cls._current.get()

        if engine is None:
            raise RuntimeError("No active cooking engine")

        return engine

    def cook(self, node: Node, context: Context):
        engine_token = self._current.set(self)

        try:
            session = self._session.get()

            if session is None:
                session = _CookSession(memo={}, active=set())
                token = self._session.set(session)

                try:
                    return self._cook(node, context, session)
                finally:
                    self._session.reset(token)

            return self._cook(node, context, session)

        finally:
            self._current.reset(engine_token)

    def on(self, event_name: str, callback: Callable):
        with self._listeners_lock:
            self._listeners[event_name].append(callback)

    def emit(self, event_name: str, event: CookEvent):
        with self._listeners_lock:
            listeners = tuple(self._listeners[event_name])

        for callback in listeners:
            try:
                callback(event)
            except Exception:
                logging.exception("Cook event listener failed")

    def _cook(
        self,
        node: Node,
        context: Context,
        session: _CookSession,
    ):
        key = (node, context.frame)

        if key in session.memo:
            print(
                f"CACHE HIT: {type(node).__name__}"
                f" frame={context.frame}"
            )
            return session.memo[key]

        if key in session.active:
            raise RuntimeError(
                f"Cyclic cook dependency: "
                f"{type(node).__name__} frame={context.frame}"
            )

        print(
            f"COOK: {type(node).__name__}"
            f" frame={context.frame}"
        )

        session.active.add(key)

        try:
            result = node.compute(context)
            session.memo[key] = result
            return result
        finally:
            session.active.remove(key)


class AnimatedTriangleNode(Node):
    def __init__(self):
        super().__init__()

    def compute(self, ctx: Context):
        points = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.5, 1.0, 0.0],
        ])

        points[:, 0] += ctx.frame * 0.1
        return points


class TemporalBlendNode(Node):
    def __init__(self, source: Node):
        self.source = source

    def compute(self, ctx: Context):
        frame = ctx.frame

        previous =  Engine.current().cook(self.source, replace(ctx, frame=frame - 1))
        current =   Engine.current().cook(self.source, replace(ctx, frame=frame))
        following = Engine.current().cook(self.source, replace(ctx, frame=frame + 1))

        return (
            previous * 0.25
            + current * 0.50
            + following * 0.25
        )


if __name__ == "__main__":
    engine = Engine()

    source = AnimatedTriangleNode()
    blend = TemporalBlendNode(source)

    print("FIRST EVALUATION")
    result = engine.cook(blend, Context(frame=100))
    print(result)

    print("\nSECOND EVALUATION")
    result = engine.cook(blend, Context(frame=100))
    print(result)
