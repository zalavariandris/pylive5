import pytest
from qtpy.QtCore import QCoreApplication, QEvent, QThread
from qtpy.QtTest import QTest

from pygraphrt.graph_rt import GraphRT
from pygraphrt.import_module_rt import ImportModuleRT
from pygraphrt.watch import watch


def source(value):
    return f"def value():\n    return {value}\n"


@pytest.fixture
def module(tmp_path, qt_app):
    path = tmp_path / "operators.py"
    path.write_text(source(1), encoding="utf-8")
    runtime = ImportModuleRT("tools", path)
    destroyed = []
    runtime.destroyed.connect(lambda: destroyed.append(True))
    yield runtime
    if not destroyed:
        runtime.file_binding.close()
        runtime.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_file_edits_refresh_graph_results_on_the_module_thread(module, wait_until):
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
        module.file_binding.path().write_text(source(2), encoding="utf-8")
        wait_until(lambda: results == [2])
        assert module.get_operator("value") is operator
        assert threads == [module.thread()]
    finally:
        watcher.stop()


@pytest.mark.parametrize("bad_source, error_type", [
    ("def value(:\n", SyntaxError),
    ("def value():\n    return 99\nraise RuntimeError('failed')\n", RuntimeError),
])
def test_invalid_edits_report_errors_and_recover_on_the_next_save(
    module, wait_until, bad_source, error_type
):
    operator = module.get_operator("value")
    fingerprint = operator.fingerprint()
    failures = []
    changes = []
    module.script_failed.connect(failures.append)
    module.operators_changed.connect(changes.append)

    module.file_binding.path().write_text(bad_source, encoding="utf-8")
    wait_until(lambda: failures)
    assert isinstance(failures[0], error_type)
    assert module.file_binding.get_text() == bad_source
    assert module.get_script() == source(1)
    assert operator() == 1
    assert operator.fingerprint() == fingerprint
    assert changes == []

    module.file_binding.path().write_text(source(2), encoding="utf-8")
    wait_until(lambda: operator() == 2)
    assert changes == [["value"]]


def test_opening_invalid_source_reports_errors_and_recovers(module, tmp_path, wait_until):
    broken = tmp_path / "broken.py"
    broken.write_text("def value(:\n", encoding="utf-8")
    failures = []
    module.script_failed.connect(failures.append)

    module.file_binding.open(broken)

    assert isinstance(failures[0], SyntaxError)
    assert module.file_binding.path() == broken
    assert module.file_binding.get_text() == "def value(:\n"
    assert module.get_operator("value")() == 1
    broken.write_text(source(2), encoding="utf-8")
    wait_until(lambda: module.get_operator("value")() == 2)


def test_saving_accepted_source_does_not_emit_duplicate_changes(module):
    changes = []
    module.operators_changed.connect(changes.append)
    module.set_script(source(2))
    module.file_binding.save()
    QTest.qWait(250)
    assert changes == [["value"]]
    assert module.get_operator("value")() == 2


def test_destroying_module_also_destroys_binding_and_wrapped_runtime(module):
    destroyed = []
    changes = []
    module.file_binding.destroyed.connect(lambda: destroyed.append("binding"))
    module.script_module.destroyed.connect(lambda: destroyed.append("script"))
    module.script_changed.connect(lambda: changes.append(True))
    path = module.file_binding.path()
    path.write_text(source(2), encoding="utf-8")
    QCoreApplication.processEvents()

    module.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert set(destroyed) == {"binding", "script"}
    path.write_text(source(3), encoding="utf-8")
    QTest.qWait(250)
    assert changes == []


def test_external_conflict_keeps_the_local_script_and_operators(module, wait_until):
    module.set_script(source(2))
    operator = module.get_operator("value")
    fingerprint = operator.fingerprint()
    conflicts = []
    changes = []
    module.file_binding.conflict_detected.connect(
        lambda *versions: conflicts.append(versions)
    )
    module.operators_changed.connect(changes.append)

    module.file_binding.path().write_text(source(3), encoding="utf-8")
    wait_until(lambda: conflicts)

    assert conflicts == [(source(1), source(2), source(3))]
    assert module.file_binding.get_text() == source(2)
    assert module.get_script() == source(2)
    assert operator() == 2
    assert operator.fingerprint() == fingerprint
    assert changes == []

    assert module.file_binding.reload(force=True) is True
    assert module.get_script() == source(3)
    assert operator() == 3
    assert changes == [["value"]]
