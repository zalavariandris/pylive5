from graphcook.provider import OperatorHandle, OperatorProvider
import pytest
from graphcook.eager_observable_engine import EagerEngine
from typing import Any, Callable
from textwrap import dedent



def test_eager_engine():
    from graphcook.observable_graph import ObservableGraph


    engine = EagerEngine(dedent("""
    def the_name():
        return "Mása"

    def the_greeting():
        return "Hey"

    def hello_world(name:str, greeting:str='Hello'):
            return f"{greeting}, {name}!"
    """))
    
    the_name = engine.create_node("the_name")
    the_greeting = engine.create_node("the_greeting")
    hello_world = engine.create_node("hello_world", name=the_name, greeting=the_greeting)
    result = next(engine.evaluate_node(hello_world))
    assert result == "Hey, Mása!"

    engine.evaluate_node(hello_world)

def test_eager_engine_smoketest():
    from graphcook.eager_observable_engine import EagerEngine, EagerEngineChange

    engine = EagerEngine(
        "def source(): return 1\n"
        "def target(value): return value\n"
    )
    source = engine.create_node("source")
    target = engine.create_node("target")

    events: list[EagerEngineChange] = []
    unsubscribe = engine.listen(events.append)

    engine.add_link(source, target, "value")
    assert len(events) == 1
    assert events[0].graph is not None
    assert len(events[0].graph.links.added) == 1

    events.clear()
    engine.remove_link(source, target, "value")
    assert len(events) == 1
    assert events[0].graph is not None
    assert len(events[0].graph.links.removed) == 1

    engine.add_link(source, target, "value")
    events.clear()

    engine.delete(source)
    assert len(events) == 1

    change = events[0].graph
    assert change is not None
    assert change.nodes.removed == {source}
    assert {
        (link.source, link.target, link.inlet)
        for link in change.links.removed
    } == {(source, target, "value")}
    assert list(engine.links()) == []

    unsubscribe()

if __name__ == "__main__":
    pytest.main([__file__])
