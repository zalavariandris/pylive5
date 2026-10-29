from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from typing import cast

import jedi
from qtpy.QtCore import QTimer, QStringListModel, Slot
from qtpy.QtGui import QTextCursor
from qtpy.QtWidgets import QApplication, QPlainTextEdit

from .jedi_completer import JediCompleter

logger = logging.getLogger(__name__)
_executor: ThreadPoolExecutor | None = None


def completion_executor() -> ThreadPoolExecutor:
    global _executor

    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="jedi",
        )
        app = QApplication.instance()
        assert app is not None
        app.aboutToQuit.connect(
            partial(_executor.shutdown, wait=False, cancel_futures=True)
        )

    return _executor


def analyze(
    source: str,
    line: int,
    column: int,
    path: str | None,
) -> tuple[list[str], str]:
    """Run entirely on the worker; return only ordinary Python data."""
    script = jedi.Script(code=source, path=path)
    names = [item.name for item in script.complete(line, column)]
    signatures = script.get_signatures(line, column)
    hint = signatures[0].to_string() if signatures else ""
    return names, hint


class AsyncJediCompleter(JediCompleter):
    def __init__(
        self,
        textedit: QPlainTextEdit,
        *,
        path: str | None = None,
    ) -> None:
        super().__init__(textedit)

        # The inherited popup timer must die with the completer.
        self.timer.setParent(self)

        self.path = path
        self._executor = completion_executor()
        self._future: Future[tuple[list[str], str]] | None = None
        self._generation = 0
        self._submitted_generation = 0
        self._ready = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._request_ready)

        self._poll = QTimer(self)
        self._poll.setInterval(20)
        self._poll.timeout.connect(self._collect_result)

        # The base class already connects textChanged.
        textedit.cursorPositionChanged.connect(self.requestCompletions)

    @Slot()
    def requestCompletions(self) -> None:
        self._generation += 1
        self._ready = False
        self.timer.stop()
        self.popup().hide()
        self.hint_label.hide()

        if self._future is not None:
            # Cancels queued work. Running work finishes normally.
            self._future.cancel()

        self._debounce.start()

    @Slot()
    def _request_ready(self) -> None:
        self._ready = True
        self._submit_latest()

    def _submit_latest(self) -> None:
        if not self._ready or self._future is not None:
            return

        self._ready = False
        editor = cast(QPlainTextEdit, self.widget())
        cursor = editor.textCursor()

        before = QTextCursor(cursor)
        before.movePosition(
            QTextCursor.MoveOperation.StartOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        line_prefix = before.selectedText()
        if not line_prefix.strip():
            return

        # Qt uses UTF-16 positions; Jedi expects Python character counts.
        column = len(line_prefix)

        self._submitted_generation = self._generation
        self._future = self._executor.submit(
            analyze,
            editor.toPlainText(),
            cursor.blockNumber() + 1,
            column,
            self.path,
        )
        self._poll.start()

    @Slot()
    def _collect_result(self) -> None:
        future = self._future
        if future is None or not future.done():
            return

        self._future = None
        self._poll.stop()

        if not future.cancelled():
            try:
                # Already finished, so this cannot wait for analysis.
                names, hint = future.result()
            except Exception:
                logger.exception("Jedi completion failed")
            else:
                if self._submitted_generation == self._generation:
                    self.setCompletionPrefix(self.getWordUntilCursor())
                    model = cast(QStringListModel, self.model())
                    model.setStringList(names)

                    self.hint_label.setText(hint)
                    self.hint_label.setVisible(bool(hint))
                    if hint:
                        editor = cast(QPlainTextEdit, self.widget())
                        self.hint_label.move(
                            editor.viewport().mapTo(
                                editor,
                                editor.cursorRect().topLeft(),
                            )
                        )
                        self.hint_label.adjustSize()

        # If typing continued during analysis, process the latest text.
        self._submit_latest()

    def insertCompletion(self, completion: str) -> None:
        editor = cast(QPlainTextEdit, self.widget())
        cursor = editor.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.insertText(completion)
        editor.setTextCursor(cursor)