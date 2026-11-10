import pytest
from graphcook.observable_graph import (
    ObservableGraph, 
    GraphChange, 
    SetChanges
)


@pytest.fixture
def hello_world(): 
    G = ObservableGraph()
    G.add_node("the_name")
    G.add_node("the_greeting")
    G.add_node("hello_world")
    G.add_node("preview")
    G.add_link("the_name", "hello_world", "name")
    G.add_link("the_greeting", "hello_world", "greeting")
    G.add_link("hello_world", "preview", "input")
    return G


def test_remove_node_with_links(hello_world):
    events = []
    def on_graph_change(event: GraphChange):
        nonlocal events
        events.append(event)

    G = hello_world
    G.listen(on_graph_change)
    assert events == []
    G.remove_node("hello_world")

    # remove node emit a single node removal event, and does not emit connected link removals
    assert len(events) == 1
    assert events[-1].nodes == SetChanges(removed={"hello_world"})

if __name__ == "__main__":
    pytest.main([__file__, '-vv'])
