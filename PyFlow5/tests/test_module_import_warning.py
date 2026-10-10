from pathlib import Path
from unittest.mock import Mock

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QSettings, Qt
from qtpy.QtWidgets import QDialog, QMessageBox

from pyflow5.views import pyflow5_window
from pygraphrt import ImportModuleRT


@pytest.fixture
def window(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> pyflow5_window.PyFlow5Window:
    class TestSettings(QSettings):
        def __init__(self, *_args: object) -> None:
            super().__init__(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(pyflow5_window, "QSettings", TestSettings)
    window = pyflow5_window.PyFlow5Window()
    qtbot.addWidget(window)
    return window


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> list[QMessageBox]:
    dialogs: list[QMessageBox] = []

    def capture_warning(dialog: QMessageBox) -> int:
        dialogs.append(dialog)
        return int(QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(pyflow5_window.QMessageBox, "exec", capture_warning)
    return dialogs


@pytest.mark.parametrize(
    ("source", "error_type", "error_message"),
    [
        ("def broken(:\n", "SyntaxError", "invalid syntax"),
        ("raise ValueError('broken import')\n", "ValueError", "broken import"),
        (
            "try:\n    raise KeyError('missing')\n"
            "except KeyError as error:\n    raise ValueError('broken import') from error\n",
            "ValueError",
            "broken import",
        ),
        ("__all__ = 42\n", "ScriptEvaluationError", "__all__ must be a list or tuple"),
        ("def value() -> int: return 1\n", None, None),
        ("", None, None),
    ],
)
def test_import_warns_only_when_evaluation_fails(
    window: pyflow5_window.PyFlow5Window,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    warnings: list[QMessageBox],
    source: str,
    error_type: str | None,
    error_message: str | None,
) -> None:
    path = tmp_path / "external.py"
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(
        pyflow5_window.QFileDialog, "exec_", Mock(return_value=QDialog.DialogCode.Accepted),
    )
    monkeypatch.setattr(
        pyflow5_window.QFileDialog, "selectedFiles", Mock(return_value=[str(path)]),
    )
    window.importModule()

    document = window._document
    model = document.modules_model
    assert model.rowCount() == 1
    index = document.modulesselection_model.currentIndex()
    module = model.mapToSource(index)
    assert isinstance(module, ImportModuleRT)
    assert module.get_source() == source
    assert window._module_details_view._code_editor.toPlainText() == source
    assert window._module_details_view._code_editor.isReadOnly()
    assert path.read_text(encoding="utf-8") == source

    if error_type is None:
        assert warnings == []
        assert module.get_status() == "VALID"
    else:
        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.parent() is window
        assert warning.windowTitle() == "Script has issues"
        assert warning.textFormat() == Qt.TextFormat.PlainText
        assert str(path) in warning.informativeText()
        assert error_message is not None
        assert warning.text().startswith(f"{error_type}: ")
        assert error_message in warning.text()
        details = warning.detailedText()
        assert "Traceback (most recent call last)" in details
        assert error_type in details
        assert error_message in details
        if error_type == "SyntaxError":
            assert "def broken(:" in details
            assert "line 1" in details
        if error_type == "ValueError":
            assert "<script:external.py>" in details
            assert "ScriptEvaluationError" not in details
        if "KeyError" in source:
            assert "KeyError: 'missing'" in details
            assert "direct cause" in details
        assert isinstance(module.get_status(), Exception)
        assert list(module.operators()) == []


def test_cancelled_import_does_not_warn(
    window: pyflow5_window.PyFlow5Window,
    monkeypatch: pytest.MonkeyPatch,
    warnings: list[QMessageBox],
) -> None:
    monkeypatch.setattr(
        pyflow5_window.QFileDialog, "exec_", Mock(return_value=QDialog.DialogCode.Rejected),
    )
    window.importModule()

    assert warnings == []
    assert window._document.modules_model.rowCount() == 0
