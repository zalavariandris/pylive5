from time import monotonic

import pytest
from qtpy.QtCore import QCoreApplication, QEvent, QThread
from qtpy.QtTest import QTest

from pygraphrt.graph_rt import GraphRT
from pygraphrt.import_module_rt import ImportModuleRT
from pygraphrt.watch import watch


def source(value):
    return f"VALUE = {value}\ndef value():\n    return VALUE\n"


def wait_until(condition, timeout_ms=3000):
    deadline = monotonic() + timeout_ms / 1000
    while not condition() and monotonic() < deadline:
        QTest.qWait(10)
    assert condition(), "Timed out waiting for a file change to be processed"


@pytest.fixture(scope="session")
def qt_app():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def module(tmp_path, qt_app):
    path = tmp_path / "operators.py"
    path.write_text(source(1), encoding="utf-8")
    runtime = ImportModuleRT("tools", path)
    destroyed = []
    runtime.destroyed.connect(lambda: destroyed.append(True))
    yield runtime
    if not destroyed:
        runtime.close()
        runtime.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_file_edits_refresh_graph_results_on_the_module_thread(module):
    graph = GraphRT()
    graph.add_modules([module])
    operator = module.get_operator("value")
    node = graph.node()(operator)
    assert graph.execute(node) == 1
    results = []
    threads = []
    module.script_changed.connect(lambda: threads.append(QThread.currentThread()))
    watcher = watch(graph, node, lambda: results.append(graph.execute(node)))
    try:
        module.path().write_text(source(2), encoding="utf-8")
        wait_until(lambda: results == [2])
        assert module.get_operator("value") is operator
        assert threads == [module.thread()]
    finally:
        watcher.stop()


def test_atomic_replacement_and_later_writes_are_detected(module):
    operator = module.get_operator("value")
    for value in (2, 3):
        replacement = module.path().with_name("replacement.py")
        replacement.write_text(source(value), encoding="utf-8")
        replacement.replace(module.path())
        wait_until(lambda: operator() == value)
        assert module.path().as_posix() in module._file_watcher.files()

    module.path().write_text(source(4), encoding="utf-8")
    wait_until(lambda: operator() == 4)


@pytest.mark.parametrize("bad_source, error_type", [
    ("def value(:\n", SyntaxError),
    ("def value():\n    return 99\nraise RuntimeError('failed')\n", RuntimeError),
])
def test_invalid_edits_report_errors_and_recover_on_the_next_save(module, bad_source, error_type):
    operator = module.get_operator("value")
    fingerprint = operator.fingerprint()
    failures = []
    changes = []
    module.reload_failed.connect(failures.append)
    module.operators_changed.connect(changes.append)

    module.path().write_text(bad_source, encoding="utf-8")
    wait_until(lambda: failures)
    assert isinstance(failures[0], error_type)
    assert module.get_script() == source(1)
    assert operator() == 1
    assert operator.fingerprint() == fingerprint
    assert changes == []

    module.path().write_text(source(2), encoding="utf-8")
    wait_until(lambda: operator() == 2)
    assert changes == [["value"]]


def test_deleted_file_keeps_live_operators_and_recreation_resumes_watching(module):
    operator = module.get_operator("value")
    failures = []
    module.reload_failed.connect(failures.append)
    module.path().unlink()
    wait_until(lambda: failures)
    assert isinstance(failures[0], FileNotFoundError)
    assert operator() == 1

    module.path().write_text(source(2), encoding="utf-8")
    wait_until(lambda: operator() == 2)
    module.path().write_text(source(3), encoding="utf-8")
    wait_until(lambda: operator() == 3)


def test_open_switches_watches_and_ignores_pending_events_for_the_old_file(module, tmp_path):
    previous_path = module.path()
    previous_path.write_text(source(10), encoding="utf-8")
    QCoreApplication.processEvents()

    folder = tmp_path / "other"
    folder.mkdir()
    next_path = folder / "operators.py"
    next_path.write_text(source(2), encoding="utf-8")
    module.open(next_path)
    assert module._file_watcher.files() == [next_path.as_posix()]
    assert module._file_watcher.directories() == [folder.as_posix()]
    previous_path.write_text(source(99), encoding="utf-8")
    QTest.qWait(250)
    assert module.get_operator("value")() == 2

    next_path.write_text(source(3), encoding="utf-8")
    wait_until(lambda: module.get_operator("value")() == 3)


def test_failed_open_keeps_watching_the_previous_file(module, tmp_path):
    previous_path = module.path()
    broken = tmp_path / "broken.py"
    broken.write_text("def value(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        module.open(broken)
    assert module.path() == previous_path
    previous_path.write_text(source(2), encoding="utf-8")
    wait_until(lambda: module.get_operator("value")() == 2)


def test_unrelated_directory_changes_preserve_unsaved_memory_edits(module):
    module.set_script(source(9))
    operator = module.get_operator("value")
    fingerprint = operator.fingerprint()
    unrelated = module.path().with_name("unrelated.txt")
    unrelated.write_text("other content", encoding="utf-8")
    QTest.qWait(250)
    assert operator() == 9
    assert operator.fingerprint() == fingerprint
    assert module.path().read_text(encoding="utf-8") == source(1)


def test_saving_accepted_source_does_not_emit_duplicate_changes(module):
    changes = []
    module.operators_changed.connect(changes.append)
    module.set_script(source(2))
    module.save()
    QTest.qWait(250)
    assert changes == [["value"]]
    assert module.get_operator("value")() == 2


def test_bursts_of_file_events_are_debounced(module):
    module._reload_timer.setInterval(200)
    results = []
    module.script_changed.connect(lambda: results.append(module.get_operator("value")()))
    for value in (2, 3, 4):
        module.path().write_text(source(value), encoding="utf-8")
        QTest.qWait(20)
    wait_until(lambda: results)
    assert results == [4]


def test_close_cancels_pending_reload_and_watching_can_restart(module):
    operator = module.get_operator("value")
    module.path().write_text(source(2), encoding="utf-8")
    QCoreApplication.processEvents()
    module.close()
    module.close()
    assert module._file_watcher.files() == []
    assert module._file_watcher.directories() == []
    QTest.qWait(250)
    assert operator() == 1

    module.path().write_text(source(3), encoding="utf-8")
    module.start_watching()
    module.start_watching()
    wait_until(lambda: operator() == 3)


def test_destroying_module_also_destroys_watcher_and_pending_timer(module):
    destroyed = []
    changes = []
    module._file_watcher.destroyed.connect(lambda: destroyed.append("watcher"))
    module._reload_timer.destroyed.connect(lambda: destroyed.append("timer"))
    module.script_changed.connect(lambda: changes.append(True))
    path = module.path()
    path.write_text(source(2), encoding="utf-8")
    QCoreApplication.processEvents()

    module.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert set(destroyed) == {"watcher", "timer"}
    path.write_text(source(3), encoding="utf-8")
    QTest.qWait(250)
    assert changes == []
