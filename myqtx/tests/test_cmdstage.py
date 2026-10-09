from dataclasses import dataclass
import json
from multiprocessing import shared_memory
import subprocess
import sys
from typing import Any
import uuid

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from myqtx.cmdstage import HTML, Image, ImageCompare, Markdown, Stage
from myqtx.cmdstage.transport import decode_payload, encode_payload
from myqtx.cmdstage.viewer import ViewerServer
from myqtx.displayviews import ImageCompareView
from myqtx.cmdstage_old.stage import SharedImageViewer


@pytest.mark.parametrize(
    "source",
    [
        np.arange(5 * 7 * 3, dtype=np.uint8).reshape(5, 7, 3)[:, ::-1],
        np.linspace(0, 1, 35, dtype=np.float32).reshape(5, 7),
        np.zeros((0, 3), dtype=np.uint8),
        np.zeros((5, 7, 4), dtype=np.uint8),
        np.array(42, dtype=np.int32),
    ],
)
def test_array_transport_owns_data_and_releases_shared_memory(source: np.ndarray) -> None:
    original = source.copy()
    with encode_payload(Image(source)) as payload:
        # Exercise the actual JSON serialization, not an in-memory shortcut.
        decoded = decode_payload(json.loads(json.dumps(payload)))
        name = payload["fields"]["data"]["name"]
        source[...] = 0
    assert isinstance(decoded, Image)
    np.testing.assert_array_equal(decoded.data, original)
    assert decoded.data.dtype == original.dtype
    with pytest.raises(FileNotFoundError):
        shared_memory.SharedMemory(name=name, create=False)


def test_nested_builtin_payloads_roundtrip() -> None:
    source = {"html": HTML("<b>Hello</b>"), "markdown": Markdown("# Header"), 3: (None, True, 2.5)}
    with encode_payload(source) as payload:
        assert decode_payload(json.loads(json.dumps(payload))) == source


def test_encoding_failure_cleans_up_already_allocated_arrays(monkeypatch: pytest.MonkeyPatch) -> None:
    original = shared_memory.SharedMemory
    names: list[str] = []

    def track_allocation(*args: Any, **kwargs: Any) -> shared_memory.SharedMemory:
        block = original(*args, **kwargs)
        if kwargs.get("create"):
            names.append(block.name)
        return block

    monkeypatch.setattr(shared_memory, "SharedMemory", track_allocation)
    with pytest.raises(TypeError, match="does not support"):
        with encode_payload([np.zeros((5, 7), dtype=np.uint8), object()]):
            pytest.fail("Unsupported objects must fail during encoding")
    assert names
    for name in names:
        with pytest.raises(FileNotFoundError):
            original(name=name, create=False)


def test_decoder_rejects_invalid_shared_memory_metadata() -> None:
    with encode_payload(np.zeros((2, 3), dtype=np.uint8)) as payload:
        with pytest.raises(ValueError, match="too small"):
            decode_payload({**payload, "shape": [100, 100]})
        with pytest.raises(ValueError, match="dtype"):
            decode_payload({**payload, "dtype": "O"})
        with pytest.raises(ValueError, match="dimensions"):
            decode_payload({**payload, "shape": [-1, 3]})


def test_server_retains_comparison_after_sender_cleanup(qtbot: QtBot) -> None:
    server = ViewerServer(f"cmdstage-test-{uuid.uuid4().hex}")
    qtbot.addWidget(server.display_widget)
    try:
        a = np.zeros((10, 20, 3), dtype=np.uint8)
        with encode_payload(ImageCompare(a, a + 255)) as payload:
            assert server.handle({"action": "show", "data": payload}) == {"ok": True}
        a[:] = 127
        view = server.display_widget.current_viewer
        assert isinstance(view, ImageCompareView)
        rendered = view.canvas.item.pixmap().toImage()
        assert rendered.pixelColor(0, 0).red() == 0
        assert rendered.pixelColor(19, 0).red() == 255
    finally:
        server.server.close()
        server.display_widget.close()



@pytest.mark.parametrize("b_shape", [(2, 3), (40, 60), (20, 5), (10, 20)])
def test_comparison_fits_b_to_a(qtbot: QtBot, b_shape: tuple[int, int]) -> None:
    view = ImageCompareView()
    qtbot.addWidget(view)
    a = np.zeros((10, 20, 3), dtype=np.uint8)
    a[..., 0] = 255
    b = np.zeros((*b_shape, 3), dtype=np.uint8)
    b[..., 2] = 255
    original_b = b.copy()
    view.set_data(ImageCompare(a, b))

    for slider_value in (0, 500, 1000):
        view.slider.setValue(slider_value)
        rendered = view.canvas.item.pixmap().toImage()
        assert (rendered.width(), rendered.height()) == (20, 10)
        split = 20 * slider_value // 1000
        for x in range(20):
            expected = (255, 0, 0, 255) if x < split else (0, 0, 255, 255)
            assert rendered.pixelColor(x, 9).getRgb() == expected
    np.testing.assert_array_equal(b, original_b)


def test_stage_end_to_end_and_error_recovery(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    a = np.zeros((30, 40, 3), dtype=np.uint8)
    stage = Stage()
    stage.clear()
    stage.close()
    assert stage.process is None
    try:
        stage.show()
        process = stage.process
        assert process is not None and process.poll() is None
        stage.start()
        assert stage.process is process
        stage.show(Image(a))
        stage.show(ImageCompare(a, a + 255))
        a[:] = 127
        stage.show(HTML("<b>Hello</b>"))
        stage.show(Markdown("# Hello"))
        stage.show("plain text")
        stage.show({"result": [1, 2, 3]})
        stage.show(ImageCompare(a, a[:1]))
        with pytest.raises(RuntimeError, match="Image dimensions must be positive") as error:
            stage.show(ImageCompare(a, a[:0]))
        stderr = capfd.readouterr().err
        assert "Traceback (most recent call last)" in stderr
        assert f"ValueError: {error.value}" in stderr
        assert stage.process is process and process.poll() is None
        stage.show(Image(a))
        stage.clear()
    finally:
        stage.close()
    assert process is not None and process.poll() == 0
    assert stage.process is None
    stage.close()
    try:
        stage.show(Image(a))
        assert stage.process is not process
    finally:
        stage.close()


def test_module_api_reuses_the_shared_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    import stage
    from myqtx import cmdstage

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert stage.show is cmdstage.show
    try:
        stage.show()
        process = cmdstage._stage.process
        stage.show(stage.HTML("<b>Hello</b>"))
        assert cmdstage._stage.process is process
        stage.clear()
    finally:
        stage.close()
    assert process is not None and process.poll() == 0


def test_show_reopens_a_closed_window(qtbot: QtBot) -> None:
    server = ViewerServer(f"cmdstage-test-{uuid.uuid4().hex}")
    qtbot.addWidget(server.display_widget)
    try:
        server.display_widget.close()
        assert not server.display_widget.isVisible()
        with encode_payload("Hello again") as payload:
            server.handle({"action": "show", "data": payload})
        assert server.display_widget.isVisible()
    finally:
        server.server.close()
        server.display_widget.close()


def test_custom_data_is_local_only() -> None:
    @dataclass
    class Custom:
        value: int

    with pytest.raises(TypeError, match="Stage transport does not support Custom"):
        with encode_payload(Custom(1)):
            pytest.fail("Custom GUI registration is outside the current scope")


def test_legacy_viewer_keeps_rgb_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[object] = []

    def capture(self: Stage, data: object) -> None:
        received.append(data)

    monkeypatch.setattr(Stage, "show", capture)
    viewer = SharedImageViewer()
    viewer.show([[[255, 0, 0]]])
    assert isinstance(received[0], Image)
    np.testing.assert_array_equal(received[0].data, np.array([[[255, 0, 0]]], dtype=np.uint8))
    with pytest.raises(ValueError, match="H x W x 3"):
        viewer.show(np.zeros((10, 10), dtype=np.uint8))


def test_public_import_does_not_start_a_viewer() -> None:
    result = subprocess.run(
        [sys.executable, "-B", "-c", """
from unittest.mock import patch

with patch("subprocess.Popen") as launch:
    import stage
    from myqtx import cmdstage
    from qtpy.QtWidgets import QApplication

    launch.assert_not_called()
    assert cmdstage._stage.process is None
    assert QApplication.instance() is None
"""],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
