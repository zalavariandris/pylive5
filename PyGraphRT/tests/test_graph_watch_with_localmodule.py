import pytest
import pygraphrt as rt
from textwrap import dedent

def test_setinput_triggers_watcher():
    G = rt.GraphRT()

    @G.node()
    def mult(x, y):
        return x * y

    track_changes = []
    def callback():
        track_changes.append("changed")

    watcher = rt.watch(G, mult, callback)

    mult.set_inputs(2, 3)
    assert len(track_changes) == 1, "Watcher callback should be triggered when mult node input changes"

    mult.set_inputs(4, 4)
    assert len(track_changes) == 2, "Watcher callback should be triggered when mult node input changes" 

    mult.set_inputs(4)
    assert len(track_changes) == 3, "Watcher callback should be triggered when mult node input changes" 

    mult.set_inputs(x=5, y=5)
    assert len(track_changes) == 4, "Watcher callback should be triggered when mult node input changes" 

def test_update_operator_triggers_watcher():
    G = rt.GraphRT()

    @G.node()
    def output():
        return 1

    tracker = []
    def callback():
        tracker.append("change")
    watcher = rt.watch(G, output, callback)

    G.local().update_operator(output.get_operator(), lambda: 2)
    assert len(tracker) == 1, "Watcher callback should be triggered when output operator is updated"

    G.local().update_operator(output.get_operator(), lambda: 3)
    assert len(tracker) == 2, "Watcher callback should be triggered when output operator is updated"

    watcher.stop()
    G.local().update_operator(output.get_operator(), lambda: 4)
    assert len(tracker) == 2, "Watcher callback should not be triggered after watcher is stopped"

# def test_watch_node_changes():
#     # setup
#     G = rt.GraphRT()
#     @G.node()
#     def output(value):
#         return value
    
#     track_changes = []

#     def callback():
#         track_changes.append("changed")

#     watcher = rt.watch(G, output, callback)

#     # add node
#     @G.node(5)
#     def identity(val):
#         return val

    

#     assert len(track_changes) == 0, "Watcher callback should not be triggered when no changes have occurred"

#     output.set_inputs(1)  # This should trigger the watcher callback

#     assert len(track_changes) == 1, "Watcher callback should be triggered when output node input changes"

#     output.set_inputs(identity)

#     assert len(track_changes) == 2, "Watcher callback should be triggered when output node input changes to identity node"

#     identity.set_inputs(10)

#     assert len(track_changes) == 3, "Watcher callback should be triggered when identity node input changes"

#     output.set_inputs(value=20) 
#     assert len(track_changes) == 4, "Watcher callback should be triggered when output node input changes to a new value"

#     identity.set_inputs(val=30)
#     assert len(track_changes) == 4, "Watcher callback should not be triggered when identity node input changes with the same value"

#     watcher.stop()

#     output.set_inputs(50)
#     assert len(track_changes) == 4, "Watcher callback should not be triggered after watcher is stopped"



# def test_watch_local_operator_changes_after_stop_and_restart():
#     G = rt.GraphRT()

#     @G.node()
#     def output():
#         return 1

#     results = []
#     watcher = rt.watch(G, output, lambda: results.append(G.execute(output)))

#     G.module().update_operator(output.get_operator(), lambda: 2)
#     assert results == [2]

#     watcher.stop()
#     G.module().update_operator(output.get_operator(), lambda: 3)
#     assert results == [2]

#     watcher.start()
#     watcher.start()
#     G.module().update_operator(output.get_operator(), lambda: 4)
#     assert results == [2, 4]

#     watcher.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_operator_removal_keeps_watcher_for_restoration():
    graph = rt.GraphRT()
    node = graph.node()(lambda: 1)
    changes = []
    watcher = rt.watch(graph, node, lambda: changes.append(True))
    graph.local().remove_operator(node.get_operator())
    assert watcher._running
    assert changes == [True]
    watcher.stop()


def test_unrelated_operator_update_and_watcher_restart():
    graph = rt.GraphRT()
    def output():
        return 1
    def unrelated():
        return 0
    node = graph.node()(output)
    other = graph.node()(unrelated)
    changes = []
    watcher = rt.watch(graph, node, lambda: changes.append(True))
    try:
        graph.local().update_operator(other.get_operator(), lambda: 2)
        assert changes == []
        watcher.stop()
        watcher.start()
        watcher.start()
        graph.local().update_operator(node.get_operator(), lambda: 3)
        assert changes == [True]
    finally:
        watcher.stop()


def test_script_operator_notifications():
    from pygraphrt.abstract_module_rt import OperatorRef
    from pygraphrt.script_module import ScriptModuleRT

    module = ScriptModuleRT("example", "def output(): return 1")
    graph = rt.GraphRT()
    node = graph.node()(OperatorRef(module, "output"))
    changes = []
    watcher = rt.watch(graph, node, lambda: changes.append(True))
    try:
        module.set_script("def output(): return 2")
        assert changes == [True]
        module.set_script("")
        assert watcher._running
        assert changes == [True, True]
    finally:
        watcher.stop()
