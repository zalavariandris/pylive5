"""Run `python example.py` from this directory."""
from dataclasses import dataclass

from graph import Node, ObservableGraph
from base_engine import DictOperatorProvider, OperatorHandle
from eager_engine import EagerEngine
from hybrid_engine import HybridEngine


# ------------------ eager graph ------------------
add = OperatorHandle("add")
double = OperatorHandle("double")
provider = DictOperatorProvider({add: lambda a, b: a + b,
                                 double: lambda source: source * 2})
graph = ObservableGraph[Node]()
a, b = Node("add"), Node("double")
graph.add(a, __operator__=add, a=2, b=3)
graph.add(b, __operator__=double)
graph.add_link(a, b, "source")
engine = EagerEngine(graph, provider)
engine.listen(lambda e: print("event", e.kind, e.node.label,
                              e.job_event.kind if e.job_event else ""))
print("Eager:", engine.evaluate(b))  # 10
graph.set(a, a=10)
print("After editing:", engine.evaluate(b))  # 26
provider.register(double, lambda source: source * 3)
print("After reloading operator:", engine.evaluate(b))  # 39
engine.close()


# ------------------ hybrid graph -----------------
@dataclass(frozen=True)
class Frames:
    numbers: frozenset[int]

    def merge(self, other: "Frames") -> "Frames":
        return Frames(self.numbers | other.numbers)


@dataclass(frozen=True)
class FrameValues:
    values: dict[int, int]

    def select(self, context: Frames) -> "FrameValues":
        if not context.numbers <= self.values.keys():
            raise KeyError("Missing frames")
        return FrameValues({f: self.values[f] for f in context.numbers})

    def merge(self, other: "FrameValues") -> "FrameValues":
        return FrameValues({**self.values, **other.values})


class FrameSource:
    def request(self, context: Frames, /, **parameters):
        return {}

    def compute(self, context: Frames, get, /, *, bias: int):
        return FrameValues({f: f + bias for f in context.numbers})


class Shift:
    def request(self, context: Frames, /, *, offset: int):
        return {"source": Frames(frozenset(f - offset for f in context.numbers))}

    def compute(self, context: Frames, get, /, *, offset: int):
        upstream_ctx = Frames(frozenset(f - offset for f in context.numbers))
        upstream = get("source", upstream_ctx)
        return FrameValues({f: upstream.values[f - offset] for f in context.numbers})


source_handle = OperatorHandle("frames")
shift_handle = OperatorHandle("shift")
hybrid_provider = DictOperatorProvider({source_handle: FrameSource(),
                                        shift_handle: Shift()})
hybrid_graph = ObservableGraph[Node]()
src, shift = Node("source"), Node("shift")
hybrid_graph.add(src, __operator__=source_handle, bias=100)
hybrid_graph.add(shift, __operator__=shift_handle, offset=1)
hybrid_graph.add_link(src, shift, "source")
hybrid = HybridEngine(hybrid_graph, hybrid_provider)
print("Hybrid first:", hybrid.evaluate(shift, Frames(frozenset({2, 3}))).values)
print("Hybrid expanded:", hybrid.evaluate(shift, Frames(frozenset({3, 4}))).values)
hybrid.close()
