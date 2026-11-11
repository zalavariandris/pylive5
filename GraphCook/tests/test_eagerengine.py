from graphcook.provider import OperatorHandle, OperatorProvider
import pytest
from graphcook.eager_engine import EagerEngine
from typing import Any, Callable
from textwrap import dedent



def test_eager_engine():
    from graphcook.observable_graph import ObservableGraph


    engine = EagerEngine("""
    def the_name():
        return "Mása"

    def the_greeting():
        return "Hey"

    def hello_world(name:str, greeting:str='Hello'):
            return f"{greeting}, {name}!"
    """)
    the_name = engine.node("the_name")
    the_greeting = engine.node("the_greeting")
    hello_world = engine.node("hello_world", name=the_name, greeting=the_greeting)

    engine.evaluate(hello_world)

if __name__ == "__main__":
    pytest.main([__file__])
