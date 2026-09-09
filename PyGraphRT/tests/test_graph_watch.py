import pytest
import pygraphrt as rt

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

if __name__ == "__main__":
    pytest.main([__file__, "-v"])