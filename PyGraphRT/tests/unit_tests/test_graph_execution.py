
import pytest
from typing import TYPE_CHECKING


from pygraphrt.graph_executor import NodeExecution, ExecutionFailure, ExecutionSuccess


def test_executing_node_without_an_operator():
    import pygraphrt as rt

    G = rt.GraphDefinitionRT()
    E = rt.GraphExecutorRT(G)
    node = G._create_node()


    execution:NodeExecution = E.execute(node)
    assert isinstance(execution, ExecutionFailure)

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