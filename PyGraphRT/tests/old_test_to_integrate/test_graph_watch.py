from typing import Literal

import pytest

from pygraphrt import GraphRT, OperatorRef, watch
from pygraphrt.script_module import ScriptModuleRT


@pytest.mark.parametrize("change", ["input", "operator"])
def test_restarted_watcher_tracks_rewired_dependencies(
    change: Literal["input", "operator"],
) -> None:
    graph = GraphRT()
    source = "def source(value: int) -> int: return value"
    old_module = ScriptModuleRT("old")
    old_module.set_script(source)
    new_module = ScriptModuleRT("new")
    new_module.set_script(source)
    old_node = graph.node(1)(OperatorRef(old_module, "source"), name="old_node")
    new_node = graph.node(2)(OperatorRef(new_module, "source"), name="new_node")

    @graph.node(old_node)
    def output(value: int) -> int:
        return value

    results: list[int] = []

    def on_change() -> None:
        results.append(graph.execute(output))

    watcher = watch(graph, output, on_change)
    try:
        watcher.stop()
        output.set_inputs(new_node)
        assert results == []

        watcher.start()
        watcher.start()  # Starting twice must not duplicate subscriptions.
        assert results == []

        old_node.set_inputs(10)
        old_module.set_script(source.replace("return value", "return value * 10"))
        assert results == []

        # Test these independently: an input notification rebuilds subscriptions
        # and could otherwise hide a missing module subscription on restart.
        if change == "input":
            new_node.set_inputs(20)
        else:
            new_module.set_script(source.replace("return value", "return value * 10"))
        assert results == [20]

        watcher.stop()
        new_node.set_inputs(30)
        new_module.set_script(source.replace("return value", "return value * 100"))
        assert results == [20]
    finally:
        watcher.stop()
