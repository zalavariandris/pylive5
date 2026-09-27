import pytest

def test_executing_node_without_an_operator():
    import pygraphrt as rt

    G = rt.GraphStateRT()
    E = rt.GraphExecutorRT(G)
    node = G._create_node()

    with pytest.raises(rt.GraphExecutionError):
        # "Expected GraphExecutionError when executing a node without an operator.":
        E.execute(node)

def test_executing_node_with_a_valid_operator():
    import pygraphrt as rt

    G = rt.GraphStateRT()
    node = G._create_node()


class Test_Api_MisUse:
    def test_create_node_from_unsupported_object(self):
        import pygraphrt as rt

        G = rt.GraphStateRT()

        with pytest.raises(AssertionError):
            G._create_node(object())

if __name__ == "__main__":
    pytest.main([__file__])