"""Requestable operators are managed by the engine; plain callables are left alone."""

from collections.abc import Callable

from pygraphrt2 import Requestable
from pygraphrt2.execution_plan import NodeOutput, NodeStateSnapshot, evaluate, execute


def test_closures_are_stored_without_wrapping() -> None:
    def source() -> Callable[[int], int]:
        def compute(frame: int) -> int:
            return frame
        return compute

    outputs = execute({"source": NodeStateSnapshot(source)}).outputs
    assert outputs["source"].__name__ == "compute"
    assert outputs["source"](3) == 3


def test_requestable_results_are_cached_per_node_and_arguments() -> None:
    calls: list[int] = []
    events: list[tuple[object, bool]] = []

    class Source(Requestable):
        def __init__(self, base: int) -> None:
            self.base = base

        def __call__(self, frame: int) -> int:
            calls.append(frame)
            return self.base + frame

    def render(video: Source) -> tuple[int, int, int]:
        return video(1), video(1), video(2)

    result = execute(
        {
            "source": NodeStateSnapshot(Source, [10]),
            "render": NodeStateSnapshot(render, [NodeOutput("source")]),
        },
        on_request_state_changed=lambda key, running: events.append((key, running)),
    )
    assert result.outputs["render"] == (11, 11, 12)
    assert calls == [1, 2]
    assert isinstance(result.outputs["source"], Source)
    assert list(result.request_outputs) == [
        ("source", ((1,), ())), ("source", ((2,), ())),
    ]
    assert len(events) == 4


def test_returning_an_upstream_requestable_keeps_its_owner() -> None:
    class Source(Requestable):
        def __call__(self, frame: int) -> int:
            return frame

    def passthrough(video: Source) -> Source:
        return video

    result = execute({
        "source": NodeStateSnapshot(Source),
        "same": NodeStateSnapshot(passthrough, [NodeOutput("source")]),
        "use": NodeStateSnapshot(lambda video: video(5), [NodeOutput("same")]),
    })
    assert list(result.request_outputs) == [("source", ((5,), ()))]


def test_script_defined_requestable_is_an_operator_without_the_base_class() -> None:
    operators = evaluate(
        "from pygraphrt2 import Requestable\n"
        "class Blur(Requestable):\n"
        "    def __init__(self, video, size: float = 0.0):\n"
        "        self.video = video\n"
        "        self.size = size\n"
        "    def __call__(self, frame: int):\n"
        "        return (self.video(frame), self.size)\n"
    )
    assert set(operators) == {"Blur"}
    blur = operators["Blur"]((lambda frame: frame), size=2.0)
    assert blur(4) == (4, 2.0)
