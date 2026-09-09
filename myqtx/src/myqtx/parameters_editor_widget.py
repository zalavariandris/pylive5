class Binding(NamedTuple):
    editor: QWidget
    getter: Callable[[QWidget], Any]
    setter: Callable[[QWidget, Any], None]
    signal: Signal


class ParameterEditor(QWidget):
    value_changed = Signal(str, Any)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout()
        self.setLayout(self._layout)
        self._editors: dict[str, QWidget] = {}
        self._getters: dict[str, Callable[[QWidget], Any]] = {}
        self._setters: dict[str, Callable[[QWidget, Any], None]] = {}
        self._connections: dict[str, tuple[Signal, Any]] = {}  # key -> (signal, slot)

    def insert_editor(self, key:str, editor:QWidget, 
        getter:Callable[[QWidget], Any], 
        setter:Callable[[QWidget, Any], None], 
        signal:Signal
    ):
        self._layout.addWidget(editor)
        self._editors[key] = editor
        self._getters[key] = getter
        self._setters[key] = setter
        slot = lambda value, k=key: self.value_changed.emit(k, self._getters[k](self._editors[k]))
        signal.connect(slot)
        self._connections[key] = (signal, slot)

    def remove_editor(self, key:str):
        if editor:= self._editors.pop(key, None):
            self._setters.pop(key, None)
            self._getters.pop(key, None)
            signal, slot = self._connections.pop(key)
            signal.disconnect(slot)
            self._layout.removeWidget(editor)
            editor.deleteLater()

    def value(self, key:str) -> Any:
        if editor := self._editors.get(key):
            return editor.text() if isinstance(editor, QLineEdit) else None
        return None

    def set_value(self, key:str, value:Any):
        if editor := self._editors.get(key):
            self._setters[key](editor, value)