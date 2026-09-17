import pytest
import pygraphrt as rt
from textwrap import dedent

def test_watch_node_changes():
    # setup
    G = rt.GraphRT()
    @G.node()
    def output(value):
        return value
    
    track_changes = []

    def callback():
        track_changes.append("changed")

    watcher = rt.watch(G, output, callback)

    # add node
    @G.node(5)
    def identity(val):
        return val

    assert len(track_changes) == 0, "Watcher callback should not be triggered when no changes have occurred"

    output.set_inputs(1)  # This should trigger the watcher callback

    assert len(track_changes) == 1, "Watcher callback should be triggered when output node input changes"

    output.set_inputs(identity)

    assert len(track_changes) == 2, "Watcher callback should be triggered when output node input changes to identity node"

    identity.set_inputs(10)

    assert len(track_changes) == 3, "Watcher callback should be triggered when identity node input changes"

    output.set_inputs(value=20) 
    assert len(track_changes) == 4, "Watcher callback should be triggered when output node input changes to a new value"

    identity.set_inputs(val=30)
    assert len(track_changes) == 4, "Watcher callback should not be triggered when identity node input changes with the same value"

    watcher.stop()

    output.set_inputs(50)
    assert len(track_changes) == 4, "Watcher callback should not be triggered after watcher is stopped"

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
    G.add_modules([sm])

    A=G.node()(sm.operators()['A'])
    B=G.node()(sm.operators()['B'])
    out = G.node(A, B)(sm.operators()['add'])

    track_changes = []

    def callback():
        track_changes.append("changed")

    watcher = rt.watch(G, out, callback)

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

    watcher.stop()


def test_watch_local_operator_changes_after_stop_and_restart():
    G = rt.GraphRT()

    @G.node()
    def output():
        return 1

    results = []
    watcher = rt.watch(G, output, lambda: results.append(G.execute(output)))

    G.module().update_operator(output.get_operator(), lambda: 2)
    assert results == [2]

    watcher.stop()
    G.module().update_operator(output.get_operator(), lambda: 3)
    assert results == [2]

    watcher.start()
    watcher.start()
    G.module().update_operator(output.get_operator(), lambda: 4)
    assert results == [2, 4]

    watcher.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
