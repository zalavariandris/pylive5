"""Decorator contract: references follow names; redefinition replaces values.

These specifications intentionally require behavior beyond the current
implementation, which rejects duplicate operator names.
"""

import random
from textwrap import dedent

from pygraphrt import ScriptModuleRT
import pytest
import pygraphrt as rt

@pytest.fixture
def module() -> ScriptModuleRT:
    module = ScriptModuleRT()
    module.set_script("def hello(): return 'Hello'")
    return module


@pytest.fixture
def hello_operator(module: ScriptModuleRT) -> rt.Operator:
    
    return module.get_operator_by_name("hello")

@pytest.fixture
def graph() -> rt.GraphDefinitionRT:
    graph = rt.GraphDefinitionRT()
    return graph

@pytest.fixture
def hello_node(hello_operator, graph: rt.GraphDefinitionRT) -> rt.NodeRef:
    return graph._create_node(hello_operator)

def _execute_node(node: rt.NodeRef) -> None:
    """helper function to execute a node and return its result
    we keep this helper in case node execution api changes in the future."""
    return node()



class Test_CreateNode:
    def test_create_node_without_op(self, graph: rt.GraphDefinitionRT) -> None:
        node_ref = graph._create_node()
        assert node_ref in graph.nodes()

    def test_create_node_with_op(self, graph: rt.GraphDefinitionRT) -> None:
        im = ScriptModuleRT()
        im.set_script("def identity(x): return x")
        op = im.get_operator_by_name("identity")
        
        node_ref = graph._create_node(op)
        assert node_ref in graph.nodes()

    def test_create_node_without_op(self, graph: rt.GraphDefinitionRT) -> None:
        n1 = graph._create_node()
        assert n1 in graph.nodes()

    def test_create_node_from_bad_objects(self, graph: rt.GraphDefinitionRT) -> None:
        with pytest.raises(AssertionError):
            graph._create_node("not an operator")

        with pytest.raises(AssertionError):
            graph._create_node(123)

    def test_create_node_directly_with_a_function_is_not_allowed(self, graph: rt.GraphDefinitionRT) -> None:
        # todo: reconsider this behaviour
        def func():
            pass
        with pytest.raises(AssertionError):
            graph._create_node(func)

    @pytest.mark.skip(reason="not yet implemented")
    def test_clear_node(self, graph: rt.GraphDefinitionRT) -> None:
        ...


class Test_UpdateNode:
    def test_update_node_operator(self) -> None:
        graph = rt.GraphDefinitionRT()
        E = rt.GraphExecutorRT(graph)
        node = graph._create_node()

        im = ScriptModuleRT()
        im.set_script("def hello(): return 'Hello'")
        op = im.get_operator_by_name("hello")
        graph._update_node(node, op, [], {})

        assert E.execute(node).result == "Hello"

    def test_update_node_args(self) -> None:
        graph = rt.GraphDefinitionRT()
        E = rt.GraphExecutorRT(graph)
        node = graph._create_node()

        im = ScriptModuleRT()
        im.set_script("def func(x): return x")
        op = im.get_operator_by_name("func")
        graph._update_node(node, op, [42], {})

        E = rt.GraphExecutorRT(graph)
        assert E.execute(node).result == 42

    def test_update_node_kwargs(self) -> None:
        graph = rt.GraphDefinitionRT()
        E = rt.GraphExecutorRT(graph)
        node = graph._create_node()

        im = ScriptModuleRT()
        im.set_script("def func(x, y): return x + y")
        op = im.get_operator_by_name("func")
        graph._update_node(node, op, [1], {"y": 2})

        assert E.execute(node).result == 3


class Test_DeleteNode:
    def test_delete_node(self) -> None:
        graph = rt.GraphDefinitionRT()
        node = graph._create_node()
        assert node in graph.nodes()

        graph._delete_node(node)
        assert node not in graph.nodes()