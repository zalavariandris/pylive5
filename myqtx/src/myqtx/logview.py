from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
)
import logging
import sys


from fxgui.fxwidgets import FXOutputLogWidget, FXOutputLogHandler

import threading
from typing import Callable, TextIO



class _TeeStream:
    def __init__(self, original: TextIO | None, send_message: Callable[[str], None]) -> None:
        self._original = original            # None under pythonw
        self._send_message = send_message
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        if self._original is not None:
            self._original.write(text)
        with self._lock:
            self._buffer += text
            *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            self._send_message(line)
        return len(text)

    def flush(self) -> None:
        if self._original is not None:
            self._original.flush()
        with self._lock:
            tail, self._buffer = self._buffer, ""
        if tail:
            self._send_message(tail)

    def isatty(self) -> bool:
        return self._original is not None and self._original.isatty()

class LogView(QWidget):
    def __init__(self, logger: logging.Logger|None=None):
        super().__init__()
        self.log_widget:FXOutputLogWidget = FXOutputLogWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)
        main_layout.addWidget(self.log_widget)
        self._logger: logging.Logger|None = None
        self.__original_stdout, self.__original_stderr = sys.stdout, sys.stderr
        self.setLogger(logger)

    def setLogger(self, logger: logging.Logger|None=None) -> None:
        # if no logger, use the TeeStream to redirect output to the widget
        if self._logger is None:
            # restore the original stdout and stderr if no logger is set
            sys.stdout, sys.stderr = self.__original_stdout, self.__original_stderr
        if self._logger is not None:
            self._logger.removeHandler(FXOutputLogHandler(self.log_widget))

        if logger is None:
            self.__original_stdout, self.__original_stderr = sys.stdout, sys.stderr
            sys.stdout = _TeeStream(
                self.__original_stdout,
                lambda text: self.log_widget.log_message.emit(text, logging.INFO),
            )
            sys.stderr = _TeeStream(
                self.__original_stderr,
                lambda text: self.log_widget.log_message.emit(text, logging.ERROR),
            )
        else:
            self._logger = logger
            self._logger.addHandler(FXOutputLogHandler(self.log_widget))