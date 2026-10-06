from collections.abc import Callable

import pygraphrt as rt
import pytest

from pyflow5.properties_editor.pygraphrt_node_inlet_tree_model_adapter import (
    PyGraphRTNodeInletTreeModelAdapter,
)
from pyflow5.pygraphrt_graphmodel import PyGraphRTGraphModel


@pytest.fixture
def make_input_model() -> Callable[..., PyGraphRTNodeInletTreeModelAdapter]:
    def make(
        graph: rt.GraphDefinitionRT,
        registry: rt.ModuleRegistry | None = None,
    ) -> PyGraphRTNodeInletTreeModelAdapter:
        registry = registry if registry is not None else rt.ModuleRegistry()
        source = PyGraphRTGraphModel(
            graph, registry, rt.GraphInvalidator(graph, registry), rt.GraphExecutorRT(graph)
        )
        return PyGraphRTNodeInletTreeModelAdapter(source)

    return make
