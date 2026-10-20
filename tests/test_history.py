import pytest

from conftest import entry
from app_entries import desktop_entries as de
from app_entries import history, trash
from app_entries import overrides as ov


def only(xdg):
    (app,) = de.scan(xdg.env)
    return app


def test_record_and_undo_survive_a_restart(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    change = ov.set_hidden(only(xdg), True, xdg.env)
    e = history.record("Hid Thing", [change], env=xdg.env)
    # A fresh load (as after restarting the app) sees it.
    (loaded,) = history.load(xdg.env)
    assert loaded.id == e.id and loaded.message == "Hid Thing" and loaded.can_undo
    history.undo(e.id, xdg.env)
    assert not only(xdg).hidden
    (loaded,) = history.load(xdg.env)
    assert loaded.undone and not loaded.can_undo
    with pytest.raises(history.UndoError):
        history.undo(e.id, xdg.env)


def test_older_changes_wait_for_later_ones_on_the_same_file(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    first = history.record("Hid", [ov.set_hidden(only(xdg), True, xdg.env)], env=xdg.env)
    second = history.record("Showed", [ov.set_hidden(only(xdg), False, xdg.env)], env=xdg.env)
    with pytest.raises(history.UndoError):
        history.undo(first.id, xdg.env)   # the file was changed again since
    assert not only(xdg).hidden           # and nothing was touched
    history.undo(second.id, xdg.env)
    history.undo(first.id, xdg.env)
    assert not only(xdg).hidden and not (xdg.user / "app.desktop").exists()


def test_trashed_files_and_binary_files_come_back(xdg):
    image = xdg.tmp / "Tool.AppImage"
    image.write_bytes(b"\x7fELF")
    icon = xdg.tmp / "icon.png"
    icon.write_bytes(b"\x89PNG\x00\xff")
    changes = [ov.Change("t", "Tool", str(icon), icon.read_bytes(), None, False)]
    ov.apply_all(changes)
    e = history.record("Removed Tool", changes, [trash.move(str(image), xdg.env)], env=xdg.env)
    assert not image.exists() and not icon.exists()
    history.undo(e.id, xdg.env)
    assert image.read_bytes() == b"\x7fELF" and icon.read_bytes() == b"\x89PNG\x00\xff"


def test_history_is_trimmed_and_can_be_cleared(xdg, monkeypatch):
    monkeypatch.setattr(history, "KEEP", 3)
    for i in range(5):
        history.record("change %d" % i, [ov.Change("a", "A", str(xdg.tmp / ("f%d" % i)), None, "x", False)],
                       env=xdg.env)
    assert [e.message for e in history.load(xdg.env)] == ["change 4", "change 3", "change 2"]
    history.clear(xdg.env)
    assert history.load(xdg.env) == []
    assert history.record("nothing", [], env=xdg.env) is None
