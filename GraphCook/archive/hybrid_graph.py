
from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Iterable

import numpy as np


# ==========================================================
# CONTEXT AND DATA
# ==========================================================

@dataclass(frozen=True)
class Context:
    """None means all frames; empty set means no frames."""

    frames: frozenset[int] | None = None

    def __post_init__(self):
        if self.frames is not None:
            object.__setattr__(
                self, "frames", frozenset(self.frames)
            )

    def with_frames(
        self,
        frames: Iterable[int] | None,
    ) -> Context:
        return Context(
            None if frames is None else frozenset(frames)
        )

    def union(self, other: Context) -> Context:
        if self.frames is None or other.frames is None:
            return Context()
        return Context(self.frames | other.frames)

    def __str__(self):
        if self.frames is None:
            return "ALL"
        return str(sorted(self.frames))


@dataclass
class Video:
    frames: dict[int, np.ndarray] = field(
        default_factory=dict
    )

    def select(self, ctx: Context) -> Video:
        if ctx.frames is None:
            return Video(dict(self.frames))

        return Video({
            frame: self.frames[frame]
            for frame in ctx.frames
            if frame in self.frames
        })


# ==========================================================
# NODE AND OPERATOR
# ==========================================================

class Node(ABC):
    """Primary interface for defining operators."""

    def __init__(self, **bindings: Any):
        self.name = type(self).__name__

        self.inputs = {
            key: value
            for key, value in bindings.items()
            if isinstance(value, Node)
        }

        self.params = {
            key: value
            for key, value in bindings.items()
            if not isinstance(value, Node)
        }

    def request(
        self,
        ctx: Context,
        **params: Any,
    ) -> dict[str, Context]:
        """Override upstream requests when necessary."""
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> Any:
        raise NotImplementedError


def operator(func: Callable[..., Any]) -> type[Node]:
    """Convert a function into an instantiable Node subclass."""

    def compute(self, **bindings):
        return func(**bindings)

    return type(
        func.__name__,
        (Node,),
        {
            "__module__": func.__module__,
            "__doc__": func.__doc__,
            "compute": compute,
        },
    )


# ==========================================================
# EXECUTION SCOPE
# ==========================================================

@dataclass(frozen=True)
class ExecutionScope:
    job: Job
    node: Node
    ctx: Context

    _active: ClassVar[
        ContextVar[ExecutionScope | None]
    ] = ContextVar(
        "execution_scope",
        default=None,
    )

    @classmethod
    def current(cls) -> ExecutionScope:
        scope = cls._active.get()

        if scope is None:
            raise RuntimeError(
                "No active node computation"
            )

        return scope

    def input(self, port: str) -> Node:
        """Get an upstream node from the job snapshot."""
        return self.job.snapshot[self.node][1][port]


# ==========================================================
# MEMO AND PLAN
# ==========================================================

@dataclass
class VideoCache:
    video: Video = field(default_factory=Video)

    # None = complete/unrestricted evaluation.
    covered: set[int] | None = field(
        default_factory=set
    )


@dataclass
class Plan:
    order: list[Node]
    pending: dict[Node, Context]
    input_requests: dict[
        Node, dict[str, Context]
    ]


# ==========================================================
# JOB
# ==========================================================

class Job:
    """Owns one evaluation's snapshot, planner and memo."""

    def __init__(self, engine: Engine, root: Node):
        self.engine = engine

        self.snapshot: dict[
            Node, tuple[dict, dict[str, Node]]
        ] = {}

        self._capture(root)

        self.video_cache: dict[
            Node, VideoCache
        ] = {}

        self.exact_cache: dict[
            tuple[Node, Context], Any
        ] = {}

        self.active: list[
            tuple[Node, Context]
        ] = []

    def _capture(self, node: Node)->None:
        if node in self.snapshot:
            return

        inputs = dict(node.inputs)

        self.snapshot[node] = (
            deepcopy(node.params),
            inputs,
        )

        for upstream in inputs.values():
            self._capture(upstream)

    # ------------------------------------------------------
    # CACHE
    # ------------------------------------------------------

    def _missing(
        self,
        node: Node,
        ctx: Context,
    ) -> Context | None:

        if (node, ctx) in self.exact_cache:
            return None

        cache = self.video_cache.get(node)

        if cache is None:
            return ctx

        if cache.covered is None:
            return None

        if ctx.frames is None:
            return ctx

        missing = ctx.frames - cache.covered

        return Context(missing) if missing else None

    def _cached(self, node: Node, ctx: Context):
        key = (node, ctx)

        if key in self.exact_cache:
            return self.exact_cache[key]

        cache = self.video_cache.get(node)

        if cache is not None and (
            cache.covered is None
            or (
                ctx.frames is not None
                and ctx.frames <= cache.covered
            )
        ):
            return cache.video.select(ctx)

        raise RuntimeError(
            f"Result not available: {node.name} {ctx}"
        )

    def _store(
        self,
        node: Node,
        ctx: Context,
        result: Any,
    ):
        if not isinstance(result, Video):
            self.exact_cache[(node, ctx)] = result
            return

        cache = self.video_cache.setdefault(
            node, VideoCache()
        )

        if ctx.frames is None:
            cache.video = Video(dict(result.frames))
            cache.covered = None
        else:
            cache.video.frames.update(
                result.select(ctx).frames
            )

            if cache.covered is not None:
                cache.covered.update(ctx.frames)

    # ------------------------------------------------------
    # RECURSIVE EVALUATION SAFETY
    # ------------------------------------------------------

    def _check_recursive(
        self,
        node: Node,
        ctx: Context,
    ):
        for active_node, active_ctx in self.active:
            if active_node is not node:
                continue

            overlap = (
                active_ctx.frames is None
                or ctx.frames is None
                or bool(
                    active_ctx.frames & ctx.frames
                )
            )

            if overlap:
                raise RuntimeError(
                    "Recursive overlapping cook: "
                    f"{node.name}: {ctx} vs {active_ctx}"
                )

    # ------------------------------------------------------
    # STAGE 1: REQUEST PLANNING
    # ------------------------------------------------------

    def _plan(
        self,
        root: Node,
        ctx: Context,
    ) -> Plan:

        order: list[Node] = []
        visiting: set[Node] = set()
        visited: set[Node] = set()

        def visit(node: Node):
            if node in visiting:
                raise ValueError(
                    f"Graph cycle at {node.name}"
                )

            if node in visited:
                return

            if node not in self.snapshot:
                raise ValueError(
                    "Node outside the job snapshot"
                )

            visiting.add(node)

            for upstream in self.snapshot[node][1].values():
                visit(upstream)

            visiting.remove(node)
            visited.add(node)
            order.append(node)

        visit(root)

        # Collect requirements, starting downstream.
        needed = {root: ctx}

        pending: dict[Node, Context] = {}
        input_requests: dict[
            Node, dict[str, Context]
        ] = {}

        print(f"\nPLAN {root.name} {ctx}")

        for node in reversed(order):
            if node not in needed:
                continue

            missing = self._missing(
                node, needed[node]
            )

            if (
                missing is None
                or missing.frames == frozenset()
            ):
                print(
                    f"  REUSE {node.name} "
                    f"{needed[node]}"
                )
                continue

            self._check_recursive(node, missing)

            pending[node] = missing

            params, inputs = self.snapshot[node]

            # Operators can transform input requirements.
            overrides = node.request(
                missing, **params
            )

            if (
                not isinstance(overrides, dict)
                or set(overrides) - set(inputs)
            ):
                raise ValueError(
                    f"Invalid request ports from {node.name}"
                )

            input_requests[node] = {}

            print(
                f"  REQUEST {node.name} {missing}"
            )

            for port, upstream in inputs.items():
                upstream_ctx = overrides.get(
                    port, missing
                )

                if not isinstance(
                    upstream_ctx, Context
                ):
                    raise TypeError(
                        "request() must return Context values"
                    )

                input_requests[node][port] = (
                    upstream_ctx
                )

                # Merge requests from multiple consumers.
                if upstream in needed:
                    needed[upstream] = (
                        needed[upstream].union(
                            upstream_ctx
                        )
                    )
                else:
                    needed[upstream] = upstream_ctx

                print(
                    f"    {port} -> "
                    f"{upstream.name} {upstream_ctx}"
                )

        return Plan(
            order,
            pending,
            input_requests,
        )

    # ------------------------------------------------------
    # STAGE 2: COMPUTATION
    # ------------------------------------------------------

    def evaluate(
        self,
        node: Node,
        ctx: Context,
    ):
        if node not in self.snapshot:
            raise ValueError(
                "Node outside this job's snapshot"
            )

        self._check_recursive(node, ctx)

        if self._missing(node, ctx) is None:
            print(f"CACHE HIT {node.name} {ctx}")
            return self._cached(node, ctx)

        # Plan missing computation.
        plan = self._plan(node, ctx)

        print("EXECUTE")

        for item in plan.order:
            if item not in plan.pending:
                continue

            output_ctx = plan.pending[item]

            self._check_recursive(
                item, output_ctx
            )

            params, inputs = self.snapshot[item]

            # Inject evaluated inputs and parameters.
            bindings = dict(params)

            for port, upstream in inputs.items():
                bindings[port] = self._cached(
                    upstream,
                    plan.input_requests[item][port],
                )

            # Activate ambient scope during compute.
            scope = ExecutionScope(
                job=self,
                node=item,
                ctx=output_ctx,
            )

            token = ExecutionScope._active.set(
                scope
            )

            self.active.append(
                (item, output_ctx)
            )

            try:
                print(
                    f"  COMPUTE {item.name} "
                    f"{output_ctx}"
                )

                # May trigger on-demand evaluation.
                result = item.compute(**bindings)

                # Store partial result in same memo.
                self._store(
                    item, output_ctx, result
                )

            finally:
                self.active.pop()
                ExecutionScope._active.reset(
                    token
                )

        return self._cached(node, ctx)


# ==========================================================
# ENGINE
# ==========================================================

class Engine:
    """Creates one job per external evaluation."""

    def evaluate(
        self,
        node: Node,
        ctx: Context,
    ):
        return Job(self, node).evaluate(node, ctx)


# ==========================================================
# EXAMPLE OPERATORS
# ==========================================================

class ReadVideo(Node):

    def __init__(self, frame_count=12):
        super().__init__(
            frame_count=frame_count
        )

    def compute(self, frame_count: int) -> Video:
        ctx = ExecutionScope.current().ctx

        frames = (
            range(frame_count)
            if ctx.frames is None
            else sorted(ctx.frames)
        )

        return Video({
            f: np.full(
                (2, 2, 3),
                float(f),
                dtype=np.float32,
            )
            for f in frames
            if 0 <= f < frame_count
        })


class TemporalBlend(Node):

    def __init__(
        self,
        source: Node,
        duration=3,
    ):
        super().__init__(
            source=source,
            duration=duration,
        )

    def request(
        self,
        ctx: Context,
        duration: int,
    ):
        if duration < 1:
            raise ValueError(
                "duration must be >= 1"
            )

        if ctx.frames is None:
            return {"source": ctx}

        return {
            "source": ctx.with_frames(
                f - delta
                for f in ctx.frames
                for delta in range(duration)
            )
        }

    def compute(
        self,
        source: Video,
        duration: int,
    ) -> Video:
        ctx = ExecutionScope.current().ctx

        frames = (
            source.frames
            if ctx.frames is None
            else ctx.frames
        )

        result = Video()

        for frame in frames:
            samples = [
                source.frames[frame - delta]
                for delta in range(duration)
                if frame - delta in source.frames
            ]

            if samples:
                result.frames[frame] = np.mean(
                    np.stack(samples),
                    axis=0,
                )

        return result


@operator
def DynamicLookback(
    source: Video,
    lookback: int = 1,
) -> Video:

    scope = ExecutionScope.current()
    output = Video()

    frames = (
        source.frames
        if scope.ctx.frames is None
        else scope.ctx.frames
    )

    for frame in frames:
        previous_frame = frame - lookback

        # Evaluate the actual input node on demand.
        older = scope.job.evaluate(
            scope.input("source"),
            scope.ctx.with_frames({
                previous_frame
            }),
        )

        if (
            frame in source.frames
            and previous_frame in older.frames
        ):
            output.frames[frame] = (
                source.frames[frame]
                + older.frames[previous_frame]
            ) / 2

    return output


@operator
def Gain(
    source: Video,
    factor: float = 2.0,
) -> Video:
    # Ordinary computation: context is not needed.
    return Video({
        f: image * factor
        for f, image in source.frames.items()
    })


# ==========================================================
# EXAMPLE GRAPH
# ==========================================================

if __name__ == "__main__":

    read = ReadVideo(frame_count=12)

    planned_blend = TemporalBlend(
        source=read,
        duration=3,
    )

    dynamic = DynamicLookback(
        source=planned_blend,
        lookback=1,
    )

    output = Gain(
        source=dynamic,
        factor=2.0,
    )

    engine = Engine()

    result = engine.evaluate(
        output,
        Context(frames={5}),
    )

    print("\nRESULT")

    for frame, image in result.frames.items():
        print(
            frame,
            image[0, 0, 0],
        )
