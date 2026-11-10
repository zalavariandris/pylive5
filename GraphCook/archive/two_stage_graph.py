"""A small node graph with genuinely separate request and compute stages.

Only NumPy is required: pip install numpy

Run: python two_stage_graph.py

A Context restricts the output the consumer wants. request(ctx) transforms
that demand for each upstream input; compute() receives *already computed*
inputs. Context.current() is optional during compute().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, ClassVar, Callable, Iterable
import numpy as np


@dataclass(frozen=True)
class Context:
    # None means all available frames; empty set means no frames.
    frames: frozenset[int] | None = None

    _current: ClassVar[ContextVar["Context | None"]] = ContextVar(
        "current_output_context", default=None
    )

    def __post_init__(self):
        if self.frames is not None:
            object.__setattr__(self, "frames", frozenset(self.frames))

    def with_frames(self, frames: Iterable[int] | None) -> "Context":
        return Context(None if frames is None else frozenset(frames))

    def union(self, other: "Context") -> "Context":
        if self.frames is None or other.frames is None:
            return Context()  # full-frame request takes precedence
        return Context(self.frames | other.frames)

    @classmethod
    def current(cls) -> "Context":
        result = cls._current.get()
        if result is None:
            raise RuntimeError("Context.current() is only available during compute()")
        return result

    def __str__(self):
        return "frames=ALL" if self.frames is None else f"frames={sorted(self.frames)}"


@dataclass
class Video:
    frames: dict[int, np.ndarray] = field(default_factory=dict)


class Node(ABC):
    """Operator instance. Node references are graph edges; others are parameters."""

    def __init__(self, **bindings: Any):
        self.inputs: dict[str, Node] = {
            name: value for name, value in bindings.items() if isinstance(value, Node)
        }
        self.params: dict[str, Any] = {
            name: value for name, value in bindings.items() if not isinstance(value, Node)
        }
        self.name = type(self).__name__

    def request(self, ctx: Context) -> dict[str, Context]:
        """Optional: override an input's default request (which is `ctx`)."""
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> Any:
        """Compute once, after all upstream inputs are available."""
        raise NotImplementedError


def operator(func: Callable[..., Any]) -> type[Node]:
    """Syntactic sugar: turn a function into an ordinary Node subclass."""

    def compute(self: Node, **bindings: Any) -> Any:
        return func(**bindings)

    return type(
        func.__name__,
        (Node,),
        {"__module__": func.__module__, "__doc__": func.__doc__, "compute": compute},
    )


@dataclass(frozen=True)
class Plan:
    # Upstream-first order; reversing it gives downstream-first planning.
    order: tuple[Node, ...]
    requests: dict[Node, Context]


class Planner:
    def build(self, root: Node, wanted: Context) -> Plan:
        # 1. Determine static topological order and reject wiring cycles.
        order: list[Node] = []
        visiting: set[Node] = set()
        visited: set[Node] = set()

        def visit(node: Node) -> None:
            if node in visiting:
                raise ValueError(f"Graph cycle involving {node.name}")
            if node in visited:
                return
            visiting.add(node)
            for upstream in node.inputs.values():
                visit(upstream)
            visiting.remove(node)
            visited.add(node)
            order.append(node)

        visit(root)

        # 2. Propagate requests in REVERSE topological order.
        # If multiple consumers need the same node, merge their frame sets
        # BEFORE calling that node's request() once.
        required: dict[Node, Context] = {root: wanted}
        print("\n=== REQUEST / PLANNING (downstream -> upstream) ===")
        for node in reversed(order):
            output_ctx = required[node]
            input_requests = node.request(output_ctx)
            extra_ports = set(input_requests) - set(node.inputs)
            if extra_ports:
                raise ValueError(
                    f"{node.name}.request() named unconnected ports: {sorted(extra_ports)}"
                )

            print(f"REQUEST {node.name:18} output {output_ctx}")
            for port, upstream in node.inputs.items():
                input_ctx = input_requests.get(port, output_ctx)
                if not isinstance(input_ctx, Context):
                    raise TypeError(f"{node.name}.request({port!r}) must return Context")
                print(f"        {port:18} -> {upstream.name:18} {input_ctx}")
                required[upstream] = (
                    required[upstream].union(input_ctx)
                    if upstream in required else input_ctx
                )

        return Plan(order=tuple(order), requests=required)


class Executor:
    def execute(self, plan: Plan, root: Node) -> Any:
        # One evaluation's memo, discarded when this method returns.
        results: dict[Node, Any] = {}
        print("\n=== COMPUTE / EXECUTION (upstream -> downstream) ===")
        for node in plan.order:
            output_ctx = plan.requests[node]
            bindings = {
                **node.params,
                **{port: results[upstream] for port, upstream in node.inputs.items()},
            }
            print(f"COMPUTE {node.name:18} output {output_ctx}")
            token = Context._current.set(output_ctx)
            try:
                results[node] = node.compute(**bindings)
            finally:
                Context._current.reset(token)

        return results[root]


class Engine:
    def __init__(self):
        self.planner = Planner()
        self.executor = Executor()

    def evaluate(self, root: Node, ctx: Context) -> Any:
        plan = self.planner.build(root, ctx)
        return self.executor.execute(plan, root)


# ------------------------------------------------------------------------
# Example operators
# ------------------------------------------------------------------------

class ReadVideo(Node):
    """Self-contained source: synthesize a frame when it is requested."""

    def __init__(self, frame_count: int = 12):
        super().__init__(frame_count=frame_count)

    def compute(self, frame_count: int) -> Video:
        ctx = Context.current()  # optional optimization: only generate wanted frames
        frames = range(frame_count) if ctx.frames is None else sorted(ctx.frames)
        out = Video()
        for frame in frames:
            if not 0 <= frame < frame_count:
                continue  # outside source domain
            # Generate a visible nonuniform image, different on every frame.
            y, x = np.indices((8, 8))
            base = ((x * 17 + y * 9 + frame * 21) % 256) / 255.0
            out.frames[frame] = np.repeat(base[..., None], 3, axis=2).astype(np.float32)
        return out


class TemporalBlend(Node):
    def __init__(self, source: Node, duration: int = 3):
        if duration < 1:
            raise ValueError("duration must be >= 1")
        super().__init__(source=source, duration=duration)

    def request(self, ctx: Context) -> dict[str, Context]:
        duration = self.params["duration"]
        if ctx.frames is None:
            return {"source": ctx}  # full output requires full source
        required = {
            frame - offset
            for frame in ctx.frames
            for offset in range(duration)
        }
        return {"source": ctx.with_frames(required)}

    def compute(self, source: Video, duration: int) -> Video:
        ctx = Context.current()
        output_frames = source.frames.keys() if ctx.frames is None else ctx.frames
        result = Video()
        for frame in sorted(output_frames):
            samples = [
                source.frames[frame - offset]
                for offset in range(duration)
                if frame - offset in source.frames
            ]
            if samples:
                # Edge policy: average only available samples.
                result.frames[frame] = np.mean(np.stack(samples), axis=0)
        return result


def box_blur(image: np.ndarray, radius: int) -> np.ndarray:
    """Tiny dependency-free blur for the example, not optimized for speed."""
    if radius < 0:
        raise ValueError("radius must be >= 0")
    if radius == 0:
        return image.copy()
    h, w, channels = image.shape
    padded = np.pad(
        image, ((radius, radius), (radius, radius), (0, 0)), mode="edge"
    ).astype(np.float32)
    output = np.zeros((h, w, channels), dtype=np.float32)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            output += padded[dy:dy + h, dx:dx + w]
    return output / (2 * radius + 1) ** 2


@operator
def blur_op(source: Video, radius: int = 1) -> Video:
    """Function operator with optional use of Context.current()."""
    ctx = Context.current()
    wanted = source.frames.keys() if ctx.frames is None else ctx.frames
    return Video({f: box_blur(source.frames[f], radius)
                  for f in sorted(wanted) if f in source.frames})


@operator
def gain_op(source: Video, factor: float = 2.0) -> Video:
    """No context needed: just operate on the prepared upstream data."""
    return Video({f: pixels * factor for f, pixels in source.frames.items()})


if __name__ == "__main__":
    read = ReadVideo(frame_count=12)
    blend = TemporalBlend(source=read, duration=3)
    blur = blur_op(source=blend, radius=1)
    output = gain_op(source=blur, factor=2.0)

    result = Engine().evaluate(output, Context(frames={5}))

    print("\n=== RESULT ===")
    print("Output frames:", sorted(result.frames))  # only [5]
    print("Frame 5 shape:", result.frames[5].shape)
    print("Frame 5, pixel [0,0]:", result.frames[5][0, 0])

    print("\n=== OPTIONAL FULL OUTPUT ===")
    # Context() means all available frames; the same graph computes all of them.
    full_result = Engine().evaluate(output, Context())
    print("Total output frames:", len(full_result.frames))
