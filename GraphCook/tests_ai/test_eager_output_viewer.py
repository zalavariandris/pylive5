"""Check actual Qt output widgets against the engine's event payloads."""

from collections.abc import Callable, Iterator

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtWidgets import QLabel
from myqtx.widgets.responsive_label import ResponsiveLabel

from graphcook.eager_engine import EagerEngine
from GraphCook.examples.eager_qdageditor import OutputViewer, ProviderView


@pytest.fixture
def make_engine() -> Iterator[Callable[[str], EagerEngine]]:
    engines: list[EagerEngine] = []

    def make(script: str) -> EagerEngine:
        engine = EagerEngine(script)
        engines.append(engine)
        return engine

    yield make
    for engine in engines:
        engine.close()


def displayed_text(viewer: OutputViewer) -> str:
    widget = viewer._display._stack.currentWidget()
    if isinstance(widget, ResponsiveLabel):
        return widget.getText()
    assert isinstance(widget, QLabel)
    return widget.text()


def test_viewer_displays_events_and_cached_selection_without_reading_attributes(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine], monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = make_engine("def source(): return 7\ndef other(): return 20")
    source = engine.node("source")
    other = engine.node("other")
    engine.evaluate(source)

    def reject_metadata_read(*args: object) -> None:
        raise AssertionError("Output viewer must consume events directly")

    monkeypatch.setattr(engine, "attributes", reject_metadata_read)
    viewer = OutputViewer(engine)
    qtbot.addWidget(viewer)
    viewer.setCurrentNode(source)
    assert displayed_text(viewer) == "7"
    viewer.setCurrentNode(other)
    assert displayed_text(viewer) == "20"
    viewer.setCurrentNode(source)
    assert displayed_text(viewer) == "7"

    engine.set_script("def source(): return 9\ndef other(): return 20")
    assert displayed_text(viewer) == "9"
    engine.delete(source)
    assert displayed_text(viewer) == "No current node selected"


def test_viewer_displays_operator_failure_and_recovers_on_script_edit(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("def source(): raise ValueError('Broken operator')")
    source = engine.node("source")
    viewer = OutputViewer(engine)
    qtbot.addWidget(viewer)
    viewer.setCurrentNode(source)
    assert "Broken operator" in displayed_text(viewer)
    engine.set_script("def source(): return None")
    assert displayed_text(viewer) == "None"


def test_script_editor_keeps_last_working_program_during_invalid_edit(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    script = "def source(): return 7"
    engine = make_engine(script)
    source = engine.node("source")
    viewer = OutputViewer(engine)
    editor = ProviderView(engine)
    qtbot.addWidget(viewer)
    qtbot.addWidget(editor)
    viewer.setCurrentNode(source)
    editor.script_view.setPlainText("def source(:")
    assert engine.script() == script
    assert editor.script_view.toolTip()
    assert displayed_text(viewer) == "7"
    editor.script_view.setPlainText("def source(): return 11")
    assert displayed_text(viewer) == "11"
    assert editor.script_view.toolTip() == ""


def test_viewer_receives_failure_of_selected_nodes_dependency(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("def source(): return 7\ndef target(value): return value * 2")
    source = engine.node("source")
    target = engine.node("target", value=source)
    viewer = OutputViewer(engine)
    qtbot.addWidget(viewer)
    viewer.setCurrentNode(target)
    assert displayed_text(viewer) == "14"
    with pytest.raises(ValueError, match="Broken dependency"):
        engine.set_script(
            "def source(): raise ValueError('Broken dependency')\n"
            "def target(value): return value * 2"
        )
    assert "Broken dependency" in displayed_text(viewer)
    engine.set_script("def source(): return 9\ndef target(value): return value * 2")
    assert displayed_text(viewer) == "18"
