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
        history.record(f"change {i}", [ov.Change("a", "A", str(xdg.tmp / f"f{i}"), None, "x", False)],
                       env=xdg.env)
    assert [e.message for e in history.load(xdg.env)] == ["change 4", "change 3", "change 2"]
    history.clear(xdg.env)
    assert history.load(xdg.env) == []
    assert history.record("nothing", [], env=xdg.env) is None


def test_undoing_an_update_puts_the_old_file_back_and_the_download_in_the_trash(xdg):
    home = xdg.env["HOME"]
    old, new = f"{home}/Tool-1.AppImage", f"{home}/Tool-2.AppImage"
    for p in (old, new):
        with open(p, "w") as f:
            f.write(p)
    t = trash.move(old, xdg.env)
    e = history.record("Tool updated to 2", [], [t], env=xdg.env, added=[new])
    (loaded,) = history.load(xdg.env)
    assert loaded.added == [new] and loaded.can_undo
    history.undo(e.id, xdg.env)
    import os
    assert os.path.exists(old) and not os.path.exists(new)
    assert any(n.startswith("Tool-2") for n in os.listdir(trash.folder(xdg.env) + "/files"))


def test_undoing_a_newer_file_through_a_link_swaps_the_link_back(xdg):
    """The launcher runs ~/.local/bin/tool, a link to the AppImage: the
    update points a new link at the new file; Undo puts the old link back."""
    import os
    home = xdg.env["HOME"]
    os.makedirs(home + "/.local/bin")
    old, new, link = f"{home}/Tool-1.AppImage", f"{home}/Tool-2.AppImage", f"{home}/.local/bin/tool"
    for p in (old, new):
        with open(p, "w") as f:
            f.write(p)
    os.symlink(old, link)
    trashed = [trash.move(old, xdg.env), trash.move(link, xdg.env)]
    os.symlink(new, link)
    e = history.record("Tool now uses Tool-2", [], trashed, env=xdg.env, added=[link])
    history.undo(e.id, xdg.env)
    assert os.path.islink(link) and os.readlink(link) == old and os.path.exists(old)


def test_undo_that_cant_finish_changes_nothing_or_can_be_tried_again(xdg, monkeypatch):
    """The new link can't go to the Trash: nothing is undone. A file can't
    be put back: the rest is undone, and Undo can be tried again."""
    import os
    home = xdg.env["HOME"]
    os.makedirs(home + "/.local/bin")
    old, new, link = f"{home}/Tool-1.AppImage", f"{home}/Tool-2.AppImage", f"{home}/.local/bin/tool"
    for p in (old, new):
        with open(p, "w") as f:
            f.write(p)
    os.symlink(old, link)
    trashed = [trash.move(old, xdg.env), trash.move(link, xdg.env)]
    os.symlink(new, link)
    e = history.record("Tool now uses Tool-2", [], trashed, env=xdg.env, added=[link])

    real_move, real_restore = trash.move, trash.restore

    def no_trash(path, env=None):
        raise trash.TrashError("the Trash can't be written")
    monkeypatch.setattr(trash, "move", no_trash)
    with pytest.raises(history.UndoError):
        history.undo(e.id, xdg.env)
    assert os.readlink(link) == new and not os.path.exists(old)         # nothing changed
    monkeypatch.setattr(trash, "move", real_move)

    def restore_once_fails(t):
        if t.original == link:
            raise trash.TrashError("disk full")
        real_restore(t)
    monkeypatch.setattr(trash, "restore", restore_once_fails)
    with pytest.raises(history.UndoError):
        history.undo(e.id, xdg.env)
    assert os.path.exists(old) and not os.path.lexists(link)            # the old file is back
    monkeypatch.setattr(trash, "restore", real_restore)
    history.undo(e.id, xdg.env)                                         # and the rest, on a second try
    assert os.readlink(link) == old
