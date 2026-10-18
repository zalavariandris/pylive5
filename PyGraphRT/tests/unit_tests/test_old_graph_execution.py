
import pytest
from typing import TYPE_CHECKING


from pygraphrt.old_graph_executor import GraphExecutorRT
from pygraphrt.core import NodeExecution, ExecutionFailure, ExecutionSuccess


def test_executing_node_without_an_operator():
    import pygraphrt as rt

    G = rt.GraphDefinitionRT()
    E = GraphExecutorRT(G)
    node = G._create_node()


    execution:NodeExecution = E.request(node)
    assert isinstance(execution, ExecutionFailure), f"Expected ExecutionFailure, got {type(execution)}"

def test_executing_node_with_a_valid_operator():
    import pygraphrt as rt

    G = rt.GraphDefinitionRT()
    node = G._create_node()


class Test_Api_MisUse:
    def test_create_node_from_unsupported_object(self):
        import pygraphrt as rt

        G = rt.GraphDefinitionRT()

        with pytest.raises(AssertionError):
            G._create_node(object())

if __name__ == "__main__":
    pytest.main([__file__])