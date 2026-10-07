import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QEvent, QSignalBlocker, Qt
from qtpy.QtGui import QKeyEvent
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from myqtx.formwidget import (
    Interactive,
    FormWidget,
    _form_from_function,
)

SubmitBehaviour = FormWidget.SubmitBehaviour


def test_form_submits_independent_snapshots(qtbot: QtBot) -> None:
    form = FormWidget()
    form.insertEditor("name", QLineEdit())
    qtbot.addWidget(form)
    submissions: list[dict[str, object]] = []
    changes: list[tuple[str, object]] = []
    form.submitted.connect(submissions.append)
    form.value_changed.connect(lambda name, value: changes.append((name, value)))

    form.submit()
    form.submit()
    form.set_value("name", "Ada")

    assert submissions == [{"name": ""}, {"name": ""}]
    assert changes == [("name", "Ada")]
    submissions[0]["name"] = "edited snapshot"
    assert submissions[1] == {"name": ""}
    assert form.value("name") == "Ada"


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
@pytest.mark.parametrize("target_type", [QLineEdit, QCheckBox, QPushButton])
def test_enter_submits_once_from_each_control(
    qtbot: QtBot, key: Qt.Key, target_type: type[QWidget],
) -> None:
    def configure(name: str, enabled: bool = True) -> None:
        pass

    form = _form_from_function(configure)
    qtbot.addWidget(form)
    form.show()
    submissions: list[dict[str, object]] = []
    form.submitted.connect(submissions.append)

    target = form.findChild(target_type)
    assert target is not None
    target.setFocus()
    qtbot.keyClick(target, key)

    assert submissions == [{"name": "", "enabled": True}]


def test_auto_enter_submits_current_widget_values(qtbot: QtBot) -> None:
    def configure(count: int, scale: float) -> None:
        pass

    form = _form_from_function(configure, submit_behaviour=SubmitBehaviour.AUTO)
    qtbot.addWidget(form)
    form.show()
    count_editor, scale_editor = form.findChildren(QLineEdit)
    submissions: list[dict[str, object]] = []
    form.submitted.connect(submissions.append)

    # Reading values does not depend on receiving change signals.
    with QSignalBlocker(count_editor), QSignalBlocker(scale_editor):
        count_editor.setText("42")
        scale_editor.setText("2.5")
    assert form.value("count") == 42
    assert form.as_dict() == {"count": 42, "scale": 2.5}
    qtbot.keyClick(count_editor, Qt.Key.Key_Return)

    assert submissions == [{"count": 42, "scale": 2.5}]
    qtbot.keyClick(count_editor, Qt.Key.Key_Return)
    assert submissions == [
        {"count": 42, "scale": 2.5},
        {"count": 42, "scale": 2.5},
    ]


def test_auto_submits_programmatic_changes_once(qtbot: QtBot) -> None:
    form = FormWidget(submit_behaviour=SubmitBehaviour.AUTO)
    editor = QLineEdit()
    form.insertEditor("name", editor)
    qtbot.addWidget(form)
    submissions: list[dict[str, object]] = []
    form.submitted.connect(submissions.append)

    form.set_value("name", "Ada")
    form.set_value("name", "Ada")
    assert submissions == [{"name": "Ada"}]
    assert editor.text() == "Ada"

    form.set_submit_behaviour(SubmitBehaviour.SUBMIT)
    form.set_value("name", "Grace")
    assert submissions == [{"name": "Ada"}]
    form.submit()
    assert submissions == [{"name": "Ada"}, {"name": "Grace"}]


@pytest.mark.parametrize(
    "initial_behaviour, next_behaviour",
    [
        (SubmitBehaviour.SUBMIT, SubmitBehaviour.AUTO),
        (SubmitBehaviour.AUTO, SubmitBehaviour.SUBMIT),
    ],
)
def test_button_follows_submission_behaviour(
    qtbot: QtBot,
    initial_behaviour: SubmitBehaviour,
    next_behaviour: SubmitBehaviour,
) -> None:
    form = FormWidget(submit_behaviour=initial_behaviour)
    qtbot.addWidget(form)
    form.show()
    button = form.findChild(QPushButton)
    assert button is not None
    assert button.isHidden() == (initial_behaviour == SubmitBehaviour.AUTO)

    changes: list[SubmitBehaviour] = []
    submissions: list[dict[str, object]] = []
    form.submit_behaviour_changed.connect(changes.append)
    form.submitted.connect(submissions.append)
    form.set_submit_behaviour(initial_behaviour)
    assert changes == []

    form.set_submit_behaviour(next_behaviour)
    assert button.isHidden() == (next_behaviour == SubmitBehaviour.AUTO)
    assert changes == [next_behaviour]
    assert submissions == []


def test_invalid_numeric_text_blocks_button_and_enter(qtbot: QtBot) -> None:
    def configure(scale: float = 1.0) -> None:
        pass

    form = _form_from_function(configure)
    qtbot.addWidget(form)
    form.show()
    editor = form.findChild(QLineEdit)
    button = form.findChild(QPushButton)
    assert editor is not None and button is not None
    submissions: list[dict[str, object]] = []
    form.submitted.connect(submissions.append)

    editor.setText("-")
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert submissions == []
    with pytest.raises(ValueError):
        form.value("scale")
    with pytest.raises(ValueError):
        form.as_dict()
    assert editor.text() == "-"
    assert editor.toolTip()

    editor.setText("2.5")
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert submissions == [{"scale": 2.5}]
    assert editor.toolTip() == ""


def test_auto_submission_waits_for_all_fields_to_be_valid(qtbot: QtBot) -> None:
    def configure(name: str, scale: float = 1.0) -> None:
        pass

    form = _form_from_function(configure, submit_behaviour=SubmitBehaviour.AUTO)
    qtbot.addWidget(form)
    name_editor, scale_editor = form.findChildren(QLineEdit)
    submissions: list[dict[str, object]] = []
    form.submitted.connect(submissions.append)

    scale_editor.setText("-")
    name_editor.setText("Ada")
    assert form.value("name") == "Ada"
    assert submissions == []
    # Restoring the original number still signals that the form is valid again.
    scale_editor.setText("1.0")
    assert submissions == [{"name": "Ada", "scale": 1.0}]


def test_repeated_enter_does_not_submit(qtbot: QtBot) -> None:
    form = FormWidget()
    editor = QLineEdit()
    form.insertEditor("name", editor)
    qtbot.addWidget(form)
    submissions: list[dict[str, object]] = []
    form.submitted.connect(submissions.append)

    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Return,
        Qt.KeyboardModifier.NoModifier, "\r", True,
    )
    QApplication.sendEvent(editor, event)
    assert submissions == []


def test_multiline_editor_keeps_enter_for_newlines(qtbot: QtBot) -> None:
    form = FormWidget()
    editor = QPlainTextEdit()
    form.insertEditor("notes", editor)
    qtbot.addWidget(form)
    form.show()
    submissions: list[dict[str, object]] = []
    form.submitted.connect(submissions.append)

    qtbot.keyClick(editor, Qt.Key.Key_Return)

    assert editor.toPlainText() == "\n"
    assert form.value("notes") == "\n"
    assert submissions == []


def test_interactive_executes_once_after_mode_switches(qtbot: QtBot) -> None:
    calls: list[str] = []

    def greet(name: str) -> str:
        calls.append(name)
        return f"Hello, {name}"

    interactive = Interactive(greet)
    qtbot.addWidget(interactive)
    interactive.show()
    editor = interactive.findChild(QLineEdit)
    button = interactive.findChild(QPushButton)
    assert editor is not None and button is not None
    results: list[object] = []
    interactive.executed.connect(results.append)

    editor.setText("Ada")
    assert calls == []
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert calls == ["Ada", "Ada"]
    assert results == ["Hello, Ada", "Hello, Ada"]

    interactive.set_execution_behaviour(SubmitBehaviour.AUTO)
    interactive.set_execution_behaviour(SubmitBehaviour.SUBMIT)
    interactive.set_execution_behaviour(SubmitBehaviour.AUTO)
    assert button.isHidden()
    editor.setText("Grace")
    assert calls == ["Ada", "Ada", "Grace"]

    interactive.set_execution_behaviour(SubmitBehaviour.SUBMIT)
    editor.setText("Linus")
    assert calls == ["Ada", "Ada", "Grace"]
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert calls == ["Ada", "Ada", "Grace", "Linus"]


def test_function_forms_have_independent_values(qtbot: QtBot) -> None:
    def greet(name: str = "Original") -> str:
        return name

    first = _form_from_function(greet)
    second = _form_from_function(greet)
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    first.set_value("name", "Ada")
    assert first.value("name") == "Ada"
    assert second.value("name") == "Original"


def test_function_helper_preserves_types_defaults_and_initial_values(qtbot: QtBot) -> None:
    calls: list[dict[str, object]] = []

    def describe(name: "str", count: int = 3, *, enabled: bool = True) -> str:
        calls.append({"name": name, "count": count, "enabled": enabled})
        return name

    form = _form_from_function(describe, initial={"count": 5})
    qtbot.addWidget(form)
    assert calls == []
    assert form.as_dict() == {"name": "", "count": 5, "enabled": True}
    checkbox = form.findChild(QCheckBox)
    assert checkbox is not None and checkbox.isChecked()

    with pytest.raises(TypeError, match="expects bool"):
        form.set_value("enabled", 1)
    assert form.value("enabled") is True

    form.submitted.connect(lambda values: describe(**values))
    form.submit()
    assert calls == [{"name": "", "count": 5, "enabled": True}]


def test_function_helper_handles_required_and_unannotated_defaults(qtbot: QtBot) -> None:
    # Missing annotations are intentional: exercise inference from defaults.
    def configure(name: str, count: int, scale: float, enabled: bool, title="Preview") -> None:
        pass

    form = _form_from_function(configure)
    qtbot.addWidget(form)
    assert form.as_dict() == {
        "name": "", "count": 0, "scale": 0.0, "enabled": False, "title": "Preview",
    }


def test_function_helper_requires_annotation_or_default() -> None:
    def configure(value) -> None:  # Missing annotation is intentional.
        pass

    with pytest.raises(TypeError, match="needs a type annotation or a default"):
        _form_from_function(configure)


def test_function_helper_rejects_positional_only_parameters() -> None:
    def configure(value: str, /) -> None:
        pass

    with pytest.raises(TypeError, match="Unsupported parameter kind"):
        _form_from_function(configure)


def test_function_helper_rejects_variadic_arguments() -> None:
    def configure(*values: int) -> None:
        pass

    with pytest.raises(TypeError, match="Unsupported parameter kind"):
        _form_from_function(configure)


def test_function_helper_rejects_variadic_keywords() -> None:
    def configure(**values: str) -> None:
        pass

    with pytest.raises(TypeError, match="Unsupported parameter kind"):
        _form_from_function(configure)


def test_function_helper_rejects_unsupported_types() -> None:
    def configure(value: list[int]) -> None:
        pass

    with pytest.raises(TypeError, match="Unsupported type"):
        _form_from_function(configure)


def test_function_helper_rejects_unknown_initial_parameters() -> None:
    def configure(count: int = 3) -> None:
        pass

    with pytest.raises(ValueError, match="Unknown parameters"):
        _form_from_function(configure, initial={"missing": 5})


def test_function_helper_rejects_initial_values_of_wrong_type() -> None:
    def configure(count: int = 3) -> None:
        pass

    with pytest.raises(TypeError, match="expects int"):
        _form_from_function(configure, initial={"count": True})


def test_default_binding_reads_back_clamped_values(qtbot: QtBot) -> None:
    form = FormWidget()
    spinbox = QSpinBox()
    spinbox.setRange(0, 10)
    spinbox.setValue(3)
    form.insertEditor("count", spinbox)
    qtbot.addWidget(form)
    changes: list[tuple[str, object]] = []
    form.value_changed.connect(lambda name, value: changes.append((name, value)))

    assert form.value("count") == 3
    form.set_value("count", 100)
    assert spinbox.value() == 10
    assert form.value("count") == 10
    assert changes == [("count", 10)]


def test_overridden_getter_setter_ignore_signal_payload(qtbot: QtBot) -> None:
    form = FormWidget()
    combo = QComboBox()
    combo.addItem("First", 10)
    combo.addItem("Second", 20)

    def set_choice(value: object) -> None:
        combo.setCurrentIndex(combo.findData(value))

    form.insertEditor(
        "choice", combo, getter=combo.currentData, setter=set_choice,
        signal=combo.currentTextChanged,
    )
    qtbot.addWidget(form)
    assert form.value("choice") == 10
    combo.setCurrentIndex(1)
    assert form.value("choice") == 20
    form.set_value("choice", 10)
    assert form.value("choice") == 10


def test_signal_override_controls_notifications_but_not_reads(qtbot: QtBot) -> None:
    form = FormWidget(submit_behaviour=SubmitBehaviour.AUTO)
    editor = QLineEdit("old")
    form.insertEditor("name", editor, signal=editor.editingFinished)
    qtbot.addWidget(form)
    changes: list[tuple[str, object]] = []
    submissions: list[dict[str, object]] = []
    form.value_changed.connect(lambda name, value: changes.append((name, value)))
    form.submitted.connect(submissions.append)

    form.set_value("name", "new")
    assert form.value("name") == "new"
    assert changes == []
    assert submissions == []

    editor.editingFinished.emit()
    assert changes == [("name", "new")]
    assert submissions == [{"name": "new"}]


def test_custom_composite_widget_binding(qtbot: QtBot) -> None:
    form = FormWidget(submit_behaviour=SubmitBehaviour.AUTO)
    container = QWidget()
    editor = QLineEdit("initial", container)
    with pytest.raises(ValueError, match="Provide a getter"):
        form.insertEditor("custom", container)

    form.insertEditor(
        "custom", container, getter=editor.text, setter=editor.setText,
        signal=editor.textChanged,
    )
    qtbot.addWidget(form)
    submissions: list[dict[str, object]] = []
    form.submitted.connect(submissions.append)

    form.set_value("custom", "updated")
    assert submissions == [{"custom": "updated"}]
    assert editor.text() == "updated"


def test_insert_remove_disconnects_and_preserves_widget_for_reuse(qtbot: QtBot) -> None:
    form = FormWidget()
    first = QLineEdit("first")
    last = QLineEdit("last")
    middle = QLineEdit("middle")
    form.insertEditor("first", first)
    form.insertEditor("last", last)
    form.insertEditor("middle", middle, index=1)
    qtbot.addWidget(form)

    assert list(form.as_dict()) == ["first", "middle", "last"]
    layout = form.layout()
    assert isinstance(layout, QFormLayout)
    assert layout.getWidgetPosition(middle)[0] == 1
    changes: list[tuple[str, object]] = []
    form.value_changed.connect(lambda name, value: changes.append((name, value)))

    removed = form.removeEditor("middle")
    assert removed is middle
    assert removed.parent() is None
    assert list(form.as_dict()) == ["first", "last"]

    other = FormWidget()
    qtbot.addWidget(other)
    other.insertEditor("reused", removed)
    middle.setText("changed")
    assert changes == []
    assert other.value("reused") == "changed"


def test_invalid_registration_leaves_existing_parameters_intact(qtbot: QtBot) -> None:
    form = FormWidget()
    editor = QLineEdit("existing")
    form.insertEditor("name", editor)
    qtbot.addWidget(form)
    unused = QLineEdit()
    qtbot.addWidget(unused)

    with pytest.raises(ValueError, match="already exists"):
        form.insertEditor("name", unused)
    with pytest.raises(ValueError, match="already registered"):
        form.insertEditor("another", editor)
    with pytest.raises(IndexError):
        form.insertEditor("other", unused, index=5)
    with pytest.raises(KeyError):
        form.removeEditor("missing")
    assert form.as_dict() == {"name": "existing"}
