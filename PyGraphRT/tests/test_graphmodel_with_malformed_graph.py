
from types import MappingProxyType
from typing import Callable, Mapping, Any
import inspect

import pytest
from qtpy.QtCore import QObject

from pygraphrt.graph_rt import GraphRT
from pygraphrt.graph_rt import NodeRef

def test_links_with_nonexistent_noderefs_in_inputs():
    G = GraphRT()

    invalid_node_ref = NodeRef(G, 'hello')

    @G.node(invalid_node_ref)
    def my_node(value):
        return value

    raise NotImplementedError()

def test_setting_inputs_from_other_graphs_raise_value_error():
    G1 = GraphRT()
    G2 = GraphRT()

    @G1.node()
    def node_in_G1():
        return 42

    with pytest.raises(ValueError):
        @G2.node(node_in_G1)
        def my_node(value):
            return value

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
