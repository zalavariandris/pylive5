class LogWidget(QPlainTextEdit):
    message_received = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.message_received.connect(
            self.append_message,
            Qt.ConnectionType.QueuedConnection,
        )

    @Slot(str)
    def log_message(self, message: str) -> None:
        self.appendPlainText(message)

    def contextMenuEvent(self, event: QContextMenuEvent | None) -> None:
        if event is None:
            return

        menu = self.createStandardContextMenu()
        if menu is None:
            return

        menu.addSeparator()
        menu.addAction("Clear", self.clear)
        menu.exec(event.globalPos())
        menu.deleteLater()


class LogHandler(logging.Handler):
    def __init__(self, send_message: Callable[[str], None]) -> None:
        super().__init__()
        self._send_message = send_message

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._send_message(self.format(record))
        except Exception:
            self.handleError(record)
