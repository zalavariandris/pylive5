from time import monotonic

import pytest
from qtpy.QtCore import QCoreApplication, QEvent, QThread
from qtpy.QtTest import QTest

from myqtx import FileBinding


def replace_when_available(source_path, target_path, timeout_ms=3000):
    """Retry transient Windows access/sharing errors while replacing a test file."""
    deadline = monotonic() + timeout_ms / 1000
    while True:
        try:
            source_path.replace(target_path)
            return
        except PermissionError as error:
            # Windows can briefly deny a rename while another handle is open.
            if getattr(error, "winerror", None) not in (5, 32, 33):
                raise
            if monotonic() >= deadline:
                raise
            QTest.qWait(10)


@pytest.fixture
def binding(tmp_path, qt_app):
    path = tmp_path / "notes.txt"
    path.write_text("first note", encoding="utf-8")
    buffer = FileBinding(path)
    destroyed = []
    buffer.destroyed.connect(lambda: destroyed.append(True))
    yield buffer
    if not destroyed:
        buffer.close()
        buffer.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_standalone_buffer_watches_a_non_python_file(binding, wait_until):
    changes = []
    threads = []
    binding.changed.connect(lambda: changes.append(binding.get_text()))
    binding.changed.connect(lambda: threads.append(QThread.currentThread()))

    binding.path().write_text("second note", encoding="utf-8")
    wait_until(lambda: changes)

    assert changes == ["second note"]
    assert binding.get_text() == "second note"
    assert threads == [binding.thread()]


def test_atomic_replacement_and_later_writes_are_detected(binding, wait_until):
    for text in ("second note", "third note"):
        replacement = binding.path().with_name("replacement.txt")
        replacement.write_text(text, encoding="utf-8")
        replace_when_available(replacement, binding.path())
        wait_until(lambda: binding.get_text() == text)
        assert binding.path().as_posix() in binding._file_watcher.files()

    binding.path().write_text("fourth note", encoding="utf-8")
    wait_until(lambda: binding.get_text() == "fourth note")


def test_deleted_file_keeps_buffer_and_recreation_resumes_watching(binding, wait_until):
    failures = []
    binding.reload_failed.connect(failures.append)
    binding.path().unlink()
    wait_until(lambda: failures)
    assert isinstance(failures[0], FileNotFoundError)
    assert binding.get_text() == "first note"

    binding.path().write_text("second note", encoding="utf-8")
    wait_until(lambda: binding.get_text() == "second note")
    binding.path().write_text("third note", encoding="utf-8")
    wait_until(lambda: binding.get_text() == "third note")


def test_open_switches_watches_and_ignores_pending_events_for_the_old_file(
    binding, tmp_path, wait_until
):
    previous_path = binding.path()
    previous_path.write_text("pending edit", encoding="utf-8")
    QCoreApplication.processEvents()

    folder = tmp_path / "other"
    folder.mkdir()
    next_path = folder / "notes.txt"
    next_path.write_text("second note", encoding="utf-8")
    binding.open(next_path)
    assert binding._file_watcher.files() == [next_path.as_posix()]
    assert binding._file_watcher.directories() == [folder.as_posix()]
    previous_path.write_text("ignored edit", encoding="utf-8")
    QTest.qWait(250)
    assert binding.get_text() == "second note"

    next_path.write_text("third note", encoding="utf-8")
    wait_until(lambda: binding.get_text() == "third note")


def test_unrelated_directory_changes_preserve_unsaved_memory_edits(binding):
    binding.set_text("unsaved edit")
    changes = []
    binding.changed.connect(lambda: changes.append(binding.get_text()))

    unrelated = binding.path().with_name("unrelated.txt")
    unrelated.write_text("other content", encoding="utf-8")
    QTest.qWait(250)

    assert binding.get_text() == "unsaved edit"
    assert changes == []
    assert binding.path().read_text(encoding="utf-8") == "first note"


def test_saving_buffer_does_not_emit_duplicate_changes(binding):
    changes = []
    binding.changed.connect(lambda: changes.append(binding.get_text()))
    binding.set_text("second note")
    binding.save()
    QTest.qWait(250)

    assert changes == ["second note"]
    assert binding.path().read_text(encoding="utf-8") == "second note"


def test_bursts_of_file_events_are_debounced(binding, wait_until):
    binding._reload_timer.setInterval(200)
    changes = []
    binding.changed.connect(lambda: changes.append(binding.get_text()))
    for text in ("second note", "third note", "fourth note"):
        binding.path().write_text(text, encoding="utf-8")
        QTest.qWait(20)
    wait_until(lambda: changes)

    assert changes == ["fourth note"]


def test_close_cancels_pending_reload_and_watching_can_restart(binding, wait_until):
    binding.path().write_text("second note", encoding="utf-8")
    QCoreApplication.processEvents()
    binding.close()
    binding.close()
    assert binding._file_watcher.files() == []
    assert binding._file_watcher.directories() == []
    QTest.qWait(250)
    assert binding.get_text() == "first note"

    binding.path().write_text("third note", encoding="utf-8")
    binding.start_watching()
    binding.start_watching()
    wait_until(lambda: binding.get_text() == "third note")


def test_destroying_binding_also_destroys_watcher_and_pending_timer(binding):
    destroyed = []
    changes = []
    binding._file_watcher.destroyed.connect(lambda: destroyed.append("watcher"))
    binding._reload_timer.destroyed.connect(lambda: destroyed.append("timer"))
    binding.changed.connect(lambda: changes.append(True))
    path = binding.path()
    path.write_text("second note", encoding="utf-8")
    QCoreApplication.processEvents()

    binding.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert set(destroyed) == {"watcher", "timer"}
    path.write_text("third note", encoding="utf-8")
    QTest.qWait(250)
    assert changes == []


def test_conflicting_file_edits_keep_local_text_and_report_each_new_disk_version(
    binding, wait_until
):
    binding.set_text("local edit")
    changes = []
    conflicts = []
    binding.changed.connect(lambda: changes.append(binding.get_text()))
    binding.conflict_detected.connect(lambda *versions: conflicts.append(versions))

    binding.path().write_text("external edit", encoding="utf-8")
    wait_until(lambda: conflicts)
    assert conflicts == [("first note", "local edit", "external edit")]
    assert binding.get_text() == "local edit"
    assert binding.is_modified()
    assert changes == []

    # Repeated directory notifications must not repeat the same conflict.
    unrelated = binding.path().with_name("unrelated.txt")
    unrelated.write_text("other contents", encoding="utf-8")
    QTest.qWait(250)
    assert len(conflicts) == 1

    binding.path().write_text("another external edit", encoding="utf-8")
    wait_until(lambda: len(conflicts) == 2)
    assert conflicts[-1] == ("first note", "local edit", "another external edit")
    assert binding.get_text() == "local edit"
    assert changes == []


def test_matching_external_edit_marks_local_text_clean_without_duplicate_changes(
    binding, wait_until
):
    binding.set_text("matching edit")
    changes = []
    conflicts = []
    binding.changed.connect(lambda: changes.append(binding.get_text()))
    binding.conflict_detected.connect(lambda *versions: conflicts.append(versions))

    binding.path().write_text("matching edit", encoding="utf-8")
    wait_until(lambda: not binding.is_modified())
    assert changes == []
    assert conflicts == []

    binding.path().write_text("next external edit", encoding="utf-8")
    wait_until(lambda: binding.get_text() == "next external edit")
    assert changes == ["next external edit"]
    assert not binding.is_modified()


def test_restarting_watch_preserves_local_edits_when_disk_changed_while_stopped(
    binding, wait_until
):
    binding.stop_watching()
    binding.set_text("local edit")
    conflicts = []
    binding.conflict_detected.connect(lambda *versions: conflicts.append(versions))
    binding.path().write_text("external edit", encoding="utf-8")

    binding.start_watching()
    wait_until(lambda: conflicts)

    assert conflicts == [("first note", "local edit", "external edit")]
    assert binding.get_text() == "local edit"
    assert binding.is_modified()
