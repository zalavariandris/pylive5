"""Cached request functions still expose active upstream work to the UI."""

from collections.abc import Callable
from threading import Event, get_ident

from pytestqt.qtbot import QtBot
from qtpy.QtCore import Qt
from qtpy.QtGui import QColor

from pygraphrt2 import Engine
from pyflow5.core.node_execution_state import NodeExecutionState
from pyflow5.models.pygraphrt_graphmodel import PyGraphRTGraphModel


def test_frame_changes_highlight_request_ancestors_and_cache_hits_stay_idle(
    qtbot: QtBot,
) -> None:
    engine = Engine()
    engine.set_auto_execute(False)
    source_entered, source_release = Event(), Event()
    blur_entered, blur_release = Event(), Event()
    calls: list[int] = []

    def source() -> Callable[[int], int]:
        def compute(frame: int) -> int:
            calls.append(frame)
            if frame == 2:
                source_entered.set()
                if not source_release.wait(5):
                    raise TimeoutError("test did not release source")
            if frame == 3:
                raise ValueError("bad frame")
            return frame * 10
        return compute

    def blur(video: Callable[[int], int]) -> Callable[[int], int]:
        def compute(frame: int) -> int:
            value = video(frame)
            if frame == 2:
                blur_entered.set()
                if not blur_release.wait(5):
                    raise TimeoutError("test did not release blur")
            return value + 1
        return compute

    def render(video: Callable[[int], int], frame: int) -> int:
        return video(frame)

    source_node = engine.add_node(source, name="source")
    blur_node = engine.add_node(blur, args=(source_node,), name="blur")
    target = engine.add_node(render, args=(blur_node, 1), name="get_image_frame")
    model = PyGraphRTGraphModel(engine)
    threads: list[int] = []
    states: list[tuple[NodeExecutionState, NodeExecutionState]] = []

    def record(*_: object) -> None:
        threads.append(get_ident())
        states.append((
            model.nodeData("source", model.StateRole),
            model.nodeData("blur", model.StateRole),
        ))

    model.nodesDataChanged.connect(record)
    idle = NodeExecutionState.IDLE
    executing = NodeExecutionState.EXECUTING
    try:
        with qtbot.waitSignal(engine.nodes_executed):
            engine.execute_nodes(target)
        source_output = model.nodeData("source", model.OutputRole)
        assert callable(source_output)

        engine._graph._update_node(target, render, args=(blur_node, 2))
        engine.execute_nodes(target)
        qtbot.waitUntil(lambda: source_entered.is_set() and states[-1] == (executing, executing))
        assert model.nodeData("source", Qt.ItemDataRole.BackgroundRole) == QColor("yellow")
        assert model.nodeData("blur", Qt.ItemDataRole.BackgroundRole) == QColor("yellow")

        source_release.set()
        qtbot.waitUntil(lambda: blur_entered.is_set() and states[-1] == (idle, executing))
        with qtbot.waitSignal(engine.nodes_executed) as completed:
            blur_release.set()
        assert completed.args[0][target] == 21
        assert states[-1] == (idle, idle)
        assert all(thread == get_ident() for thread in threads)
        assert model.nodeData("source", model.OutputRole) is source_output

        states.clear()
        engine._graph._update_node(target, render, args=(blur_node, 1))
        with qtbot.waitSignal(engine.nodes_executed):
            engine.execute_nodes(target)
        assert calls == [1, 2]
        assert all(state == (idle, idle) for state in states)

        engine._graph._update_node(target, render, args=(blur_node, 3))
        with qtbot.waitSignal(engine.execution_failed):
            engine.execute_nodes(target)
        assert model.nodeData("source", model.StateRole) is NodeExecutionState.ERROR
        assert model.nodeData("blur", model.StateRole) is idle
        assert not engine.pending_nodes()
    finally:
        source_release.set()
        blur_release.set()
        model.close()
        engine.close()
