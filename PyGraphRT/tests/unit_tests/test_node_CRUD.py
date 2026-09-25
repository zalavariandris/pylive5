"""Decorator contract: references follow names; redefinition replaces values.

These specifications intentionally require behavior beyond the current
implementation, which rejects duplicate operator names.
"""

import random

from pygraphrt.inline_module import InlineModuleRT
import pytest
import pygraphrt as rt
from pygraphrt.graph_rt import NodeData



@pytest.fixture
def hello_operator(module: InlineModuleRT) -> rt.Operator:
    def hello():
        return "Hello"
    return module._create_operator(hello)

@pytest.fixture
def module() -> InlineModuleRT:
    module = InlineModuleRT()
    return module

@pytest.fixture(
    params=[rt.DummyCache, rt.MemoryCache, rt.HistoryMemoryCache],
    ids=["uncached", "memory", "history"],
)
def graph(request: pytest.FixtureRequest) -> rt.GraphRT:
    graph = rt.GraphRT()
    graph.cache = request.param()
    return graph

@pytest.fixture
def hello_node(hello_operator, graph: rt.GraphRT) -> rt.NodeRef:
    return graph._create_node(hello_operator)


def _execute_node(node: rt.NodeRef) -> None:
    """helper function to execute a node and return its result
    we keep this helper in case node execution api changes in the future."""
    return node()



class Test_CreateNode:
    def test_create_node_without_op(self, graph: rt.GraphRT) -> None:
        node_ref = graph._create_node()
        assert node_ref in graph.nodes()

    def test_create_node_with_op(self, graph: rt.GraphRT) -> None:
        im = InlineModuleRT()
        op = im._create_operator(lambda x: x)
        
        node_ref = graph._create_node(op)
        assert node_ref in graph.nodes()

    def test_create_node_without_op(self, graph: rt.GraphRT) -> None:
        n1 = graph._create_node()
        assert n1 in graph.nodes()

    def test_create_node_from_bad_objects(self, graph: rt.GraphRT) -> None:
        with pytest.raises(AssertionError):
            graph._create_node("not an operator")

        with pytest.raises(AssertionError):
            graph._create_node(123)

    def test_create_node_directly_with_a_function_is_not_allowed(self, graph: rt.GraphRT) -> None:
        # todo: reconsider this behaviour
        def func():
            pass
        with pytest.raises(AssertionError):
            graph._create_node(func)

    @pytest.mark.skip(reason="not yet implemented")
    def test_clear_node(self, graph: rt.GraphRT) -> None:
        ...

class Test_UpdateNode:
    def test_update_node_operator(self) -> None:
        graph = rt.GraphRT()
        node = graph._create_node()

        im = InlineModuleRT()
        op = im._create_operator(lambda: "Hello")
        graph._update_node(node, op, [], {})

        assert _execute_node(node) == "Hello"

    def test_update_node_args(self) -> None:
        graph = rt.GraphRT()
        node = graph._create_node()

        im = InlineModuleRT()
        def func(x):
            return x
        op = im._create_operator(func)
        graph._update_node(node, op, [42], {})

        assert _execute_node(node) == 42

    def test_update_node_kwargs(self) -> None:
        graph = rt.GraphRT()
        node = graph._create_node()

        im = InlineModuleRT()
        def func(x, y):
            return x + y
        op = im._create_operator(func)
        graph._update_node(node, op, [1], {"y": 2})

        assert _execute_node(node) == 3


class Test_DeleteNode:
    def test_delete_node(self) -> None:
        graph = rt.GraphRT()
        node = graph._create_node()
        assert node in graph.nodes()

        graph._delete_node(node)
        assert node not in graph.nodes()