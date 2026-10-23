import pytest

from textwrap import dedent
from typing import Iterable, Tuple, Any

from pygraphrt2.graph import Graph
from pygraphrt2.engine import Engine


from pygraphrt2.inline_scriptmodule import InlineScriptModule
from pygraphrt2.async_scriptmodule import AsyncScriptModule


# ==========
# UNIT TESTS
# ==========

@pytest.fixture
def hello_world():
    graph:Graph = Graph()
    
    @graph.node()
    def the_name():
        return "Mása"

    @graph.node()
    def the_greeting():
        return "Hey"

    @graph.node(the_name)
    def hello(name:str, greeting:str="Hello"):
        return f"{greeting} {name}!"
    
    return graph, (the_name, the_greeting, hello)

def test_graph_structure(hello_world):
    graph, (the_name, the_greeting, hello) = hello_world
    # test graph structure
    assert set(list(graph.nodes())) == {the_name, the_greeting, hello}
    assert graph.in_links(hello) == {the_name: {0}}
    assert graph.out_links(the_name) == {hello: {0}}

def test_inline_executor(hello_world):
    graph, (the_name, the_greeting, hello) = hello_world
    from pygraphrt2.inline_executor import InlineExecutor
    executor = InlineExecutor(graph)

    outputs = executor.execute(hello)

    assert outputs[hello] == "Hello Mása!"

def test_inline_scriptmodule():
    sm = InlineScriptModule()
    sm.evaluate()
    assert list(sm.operators()) == []

    sm.set_script(dedent("""\
    def the_name():
        return "Mása"

    def the_greeting():
        return "Hey"

    def hello(name:str, greeting:str="Hello"):
        return f"{greeting} {name}!"
    """))
    track_changes = dict(added=[], removed=[], updated=[])
    sm.operators_added.connect(lambda ops: track_changes['added'].extend(ops))
    sm.operators_removed.connect(lambda ops: track_changes['removed'].extend(ops))
    sm.operators_changed.connect(lambda ops: track_changes['updated'].extend(ops))

    sm.evaluate()
    expected_operators = set([
        sm.get_operator_by_name("the_name"), 
        sm.get_operator_by_name("the_greeting"), 
        sm.get_operator_by_name("hello")
    ])
    assert set(list(sm.operators())) == set(expected_operators)

    assert set(track_changes['added']) == expected_operators
    assert track_changes['removed'] == []
    assert track_changes['updated'] == []

    # breake the script
    sm.set_script(dedent("""\
        ...SYNTAX ERROR...
        def the_name():
            return "Mása"
    
        def the_greeting():
            return "Hey"
    
        def hello(name:str, greeting:str="Hello"):
            return f"{greeting} {name}!"
        """))

    track_changes = dict(added=[], removed=[], updated=[])
    sm.evaluate()

    assert track_changes['added'] == []
    assert set(track_changes['removed']) == expected_operators
    assert track_changes['updated'] == []
    
@pytest.mark.asyncio
async def test_async_executor(hello_world):
    from pygraphrt2.async_executor import AsyncExecutor
    graph, (the_name, the_greeting, hello) = hello_world
    executor = AsyncExecutor(graph)

    future = executor.execute(hello)
    print(future)
    outputs = await future
    assert outputs[hello] == "Hello Mása!"


## SCRIPT MODULES

@pytest.mark.asyncio
async def test_async_scriptmodule():
    sm = AsyncScriptModule()
    await sm.evaluate()
    sm.operators_added(...)
    sm.operators_removed(...)
    sm.operators_updated(...)


# =================
# INTEGRATION TESTS
# =================

@pytest.mark.asyncio
async def test_engine_with_async_executor_and_scriptmodule():
    sm = AsyncScriptModule()
    script = dedent("""
    def the_name():
        return "Mása"

    def the_greeting():
        return "Hey"

    def hello_world():
        return f":{greeting} {name}"
    """)
    await sm.evaluate_in_background()

    engine = Engine(registry=sm)

    graph = engine.graph
    the_name_op  =script.get_operator_by_name("the_name")
    the_greeting_op = script.get_operator_by_name("the_greeting")
    hello_world_op = script.get_operator_by_name("hello_world")
    the_name_node = graph._create_node(the_name_op)
    the_greeting_node = graph._create_node(the_greeting_op)
    hello_world_node = graph._create_node(hello_world_op, {'name': the_name_node})

    # test graph structure
    ...

    # updating the script module, should replace the existing operators in the graph
    sm = AsyncScriptModule()
    updated_script = dedent("""
    def the_name():
        return "Mása"

    def the_greeting():
        return "Hello"

    def hello_world(name:str, greeting:str="Hello"):
        return f":{greeting} {name}"
    """)
    await sm.evaluate_in_background()

    executor = InlineExecutor(graph)
    await executor.execute(hello_world_node)


if __name__ == "__main__":
    pytest.main([__file__])