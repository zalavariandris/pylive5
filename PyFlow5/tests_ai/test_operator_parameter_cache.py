"""Parameter metadata stays reusable during edits and fresh after script changes."""

from collections.abc import Iterator
from unittest.mock import patch

import pygraphrt2 as rt
import pytest
from qtpy.QtCore import Qt

from pyflow5.core.input_roles import InputDataRole
from pyflow5.models.pygraphrt_graphmodel import PyGraphRTGraphModel


@pytest.fixture
def model_and_module(qapp: object) -> Iterator[tuple[PyGraphRTGraphModel, rt.InlineScriptModule]]:
    graph = rt.Graph()
    module = rt.InlineScriptModule("example")
    module.set_script("def operation(value: int = 1):\n    return value\n")
    module.evaluate()
    operator = module.get_operator_by_name("operation")
    graph._create_node(operator, name="first")
    graph._create_node(module.get_operator_by_name("operation"), name="second")
    engine = rt.Engine(graph=graph, registry=module)
    model = PyGraphRTGraphModel(engine)
    yield model, module
    model.close()
    engine.close()


def test_repeated_queries_and_value_edits_share_parameters(
    model_and_module: tuple[PyGraphRTGraphModel, rt.InlineScriptModule],
) -> None:
    model, _ = model_and_module
    node = model.mapToSource("first")
    assert node is not None
    operator = node.resolve().operator
    assert operator is not None

    with patch.object(rt.ScriptOperatorRef, "get_parameters", autospec=True) as get_parameters:
        for name in ("first", "second"):
            assert list(model.inlets(name)) == ["value"]
            assert model.inletData(name, "value") == "value: int"
            assert model.inletData(name, "value", InputDataRole.AnnotationRole) is int
            assert model.inletData(name, "value", InputDataRole.DefaultValueRole) == 1
            assert "value" in model.inletData(name, "value", Qt.ItemDataRole.ToolTipRole)

        assert model.setInletData("first", "value", 7, InputDataRole.InputValueRole)
        assert model.inletData("first", "value", InputDataRole.InputValueRole) == 7
        assert list(model.inlets("first")) == ["value"]
        # Initial graph snapshots already populated the shared parameter cache.
        get_parameters.assert_not_called()


def test_script_changes_refresh_parameters_before_notifying_observers(
    model_and_module: tuple[PyGraphRTGraphModel, rt.InlineScriptModule],
) -> None:
    model, module = model_and_module
    assert list(model.inlets("first")) == ["value"]
    observed_defaults: list[object] = []

    def read_parameters(node_name: str) -> None:
        assert list(model.inlets(node_name)) == ["amount"]
        assert model.inletData(node_name, "amount", InputDataRole.AnnotationRole) is float
        observed_defaults.append(
            model.inletData(node_name, "amount", InputDataRole.DefaultValueRole)
        )

    model.inletsReset.connect(read_parameters)
    module.set_script("def operation(amount: float = 2.5):\n    return amount\n")
    module.evaluate()
    assert observed_defaults == [2.5, 2.5]


def test_removed_operator_and_empty_parameters_refresh_when_restored(
    model_and_module: tuple[PyGraphRTGraphModel, rt.InlineScriptModule],
) -> None:
    model, module = model_and_module
    assert list(model.inlets("first")) == ["value"]

    module.set_script("")
    module.evaluate()
    assert list(model.inlets("first")) == []
    module.set_script("def operation():\n    return 1\n")
    module.evaluate()
    assert list(model.inlets("first")) == []
    module.set_script("def operation(label: str = 'ready'):\n    return label\n")
    module.evaluate()
    assert list(model.inlets("first")) == ["label"]
    assert model.inletData("first", "label", InputDataRole.DefaultValueRole) == "ready"


def test_recovery_reset_refreshes_metadata(
    model_and_module: tuple[PyGraphRTGraphModel, rt.InlineScriptModule],
) -> None:
    model, module = model_and_module
    assert model.inletData("first", "value", InputDataRole.DefaultValueRole) == 1
    operator = module.get_operator_by_name("operation")
    assert operator is not None
    # Simulate a change that did not deliver its normal registry notification.
    operator.resolve().__defaults__ = (9,)

    model.reset_graph_from_scratch()

    assert model.inletData("first", "value", InputDataRole.DefaultValueRole) == 9
