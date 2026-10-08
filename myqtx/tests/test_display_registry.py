from dataclasses import dataclass

import numpy as np
import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QWidget

from myqtx.cmdstage import HTML, Image, ImageCompare, Markdown
from myqtx import DisplayView, DisplayWidget
from myqtx.displayviews import HTMLView, ImageCompareView, ImageView, MarkdownView, TextView


@dataclass
class Reading:
    value: int


@dataclass
class SpecialReading(Reading):
    pass


class ReadingView(DisplayView[Reading]):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: list[int] = []

    def set_data(self, data: Reading) -> None:
        if data.value < 0:
            raise ValueError("Negative reading")
        self.values.append(data.value)


class SpecialReadingView(ReadingView):
    pass


@pytest.fixture
def display(qtbot: QtBot) -> DisplayWidget:
    widget = DisplayWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    QApplication.processEvents()
    return widget


def test_registry_reuses_view_and_is_isolated(display: DisplayWidget, qtbot: QtBot) -> None:
    other = DisplayWidget()
    qtbot.addWidget(other)
    display.register_viewer(Reading, ReadingView)
    display.display(Reading(1))
    view = display.current_viewer
    display.display(Reading(2))
    assert display.current_viewer is view
    assert isinstance(view, ReadingView) and view.values == [1, 2]
    other.display(Reading(3))
    assert isinstance(other.current_viewer, TextView)


def test_registry_uses_mro_and_allows_replacement(display: DisplayWidget) -> None:
    display.register_viewer(Reading, ReadingView)
    display.display(SpecialReading(1))
    assert type(display.current_viewer) is ReadingView
    display.register_viewer(SpecialReading, SpecialReadingView)
    display.display(SpecialReading(2))
    assert type(display.current_viewer) is SpecialReadingView
    previous = display.current_viewer
    display.register_viewer(SpecialReading, ReadingView)
    assert display.current_viewer is previous
    display.display(SpecialReading(3))
    assert type(display.current_viewer) is ReadingView
    assert display.current_viewer is not previous


def test_failed_view_creation_preserves_current_content(display: DisplayWidget) -> None:
    display.display("previous")
    previous = display.current_viewer
    display.register_viewer(Reading, ReadingView)
    with pytest.raises(ValueError, match="Negative"):
        display.display(Reading(-1))
    assert display.current_viewer is previous
    assert isinstance(previous, TextView) and previous.label.text() == "previous"
    display.display(Reading(1))
    assert isinstance(display.current_viewer, ReadingView)


def test_image_wrapper_updates_existing_canvas(display: DisplayWidget) -> None:
    source = np.full((600, 900, 3), 127, dtype=np.uint8)
    display.display(Image(source))
    view = display.current_viewer
    assert isinstance(view, ImageView)
    view.canvas.scale(2, 2)
    scale = view.canvas.transform().m11()
    source[:] = 0
    assert view.canvas.item.pixmap().toImage().pixelColor(0, 0).red() == 127
    display.display(Image(source))
    assert display.current_viewer is view
    assert view.canvas.transform().m11() == pytest.approx(scale)
    assert view.canvas.item.pixmap().toImage().pixelColor(0, 0).red() == 0


def test_rich_text_is_explicit_and_switches_cleanly(display: DisplayWidget) -> None:
    display.display("<b>Hello</b>")
    view = display.current_viewer
    assert isinstance(view, TextView)
    assert view.label.textFormat() == Qt.TextFormat.PlainText
    assert view.label.text() == "<b>Hello</b>"
    display.display(HTML("<h1>Hello</h1><p>World</p>"))
    html = display.current_viewer
    assert isinstance(html, HTMLView)
    assert html.browser.toPlainText() == "Hello\nWorld"
    display.display(Markdown("# Heading\n\n**Content**"))
    markdown = display.current_viewer
    assert isinstance(markdown, MarkdownView)
    assert markdown.browser.toPlainText() == "Heading\nContent"
    assert html.browser.toPlainText() == ""
    display.display(Markdown("Updated"))
    assert display.current_viewer is markdown
    assert markdown.browser.toPlainText() == "Updated"


def test_comparison_wipe_and_updates_preserve_state(display: DisplayWidget) -> None:
    a = np.zeros((100, 200, 3), dtype=np.uint8)
    b = np.zeros_like(a)
    a[:, :, 0] = 255
    b[:, :, 2] = 255
    display.display(ImageCompare(a, b))
    view = display.current_viewer
    assert isinstance(view, ImageCompareView)
    rendered = view.canvas.item.pixmap().toImage()
    assert rendered.pixelColor(25, 50) == Qt.GlobalColor.red
    assert rendered.pixelColor(175, 50) == Qt.GlobalColor.blue
    view.slider.setValue(0)
    assert view.canvas.item.pixmap().toImage().pixelColor(0, 50) == Qt.GlobalColor.blue
    view.slider.setValue(1000)
    assert view.canvas.item.pixmap().toImage().pixelColor(199, 50) == Qt.GlobalColor.red
    view.slider.setValue(250)
    view.canvas.scale(2, 2)
    scale = view.canvas.transform().m11()
    display.display(ImageCompare(b, a))
    assert display.current_viewer is view
    assert view.slider.value() == 250
    assert view.canvas.transform().m11() == pytest.approx(scale)
    rendered = view.canvas.item.pixmap().toImage()
    assert rendered.pixelColor(25, 50) == Qt.GlobalColor.blue
    assert rendered.pixelColor(175, 50) == Qt.GlobalColor.red


def test_comparison_validation_preserves_previous_images(display: DisplayWidget) -> None:
    a = np.zeros((10, 20, 3), dtype=np.uint8)
    display.display(ImageCompare(a, a + 255))
    view = display.current_viewer
    assert isinstance(view, ImageCompareView)
    before = view.canvas.item.pixmap().toImage()
    with pytest.raises(ValueError, match="same width and height"):
        display.display(ImageCompare(a, np.zeros((11, 20, 3), dtype=np.uint8)))
    assert display.current_viewer is view
    assert view.canvas.item.pixmap().toImage() == before
    display.clear()
    assert display.current_viewer is None
    assert view.canvas.item.pixmap().isNull()


def test_comparison_preserves_alpha(display: DisplayWidget) -> None:
    a = np.zeros((10, 20, 4), dtype=np.uint8)
    b = np.full((10, 20, 4), 255, dtype=np.uint8)
    display.display(ImageCompare(a, b))
    view = display.current_viewer
    assert isinstance(view, ImageCompareView)
    rendered = view.canvas.item.pixmap().toImage()
    assert rendered.pixelColor(0, 0).alpha() == 0
    assert rendered.pixelColor(19, 0).alpha() == 255
