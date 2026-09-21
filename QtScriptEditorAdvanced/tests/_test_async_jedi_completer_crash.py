"""Check that async_jedi_completer does not crash under overlapping completions.

Rapid typing starts a new JediWorkerTask on QThreadPool without stopping the
previous one. Jedi is not thread-safe, and JediWorkerTask(QObject, QRunnable)
is auto-deleted from the worker thread — that combination access-violates.

A native AV cannot be caught in-process (it kills pytest), so each case is
run in a subprocess. A crash or hang fails the test instead of the session.
"""

from __future__ import annotations

import os
import subprocess
import sys

import QtScriptEditorAdvanced.components.async_jedi_completer as ajc
import pytest


SOURCE = (
    "class Dog:\n"
    "    def bark(self):\n"
    "        return 1\n"
    "mydog = Dog()\n"
    "mydog.\n"
)


def _run_in_subprocess(case: str, timeout: float = 20) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    try:
        result = subprocess.run(
            [sys.executable, __file__, case],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=os.getcwd(),
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"case {case!r} hung (thread-pool deadlock)\n"
            f"stdout:\n{exc.stdout}\nstderr:\n{exc.stderr}"
        )

    if result.returncode != 0:
        pytest.fail(
            f"case {case!r} crashed (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def test_overlapping_jedi_worker_tasks_do_not_crash():
    _run_in_subprocess("overlapping")


def test_worker_cpp_object_survives_after_run():
    _run_in_subprocess("cpp_lifetime")


def test_rapid_request_completions_does_not_crash():
    _run_in_subprocess("rapid_request")


def _qapp():
    from qtpy.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _case_overlapping() -> None:
    from qtpy.QtCore import QThreadPool

    app = _qapp()
    pool = QThreadPool.globalInstance()
    finished = []
    errors = []
    tasks = []

    def on_finished(completions):
        finished.append([c.name for c in completions])

    def on_error(exc):
        errors.append(exc)

    for i in range(20):
        task = ajc.JediWorkerTask(SOURCE, 5, 6)
        task.finished.connect(on_finished)
        task.exceptionThrown.connect(on_error)
        tasks.append(task)
        pool.start(task)
        if i % 4 == 0:
            # same as AsyncJediCompleter.cancellAllTasks — drop python refs
            # while the pool still owns the runnables
            tasks.clear()

    assert pool.waitForDone(15_000), "thread pool deadlocked on overlapping jedi.complete()"
    app.processEvents()
    assert not errors, f"jedi worker exceptions: {errors[:5]!r}"
    assert finished, "no completions delivered"
    assert any("bark" in names for names in finished)
    print("OK overlapping", flush=True)


def _case_cpp_lifetime() -> None:
    from qtpy.QtCore import QThreadPool

    app = _qapp()
    pool = QThreadPool.globalInstance()
    task = ajc.JediWorkerTask(SOURCE, 5, 6)
    pool.start(task)
    assert pool.waitForDone(15_000)
    app.processEvents()
    # RuntimeError: Internal C++ object already deleted
    assert task.autoDelete() in (True, False)
    print("OK cpp_lifetime", flush=True)


def _case_rapid_request() -> None:
    from qtpy.QtGui import QTextCursor
    from qtpy.QtWidgets import QPlainTextEdit

    app = _qapp()
    editor = QPlainTextEdit()
    editor.setPlainText(SOURCE)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    completer = ajc.AsyncJediCompleter(editor)
    for _ in range(20):
        completer.requestCompletions()

    assert completer._thread_pool.waitForDone(15_000), (
        "AsyncJediCompleter deadlocked — cancellAllTasks does not stop in-flight jedi work"
    )
    app.processEvents()
    print("OK rapid_request", flush=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])