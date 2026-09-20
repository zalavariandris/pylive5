import pytest
import pygraphrt as rt
from textwrap import dedent

from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.script_module_rt import ScriptModuleRT


@pytest.mark.parametrize(
    "a_value, b_value, unused_value, expected_changes",
    [(10, 2, 0, 1), (10, 20, 0, 1), (1, 2, 10, 0)],
    ids=["one-function", "multiple-functions", "unrelated-function"],
)
def test_script_module_function_changed(a_value, b_value, unused_value, expected_changes):
    from pygraphrt.script_module_rt import ScriptModuleRT
    sm = ScriptModuleRT("mathy", dedent("""
    def A():
        return 1

    def B():
        return 2

    def add(a, b):
        return a + b

    def unused():
        return 0
    """))

    G = rt.GraphRT()
    operators = {operator.name: operator for operator in sm.operators()}

    A=G.node()(operators['A'])
    B=G.node()(operators['B'])
    out = G.node(A, B)(operators['add'])

    track_changes = []

    def callback():
        track_changes.append("changed")

    watcher = rt.watch(G, out, callback)

    try:
        assert G.execute(out) == 3

        sm.set_script(dedent(f"""
        def A():
            return {a_value}

        def B():
            return {b_value}

        def add(a, b):
            return a + b

        def unused():
            return {unused_value}
        """))

        assert len(track_changes) == expected_changes
        assert G.execute(out) == a_value + b_value

    finally:
        watcher.stop()


@pytest.fixture
def ancestor_graph():
    """The output is local; its ancestor comes from an independently edited script."""
    graph = rt.GraphRT()
    module = ScriptModuleRT("source", "def value(): return 1")
    ancestor = graph.node()(OperatorRef(module, "value"))

    @graph.node(value=ancestor)
    def output(value):
        return value * 10

    changes = []
    watcher = rt.watch(graph, output, lambda: changes.append(True))
    try:
        yield graph, module, ancestor, output, watcher, changes
    finally:
        watcher.stop()


@pytest.mark.parametrize("script", [
    "", "def other(): return 0", "def value(:", "raise RuntimeError('broken')",
], ids=["removed", "replaced", "syntax-error", "execution-error"])
def test_ancestor_operator_removed_and_restored(ancestor_graph, script):
    graph, module, ancestor, output, watcher, changes = ancestor_graph
    assert graph.execute(output) == 10
    for value in (2, 3):
        changes.clear()
        module.set_script(script)
        assert changes == [True]
        assert ancestor.get_operator().get_value() is None
        assert watcher._running
        changes.clear()
        module.set_script(f"def value(): return {value}")
        assert changes == [True]
        assert graph.execute(output) == value * 10
        assert watcher._running


def test_ancestor_operator_changed_and_unrelated_exports_ignored(ancestor_graph):
    graph, module, ancestor, output, watcher, changes = ancestor_graph
    module.set_script("def value(): return 2")
    assert changes == [True]
    assert graph.execute(output) == 20
    changes.clear()
    module.set_script("def value(): return 2\ndef unused(): return 0")
    module.set_script("def value(): return 2\ndef unused(): return 9")
    module.set_script("def value(): return 2")
    assert changes == []
    watcher.stop()
    module.set_script("def value(): return 3")
    assert changes == []


def test_setting_ancestor_inputs_rewires_watched_modules(ancestor_graph):
    graph, module, ancestor, output, watcher, changes = ancestor_graph
    # Both scripts export the same name: matching must include module identity.
    other_module = ScriptModuleRT("other", "def value(): return 4")
    other = graph.node()(OperatorRef(other_module, "value"))
    bridge_module = ScriptModuleRT("bridge", "def identity(value): return value")
    bridge = graph.node(value=ancestor)(OperatorRef(bridge_module, "identity"))
    output.set_inputs(value=bridge)
    assert changes == [True]
    assert graph.execute(output) == 10
    changes.clear()

    # Mutate an ancestor's inputs, not the selected output node.
    bridge.set_inputs(value=other)
    assert changes == [True]
    assert graph.execute(output) == 40
    changes.clear()
    module.set_script("def value(): return 7")
    module.set_script("")
    assert changes == []
    other_module.set_script("def value(): return 5")
    assert changes == [True]
    assert graph.execute(output) == 50
    changes.clear()
    other_module.set_script("")
    assert changes == [True]
    other_module.set_script("def value(): return 6")
    assert changes == [True, True]
    assert graph.execute(output) == 60
    changes.clear()

    bridge.set_inputs(value=8)
    assert changes == [True]
    assert graph.execute(output) == 80
    changes.clear()
    other_module.set_script("def value(): return 9")
    assert changes == []
