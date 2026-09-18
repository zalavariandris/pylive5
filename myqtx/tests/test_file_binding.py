from pathlib import Path

import pytest

import myqtx


def test_buffer_reads_edits_saves_and_reloads_arbitrary_utf8(tmp_path):
    path = tmp_path / "notes.txt"
    original = "Notes: \u00e1rv\u00edz\nThis is not Python.\n"
    path.write_text(original, encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    changes = []
    buffer.changed.connect(lambda: changes.append(buffer.get_text()))

    assert buffer.path() == path
    assert buffer.get_text() == original
    buffer.set_text("an unsaved edit")
    assert path.read_text(encoding="utf-8") == original
    buffer.save()
    assert path.read_text(encoding="utf-8") == "an unsaved edit"
    buffer.reload()
    assert changes == ["an unsaved edit"]

    path.write_text("external edit", encoding="utf-8")
    buffer.reload()
    assert buffer.get_text() == "external edit"
    assert changes == ["an unsaved edit", "external edit"]


def test_open_notifies_after_path_and_text_are_committed(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("same text", encoding="utf-8")
    second.write_text("same text", encoding="utf-8")
    buffer = myqtx.FileBinding(first, watch=False)
    changes = []
    buffer.changed.connect(lambda: changes.append((buffer.path(), buffer.get_text())))

    buffer.open(str(second))
    buffer.open(second)
    buffer.set_text("same text")

    assert changes == [(second, "same text")]


@pytest.mark.parametrize("failure", ["missing", "invalid_utf8"])
def test_failed_read_preserves_the_buffer_and_path(tmp_path, failure):
    path = tmp_path / "notes.txt"
    path.write_text("accepted", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text("unsaved")
    other = tmp_path / "other.txt"
    error = FileNotFoundError
    if failure == "invalid_utf8":
        other.write_bytes(b"\xff")
        error = UnicodeDecodeError
    changes = []
    buffer.changed.connect(lambda: changes.append(True))

    with pytest.raises(error):
        buffer.open(other)

    assert buffer.path() == path
    assert buffer.get_text() == "unsaved"
    assert changes == []


def test_failed_save_preserves_memory_and_last_disk_contents(tmp_path, monkeypatch):
    path = tmp_path / "notes.txt"
    path.write_text("original", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text("unsaved")

    def fail_write(*args, **kwargs):
        raise OSError("write failed")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", fail_write)
        with pytest.raises(OSError, match="write failed"):
            buffer.save()

    assert buffer.get_text() == "unsaved"
    assert path.read_text(encoding="utf-8") == "original"
    buffer.save()
    assert path.read_text(encoding="utf-8") == "unsaved"


@pytest.mark.parametrize(
    "local, incoming, expected, modified, accepted",
    [
        ("base", "base", "base", False, True),
        ("local", "base", "local", True, True),
        ("base", "external", "external", False, True),
        ("local", "local", "local", False, True),
        ("local", "external", "local", True, False),
    ],
    ids=["unchanged", "local-only", "disk-only", "matching-edits", "conflict"],
)
def test_reload_compares_local_and_disk_against_the_baseline(
    tmp_path, local, incoming, expected, modified, accepted
):
    path = tmp_path / "notes.txt"
    path.write_text("base", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text(local)
    changes = []
    conflicts = []
    buffer.changed.connect(lambda: changes.append(buffer.get_text()))
    buffer.conflict_detected.connect(lambda *versions: conflicts.append(versions))
    path.write_text(incoming, encoding="utf-8")

    assert buffer.reload() is accepted

    assert buffer.get_text() == expected
    assert buffer.is_modified() is modified
    assert path.read_text(encoding="utf-8") == incoming
    assert changes == ([expected] if expected != local else [])
    assert conflicts == ([] if accepted else [("base", local, incoming)])


def test_further_conflicts_keep_the_original_baseline(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("base", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text("local")
    conflicts = []
    buffer.conflict_detected.connect(lambda *versions: conflicts.append(versions))

    path.write_text("external one", encoding="utf-8")
    assert buffer.reload() is False
    buffer.set_text("edited local")
    path.write_text("external two", encoding="utf-8")
    assert buffer.reload() is False

    assert conflicts == [
        ("base", "local", "external one"),
        ("base", "edited local", "external two"),
    ]
    assert buffer.get_text() == "edited local"
    assert buffer.is_modified()


@pytest.mark.parametrize("resolution, resolved_text", [
    ("reload", "external"),
    ("save", "local"),
])
def test_explicit_conflict_resolution_establishes_a_new_baseline(
    tmp_path, resolution, resolved_text
):
    path = tmp_path / "notes.txt"
    path.write_text("base", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text("local")
    path.write_text("external", encoding="utf-8")
    assert buffer.reload() is False

    assert getattr(buffer, resolution)(force=True) is True

    assert buffer.get_text() == resolved_text
    assert path.read_text(encoding="utf-8") == resolved_text
    assert not buffer.is_modified()

    conflicts = []
    buffer.conflict_detected.connect(lambda *versions: conflicts.append(versions))
    buffer.set_text("next local")
    path.write_text("next external", encoding="utf-8")
    assert buffer.reload() is False
    assert conflicts == [(resolved_text, "next local", "next external")]


def test_save_checks_for_unseen_disk_conflicts_before_writing(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("base", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text("local")
    conflicts = []
    buffer.conflict_detected.connect(lambda *versions: conflicts.append(versions))
    path.write_text("external", encoding="utf-8")

    assert buffer.save() is False

    assert conflicts == [("base", "local", "external")]
    assert buffer.get_text() == "local"
    assert buffer.is_modified()
    assert path.read_text(encoding="utf-8") == "external"


def test_saving_a_clean_buffer_accepts_newer_disk_contents(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("base", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    path.write_text("external", encoding="utf-8")

    assert buffer.save() is True

    assert buffer.get_text() == "external"
    assert path.read_text(encoding="utf-8") == "external"
    assert not buffer.is_modified()


def test_editing_local_text_to_match_incoming_resolves_the_conflict(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("base", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text("local")
    path.write_text("external", encoding="utf-8")
    assert buffer.reload() is False

    buffer.set_text("external")

    assert not buffer.is_modified()
    path.write_text("next external", encoding="utf-8")
    assert buffer.reload() is True
    assert buffer.get_text() == "next external"


def test_reloading_with_force_discards_local_edits_when_disk_is_unchanged(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("base", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text("local")

    assert buffer.reload(force=True) is True

    assert buffer.get_text() == "base"
    assert not buffer.is_modified()


def test_opening_the_current_path_cannot_silently_discard_a_conflict(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("base", encoding="utf-8")
    buffer = myqtx.FileBinding(path, watch=False)
    buffer.set_text("local")
    path.write_text("external", encoding="utf-8")

    assert buffer.open(path) is False
    assert buffer.get_text() == "local"
    assert buffer.open(path, force=True) is True
    assert buffer.get_text() == "external"


def test_opening_another_document_resets_the_baseline(tmp_path):
    first = tmp_path / "first.txt"
    first.write_text("first", encoding="utf-8")
    second = tmp_path / "second.txt"
    second.write_text("second", encoding="utf-8")
    buffer = myqtx.FileBinding(first, watch=False)
    buffer.set_text("local")
    first.write_text("external", encoding="utf-8")
    assert buffer.reload() is False

    assert buffer.open(second) is True
    assert not buffer.is_modified()
    second.write_text("updated second", encoding="utf-8")

    assert buffer.reload() is True
    assert buffer.get_text() == "updated second"
