from pygraphrt.inline_module import FunctionOperator
import pytest
import pygraphrt as rt
from qtpy.QtCore import (
    QObject, 
    Signal
)
from qtpy.QtTest import QSignalSpy

def test_operator_changed_signal():
    G = rt.GraphRT()
    spy = QSignalSpy(G._inline_module.operators_changed)

    @G.node()
    def my_node(x):
        return x * 2

    def new_function(x):
        return x + 1
    
    G._inline_module._update_operator(my_node.get_operator(), new_function)

    assert len(spy) == 1, "operators_changed signal should have been emitted once"
    assert my_node.get_operator() in spy[0][0], "operators_changed signal should contain the name of the changed operator"

if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 