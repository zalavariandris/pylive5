from pygraphrt2.graph_rt2 import FunctionOperator
import pytest
import pygraphrt2 as rt
from qtpy.QtCore import (
    QObject, 
    Signal
)
from qtpy.QtTest import QSignalSpy

class TestNodeCollectionSignals():
    def test_node_added_signal(self):
        G = rt.GraphRT()
        spy = QSignalSpy(G.nodes_added)

        @G.node()
        def my_node(x):
            return x * 2

        assert len(spy) == 1, "nodes_added signal should have been emitted once"
        assert my_node in spy[0][0], "nodes_added signal should contain the name of the added node"

    def test_node_removed_signal(self):
        G = rt.GraphRT()
        spy = QSignalSpy(G.nodes_removed)

        @G.node()
        def my_node(x):
            return x * 2

        G.remove_node(my_node)
        assert len(spy) == 1, "nodes_removed signal should have been emitted once"
        assert my_node in spy[0][0], "nodes_removed signal should contain the name of the removed node"

    def test_node_inputs_changed_signal(self):
        G = rt.GraphRT()
        spy = QSignalSpy(G.nodes_changed)

        @G.node()
        def my_node(x):
            return x * 2

        my_node.set_inputs(5)
        assert len(spy) == 1, "node_inputs_changed signal should have been emitted once"
        assert my_node in spy[0][0], "node_inputs_changed signal should contain the name of the changed node"


class TestOperatorCollectionSignals():
    def test_operator_added_signal(self):
        G = rt.GraphRT()
        spy = QSignalSpy(G.operators_added)

        @G.op()
        def my_operator(x):
            return x * 2

        assert len(spy) == 1, "operators_added signal should have been emitted once"
        assert my_operator in spy[0][0], "operators_added signal should contain the name of the added operator"

    def test_operator_removed_signal(self):
        G = rt.GraphRT()
        spy = QSignalSpy(G.operators_removed)

        @G.op()
        def my_operator(x):
            return x * 2

        G.remove_operator(my_operator)
        assert len(spy) == 1, "operators_removed signal should have been emitted once"
        assert my_operator in spy[0][0], "operators_removed signal should contain the name of the removed operator"

    def test_operator_changed_signal(self):
        G = rt.GraphRT()
        spy = QSignalSpy(G.operators_changed)

        @G.node()
        def my_node(x):
            return x * 2

        def new_function(x):
            return x + 1
        
        G.update_operator(my_node.get_operator(), FunctionOperator(new_function))

        assert len(spy) == 1, "operators_changed signal should have been emitted once"
        assert my_node.get_operator() in spy[0][0], "operators_changed signal should contain the name of the changed operator"



def test_executed_signal():
    G = rt.GraphRT()
    spy = QSignalSpy(G.executed)

    @G.node()
    def two():
        return 2

    @G.node()
    def three():
        return 3

    @G.node(two, three)
    def mult(a, b):
        return a*b

    result = G.execute(mult, profile=True)
    assert result == 6, "The result of executing the node should be correct"

    assert len(spy) == 1, "executed signal should have been emitted once"
    assert all(name in spy[0][0] for name in ["two", "three", "mult"]), "executed signal should contain the names of the executed nodes"
    
if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 
