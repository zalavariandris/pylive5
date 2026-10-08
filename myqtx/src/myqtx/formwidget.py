import builtins
import inspect
from myqtx.displaywidget import DisplayWidget
import numpy as np
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import pathlib
from typing import Any, TypeVar
from enum import Enum, StrEnum
from functools import partial
from typing import NamedTuple, get_type_hints
import warnings


from qtpy.QtCore import (
    QEvent, 
    QObject, 
    Qt, 
    Signal, 
    Slot,
    SignalInstance
)

from qtpy.QtGui import QKeyEvent
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from myqtx import QPathEdit

@dataclass
class _Binding:
    widget: QWidget
    getter: Callable[[], Any]
    setter: Callable[[Any], None]
    signal: SignalInstance
    

class FormWidget(QFrame):
    """Read values from registered widgets and submit valid forms.

    Change notifications follow each widget's registered signal. AUTO submits
    on those notifications; explicit submissions always read the current values.
    """

    value_changed = Signal(str, object)
    submitted = Signal(object)
    submit_behaviour_changed = Signal(object)

    class SubmitBehaviour(StrEnum):
        AUTO = "auto"
        SUBMIT = "submit"

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        submit_behaviour: SubmitBehaviour = SubmitBehaviour.SUBMIT,
    ) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        # private members
        self._bindings: dict[str, _Binding] = {}
        self._callbacks: dict[str, tuple[SignalInstance, Callable[..., None]]] = {}
        self._submit_behaviour = self.SubmitBehaviour(submit_behaviour)
        
        self._form_layout = QFormLayout(self)
        self._submit_button = QPushButton("Submit", self)
        self._submit_button.setAutoDefault(False)
        self._submit_button.clicked.connect(self.submit)
        self._submit_button.installEventFilter(self)
        self._form_layout.addRow(self._submit_button)
        self._submit_button.setVisible(
            self._submit_behaviour == self.SubmitBehaviour.SUBMIT
        )

    def insertEditor(
        self,
        index: int,
        name: str,
        widget: QWidget,
        *,
        getter: Callable[[], object] | None = None,
        setter: Callable[[object], None] | None = None,
        signal: SignalInstance | None = None,
    ) -> None:
        """Register a widget, inferring omitted bindings from its user property."""
        if name in self._bindings:
            raise ValueError(f"Editor with name {name!r} already exists")
        
        if any(binding.widget is widget for binding in self._bindings.values()):
            raise ValueError("This widget is already registered")

        if index is None:
            index = len(self._bindings)

        if not 0 <= index <= len(self._bindings):
            raise IndexError(f"Invalid editor index: {index}")

        # prop = widget.metaObject().userProperty()
        # if getter is None:
        #     if not prop.isValid() or not prop.isReadable():
        #         raise ValueError(f"Provide a getter for {name!r}")
        #     getter = partial(prop.read, widget)

        # if setter is None:
        #     if not prop.isValid() or not prop.isWritable():
        #         raise ValueError(f"Provide a setter for {name!r}")

        #     def write_property(value: object) -> None:
        #         if not prop.write(widget, value):
        #             raise ValueError(f"Could not set {name!r}")

        #     setter = write_property

        # if signal is None:
        #     if not prop.isValid() or not prop.hasNotifySignal():
        #         raise ValueError(f"Provide a change signal for {name!r}")
        #     signal_name = bytes(prop.notifySignal().name()).decode()
        #     signal = getattr(widget, signal_name)

        # support default bindings for built in widgets #todo: extend, and find out how QtQuick or the QStyleDelegate figures out the bindings automatically
        if getter is None or setter is None or signal is None:
            match widget:
                case QLineEdit() as lineedit:
                    if getter is None:
                        getter = lineedit.text if getter is None else getter
                    if setter is None:
                        setter = lineedit.setText if setter is None else setter
                    if signal is None:
                        signal = lineedit.textChanged if signal is None else signal

                case QCheckBox():
                    if getter is None:
                        getter = widget.isChecked if getter is None else getter
                    if setter is None:
                        setter = widget.setChecked if setter is None else setter
                    if signal is None:
                        signal = widget.stateChanged if signal is None else signal

                case pathlib.Path() as pathedit:
                    if getter is None:
                        getter = pathedit.path if getter is None else getter
                    if setter is None:
                        setter = pathedit.setPath if setter is None else setter
                    if signal is None:
                        signal = pathedit.pathChanged if signal is None else signal
                case _:
                    raise ValueError(f"Provide getter, setter, and signal for {name!r}")

        widget.installEventFilter(self)

        binding = _Binding(
            widget=widget,
            getter=getter,
            setter=setter,
            signal=signal
        )

        callback = partial(self._on_parameter_changed, name)
        self._callbacks[name] = (signal, callback)
        signal.connect(callback)

        bindings = list(self._bindings.items())
        bindings.insert(index, (name, binding))
        self._bindings = dict(bindings)
        self._form_layout.insertRow(index, name, widget)

    def removeEditor(self, name: str) -> QWidget:
        """Disconnect and detach an editor, returning its widget for reuse."""
        binding = self._bindings[name]
        signal, callback = self._callbacks[name]
        signal.disconnect(callback)
        del self._callbacks[name]

        row = self._form_layout.takeRow(binding.widget)
        if row.labelItem is not None:
            label = row.labelItem.widget()
            if label is not None:
                label.deleteLater()

        del self._bindings[name]
        binding.widget.setParent(None)
        return binding.widget

    def clear(self) -> None:
        """Remove all editors and clear the form."""
        for name in list(self._bindings.keys()):
            self.removeEditor(name)

    def submit_behaviour(self) -> SubmitBehaviour:
        return self._submit_behaviour

    def set_submit_behaviour(self, behaviour: SubmitBehaviour) -> None:
        behaviour = self.SubmitBehaviour(behaviour)
        if behaviour == self._submit_behaviour:
            return

        self._submit_behaviour = behaviour
        self._submit_button.setVisible(
            behaviour == self.SubmitBehaviour.SUBMIT
        )
        self.submit_behaviour_changed.emit(behaviour)

    def value(self, name: str) -> object:
        """Read the widget through its getter, raising if its input is invalid."""
        return self._bindings[name].getter()

    def set_value(self, name: str, value: object) -> None:
        """Set the widget value; its registered signal controls notifications."""
        self._bindings[name].setter(value)

    def as_dict(self) -> dict[str, object]:
        """Read all widget values, raising if any getter rejects its input."""
        return {name: self.value(name) for name in self._bindings}

    def _on_parameter_changed(self, name: str, *_args: object) -> None:
        if name not in self._bindings:
            return
        try:
            value = self.value(name)
        except (TypeError, ValueError):
            return

        self.value_changed.emit(name, value)
        if self._submit_behaviour == self.SubmitBehaviour.AUTO:
            self.submit()

    @Slot()
    def submit(self) -> None:
        """Read and submit current values, focusing the first invalid editor."""
        values = {
            name: self.value(name) 
            for name, binding in 
            self._bindings.items()
        }

        self.submitted.emit(values)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() in (
                Qt.KeyboardModifier.NoModifier,
                Qt.KeyboardModifier.KeypadModifier,
            )
        ):
            # Multiline editors keep Enter for inserting a newline.
            widget = watched if isinstance(watched, QWidget) else None
            while widget is not None and widget is not self:
                if isinstance(widget, (QPlainTextEdit, QTextEdit)):
                    return super().eventFilter(watched, event)
                widget = widget.parentWidget()
            if not event.isAutoRepeat():
                self.submit()
            return True
        return super().eventFilter(watched, event)


def _create_function_editor(
    name: str, 
    value_type: type, 
    initial: object,
) -> _Binding:
    widget: QWidget|None = None
    match value_type:
        case builtins.bool:
            widget = QCheckBox()
            widget.setChecked(bool(initial))
            return _Binding(widget,
                lambda: widget.isChecked(), 
                lambda value: widget.setChecked(value), 
                widget.checkStateChanged
            )
        
        case builtins.str:
            widget = QLineEdit()
            widget.setText(str(initial))
            return _Binding(widget,
                lambda: widget.text(),
                lambda value: widget.setText(value),
                widget.textChanged
            )
        
        case builtins.float:
            widget = QDoubleSpinBox()
            widget.setValue(float(initial))
            return _Binding(widget,
                lambda: widget.value(),
                lambda value: widget.setValue(value),
                widget.valueChanged
            )

        case builtins.int:
            widget = QSpinBox()
            widget.setValue(int(initial))
            return _Binding(widget,
                lambda: widget.value(),
                lambda value: widget.setValue(value),
                widget.valueChanged
            )

        case pathlib.Path:
            widget = QPathEdit()
            widget.setPath(str(initial))
            return _Binding(widget,
                lambda: pathlib.Path(widget.path()),
                lambda value: widget.setPath(str(value)),
                widget.pathChanged
            )

        case enum_type if isinstance(enum_type, type) and issubclass(enum_type, Enum):
            widget = QComboBox()
            for member in enum_type:
                widget.addItem(member.name, member)
            widget.setCurrentIndex(max(widget.findData(initial), 0))
            return _Binding(widget,
                lambda: widget.currentData(),
                lambda value: widget.setCurrentIndex(max(widget.findData(value), 0)),
                widget.currentIndexChanged
            )

        case _:
            raise TypeError(
                f"Unsupported type for {name!r}: {value_type!r}"
            )


def _form_from_function(
    function: Callable[..., object],
    initial: Mapping[str, object] | None = None,
    parent: QWidget | None = None,
    *,
    submit_behaviour: FormWidget.SubmitBehaviour = FormWidget.SubmitBehaviour.SUBMIT,
) -> FormWidget:
    """Build a form for keyword-callable bool, int, float, and str editors."""
    function_signature = inspect.signature(function)
    hints = get_type_hints(function)
    provided = dict(initial) if initial is not None else {}
    unknown = provided.keys() - function_signature.parameters.keys()
    if unknown:
        raise ValueError(f"Unknown parameters: {sorted(unknown)}")

    specs: list[tuple[str, type, object]] = []
    for parameter in function_signature.parameters.values():
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            raise TypeError(
                f"Unsupported parameter kind for {parameter.name!r}: "
                f"{parameter.kind.description}"
            )

        value_type = hints.get(parameter.name, inspect.Parameter.empty)
        if value_type is inspect.Parameter.empty:
            if parameter.default is inspect.Parameter.empty:
                raise TypeError(
                    f"Parameter {parameter.name!r} needs a type annotation "
                    "or a default value"
                )
            value_type = type(parameter.default)

        is_enum = isinstance(value_type, type) and issubclass(value_type, Enum)
        if not is_enum and value_type not in (bool, int, float, str, pathlib.Path):
            raise TypeError(
                f"Unsupported type for {parameter.name!r}: {value_type!r}"
            )

        value = provided.get(parameter.name, parameter.default)
        if value is inspect.Parameter.empty:
            value = next(iter(value_type)) if is_enum else value_type()
        if type(value) is not value_type:
            warnings.warn(
                f"{parameter.name!r} expects {value_type.__name__}, "
                f"got {type(value).__name__}"
            )
            # todo: review type checking. subclasses not pass
            # raise TypeError(
                #     f"{parameter.name!r} expects {value_type.__name__}, "
                #     f"got {type(value).__name__}"
            # )
        specs.append((parameter.name, value_type, value))

    form = FormWidget(parent, submit_behaviour=submit_behaviour)
    for index, (name, value_type, value) in enumerate(specs):
        editor = _create_function_editor(name, value_type, value)
        form.insertEditor(
            index, 
            name, 
            editor.widget, 
            getter=editor.getter, 
            setter=editor.setter,
            signal=editor.signal
        )
    return form


class Interactive(QFrame):
    """usage:
        interactive = Interactive(some_function)
        interactive.set_execution_behaviour(Interactive.ExecutionBehaviour.SUBMIT)
        interactive.show()
        interactive.executed.connect(lambda val: print(val))
    """
    executed = Signal(object)
    ExecutionBehaviour = FormWidget.SubmitBehaviour

    def __init__(
        self,
        func: Callable[..., object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        
        self._func = func
        self.header = QLabel(f"{func.__name__}".replace("_", " ").title())
        # center label
        self.header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.inputs = _form_from_function(func, parent=self)

        self._output = DisplayWidget()

        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(self.inputs)
        layout.addWidget(self._output)
        self.inputs.submitted.connect(self._execute)

    def set_execution_behaviour(self, behaviour: ExecutionBehaviour) -> None:
        self.inputs.set_submit_behaviour(behaviour)

    @Slot(object)
    def _execute(self, values: dict[str, object]) -> None:
        results = self._func(**values)
        self.executed.emit(results)
        self._output.display(results)


if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication

    app = QApplication([])

    def hello_world(name:str, greeting: str = "Hello")->str:
        return f"{greeting}, {name}!"

    def capitalize(text: str) -> str:
        return text.upper()

    interactive_hello_world = Interactive(hello_world)
    interactive_hello_world.set_execution_behaviour(Interactive.ExecutionBehaviour.SUBMIT)
    interactive_capitalize = Interactive(capitalize)
    interactive_capitalize.set_execution_behaviour(Interactive.ExecutionBehaviour.AUTO)

    interactive_hello_world.executed.connect(lambda result: interactive_capitalize.inputs.set_value("text", result))

    window = QWidget()
    window.setWindowTitle("Interactive Function")
    layout = QVBoxLayout(window)
    layout.addWidget(interactive_hello_world)
    layout.addWidget(interactive_capitalize)
    layout.addStretch()
    window.show()
    app.exec()
