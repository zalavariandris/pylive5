import pytest

from pygraphrt import (
    GraphDefinitionRT,
    GraphExecutorRT,
    ExecutionSuccess,
    MemoryCache,
)

def test_smoke_memorycache():
    graph = GraphDefinitionRT()

    counter = 0

    @graph.node()
    def the_name():
        nonlocal counter
        counter += 1
        return 'Mása'

    @graph.node()
    def the_greeting():
        return 'Hey'

    @graph.node(the_name, the_greeting)
    def hello_world(name:str, greeting:str='Hello'):
        return f"{greeting}, {name}!"

    
    cache = MemoryCache()
    executor = GraphExecutorRT(graph, cache)

    # Sanity check: Execute the graph to test the memory cache
    execution = executor.execute(hello_world)
    assert isinstance(execution, ExecutionSuccess)
    assert execution.result == "Hey, Mása!"
    assert counter == 1  # Ensure the_name was called only once due to caching

    # Execute the graph again to ensure the result is retrieved from the cache
    execution = executor.execute(hello_world)
    assert isinstance(execution, ExecutionSuccess)
    assert execution.result == "Hey, Mása!"
    assert counter == 1  # Ensure the_name was not called again due to caching

if __name__ == "__main__":
    pytest.main([__file__, '--v'])