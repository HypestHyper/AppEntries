import os
import stat

import pytest

from conftest import entry
from app_entries import desktop_entries as de
from app_entries import overrides as ov


def only(xdg):
    (app,) = de.scan(xdg.env)
    return app


def group(path):
    return de.DesktopFile(path.read_text()).group_dict()


def test_hide_writes_full_nodisplay_copy_and_unhide_deletes_it(xdg):
    sys_file = xdg.write(xdg.sys_b, "app.desktop",
                         entry("Thing", MimeType="text/html;", Icon="thing"))
    original = sys_file.read_text()
    change = ov.set_hidden(only(xdg), True, xdg.env)
    path = xdg.user / "app.desktop"
    assert change.path == str(path) and change.before is None
    d = group(path)
    # Everything a launcher or "Open With" needs is still there.
    assert d["Exec"] == "thing %U" and d["MimeType"] == "text/html;" and d["Icon"] == "thing"
    assert d["NoDisplay"] == "true" and "Hidden" not in d
    assert d[de.MANAGED_KEY] == "true" and ov.is_pristine(de.DesktopFile(path.read_text()))
    app = only(xdg)
    assert app.hidden and app.override_managed and not app.no_display

    ov.set_hidden(app, False, xdg.env)
    assert not path.exists()
    assert not only(xdg).hidden
    assert sys_file.read_text() == original


def test_hidden_apps_are_listed_without_the_no_display_option(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    ov.set_hidden(only(xdg), True, xdg.env)
    (app,) = de.scan(xdg.env, include_no_display=False)
    assert app.hidden


def test_hide_updates_existing_user_override_in_place(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    text = "[Desktop Entry]\n# my tweak\nType=Application\nName=Thing\nExec=thing --fast\n\n[Desktop Action a]\nName=A\nExec=a\n"
    user = xdg.write(xdg.user, "app.desktop", text)
    ov.set_hidden(only(xdg), True, xdg.env)
    d = group(user)
    assert d["NoDisplay"] == "true" and d[de.HIDDEN_KEY] == "true" and "# my tweak" in user.read_text()
    assert de.MANAGED_KEY not in d
    ov.set_hidden(only(xdg), False, xdg.env)
    assert user.read_text() == text


def test_user_only_app_hides_in_place_and_stays_listed(xdg):
    text = entry("Mine", "/home/me/run.sh")
    user = xdg.write(xdg.user, "mine.desktop", text)
    ov.set_hidden(only(xdg), True, xdg.env)
    (app,) = de.scan(xdg.env, include_no_display=False)
    assert app.hidden and not app.no_display
    ov.set_hidden(app, False, xdg.env)
    assert user.read_text() == text


def test_unhide_full_override_with_hidden_removes_only_that_line(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    user = xdg.write(xdg.user, "app.desktop", entry("Thing", "thing --x", Hidden="true", Icon="mine"))
    ov.set_hidden(only(xdg), False, xdg.env)
    d = group(user)
    assert "Hidden" not in d and d["Icon"] == "mine" and d["Exec"] == "thing --x"


def test_unhide_users_own_nodisplay_line(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    user = xdg.write(xdg.user, "app.desktop", entry("Thing", NoDisplay="true", Icon="mine"))
    ov.set_hidden(only(xdg), False, xdg.env)
    d = group(user)
    assert "NoDisplay" not in d and d["Icon"] == "mine"
    assert not only(xdg).hidden


def test_unhide_foreign_bare_override_needs_confirmation(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    user = xdg.write(xdg.user, "app.desktop", "[Desktop Entry]\nType=Application\nName=Thing\nHidden=true\n")
    with pytest.raises(ov.NeedsConfirmation) as e:
        ov.set_hidden(only(xdg), False, xdg.env)
    assert e.value.path == str(user) and user.exists()
    ov.set_hidden(only(xdg), False, xdg.env, allow_delete=True)
    assert not user.exists()


def test_edited_copy_is_kept_and_only_unhidden(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    ov.set_hidden(only(xdg), True, xdg.env)
    user = xdg.user / "app.desktop"
    user.write_text(user.read_text().replace("Name=Thing", "Name=My Thing"))
    assert not ov.is_pristine(de.DesktopFile(user.read_text()))
    ov.set_hidden(only(xdg), False, xdg.env)
    d = group(user)
    assert user.exists() and "NoDisplay" not in d and d["Name"] == "My Thing"
    assert not only(xdg).hidden


def test_undo_restores_exact_bytes(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    text = "[Desktop Entry]\nType=Application\nName=Thing\nHidden=true\n# mine\n"
    user = xdg.write(xdg.user, "app.desktop", text)
    change = ov.set_hidden(only(xdg), False, xdg.env, allow_delete=True)
    assert not user.exists()
    ov.undo(change)
    assert user.read_text() == text


def test_undo_refuses_if_file_changed(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    change = ov.set_hidden(only(xdg), True, xdg.env)
    (xdg.user / "app.desktop").write_text("changed\n")
    with pytest.raises(ov.ConflictError):
        ov.undo(change)
    assert (xdg.user / "app.desktop").read_text() == "changed\n"


def test_hide_already_hidden_is_noop(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    ov.set_hidden(only(xdg), True, xdg.env)
    assert ov.set_hidden(only(xdg), True, xdg.env) is None
    assert ov.set_hidden(only(xdg), False, xdg.env) is not None
    assert ov.set_hidden(only(xdg), False, xdg.env) is None


@pytest.mark.parametrize("key", ["Hidden", "NoDisplay"])
def test_show_app_hidden_by_its_package(xdg, key):
    sys_file = xdg.write(xdg.sys_b, "app.desktop", entry("Thing", **{key: "true"}))
    app = only(xdg)
    assert app.hidden and app.base_hidden
    ov.set_hidden(app, False, xdg.env)
    assert sys_file.read_text().count("%s=true" % key) == 1
    app = only(xdg)
    assert not app.hidden and app.override_managed
    assert group(xdg.user / "app.desktop")["NoDisplay"] == "false"
    # Hiding it again just removes the copy.
    ov.set_hidden(app, True, xdg.env)
    assert not (xdg.user / "app.desktop").exists() and only(xdg).hidden


def test_update_legacy_turns_old_hidden_file_into_copy(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing", MimeType="text/plain;"))
    old = "[Desktop Entry]\nType=Application\nName=Thing\nHidden=true\n%s=true\n" % de.MANAGED_KEY
    xdg.write(xdg.user, "app.desktop", old)
    ov.apply(ov.plan_update_legacy(only(xdg)))
    d = group(xdg.user / "app.desktop")
    assert d["NoDisplay"] == "true" and d["MimeType"] == "text/plain;" and "Hidden" not in d
    assert only(xdg).hidden


def test_update_legacy_refuses_other_files(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    xdg.write(xdg.user, "app.desktop", "[Desktop Entry]\nType=Application\nName=Thing\nHidden=true\n")
    with pytest.raises(ov.OverrideError):
        ov.plan_update_legacy(only(xdg))


def test_restore_original_deletes_users_copy_with_undo(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    text = entry("My Thing", "thing --mine")
    user = xdg.write(xdg.user, "app.desktop", text)
    change = ov.plan_restore_original(only(xdg))
    ov.apply(change)
    assert not user.exists() and only(xdg).name == "Thing"
    ov.undo(change)
    assert user.read_text() == text


def test_restore_original_needs_a_system_entry(xdg):
    xdg.write(xdg.user, "mine.desktop", entry("Mine"))
    with pytest.raises(ov.OverrideError):
        ov.plan_restore_original(only(xdg))


def test_unhide_all_skips_package_hidden_and_foreign_files(xdg):
    for n in ("a", "b", "c", "d"):
        xdg.write(xdg.sys_b, n + ".desktop", entry(n.upper()))
    xdg.write(xdg.sys_b, "pkg.desktop", entry("Pkg", NoDisplay="true"))
    apps = {a.id: a for a in de.scan(xdg.env)}
    ov.set_hidden(apps["a.desktop"], True, xdg.env)
    ov.set_hidden(apps["b.desktop"], True, xdg.env)
    xdg.write(xdg.user, "c.desktop", "[Desktop Entry]\nType=Application\nName=C\nHidden=true\n")
    changes, skipped = ov.plan_unhide_all(de.scan(xdg.env), xdg.env)
    assert sorted(c.app_id for c in changes) == ["a.desktop", "b.desktop"]
    assert [a.id for a in skipped] == ["c.desktop"]
    done = ov.apply_all(changes)
    shown = {a.id: a.hidden for a in de.scan(xdg.env)}
    assert not shown["a.desktop"] and not shown["b.desktop"] and shown["c.desktop"] and shown["pkg.desktop"]
    ov.undo_all(done)
    assert {a.id: a.hidden for a in de.scan(xdg.env)}["a.desktop"]


def test_apply_all_is_all_or_nothing(xdg):
    xdg.write(xdg.sys_b, "a.desktop", entry("A"))
    xdg.write(xdg.sys_b, "b.desktop", entry("B"))
    apps = {a.id: a for a in de.scan(xdg.env)}
    first = ov.plan_set_hidden(apps["a.desktop"], True, xdg.env)
    second = ov.plan_set_hidden(apps["b.desktop"], True, xdg.env)
    second.before = "something else\n"  # makes it conflict
    with pytest.raises(ov.ConflictError):
        ov.apply_all([first, second])
    assert not (xdg.user / "a.desktop").exists()


def test_copy_tracks_a_newer_system_entry(xdg):
    sys_file = xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    ov.set_hidden(only(xdg), True, xdg.env)
    sys_file.write_text(entry("Thing", "thing --new"))
    # The untouched copy is still ours to drop, so showing restores the new entry.
    ov.set_hidden(only(xdg), False, xdg.env)
    assert not (xdg.user / "app.desktop").exists()
    assert only(xdg).exec == "thing --new"


def test_subdir_id_writes_flat_override(xdg):
    xdg.write(xdg.sys_b, "wine/notepad.desktop", entry("Notepad"))
    change = ov.set_hidden(only(xdg), True, xdg.env)
    assert change.path == str(xdg.user / "wine-notepad.desktop")
    assert only(xdg).hidden


def test_user_dir_created_when_missing(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    os.rmdir(xdg.user)
    ov.set_hidden(only(xdg), True, xdg.env)
    assert (xdg.user / "app.desktop").exists()


def test_atomic_write_keeps_mode_and_leaves_no_temp(xdg):
    p = xdg.write(xdg.user, "x.desktop", "a\n")
    os.chmod(p, 0o600)
    ov.atomic_write(str(p), "b\n")
    assert p.read_text() == "b\n" and stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert [f for f in os.listdir(xdg.user) if f.endswith(".tmp")] == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_permission_error_names_the_path(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    os.chmod(xdg.user, 0o500)
    try:
        with pytest.raises(ov.OverrideError) as e:
            ov.set_hidden(only(xdg), True, xdg.env)
        assert e.value.path == str(xdg.user / "app.desktop")
    finally:
        os.chmod(xdg.user, 0o700)


def test_write_error_via_fake_dir(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    os.rmdir(xdg.user)
    xdg.user.write_text("not a dir")  # makedirs/mkstemp will fail
    with pytest.raises(ov.OverrideError):
        ov.set_hidden(only(xdg), True, xdg.env)


def test_entry_for_another_desktop_counts_as_hidden_and_can_be_shown(xdg):
    env = dict(xdg.env, XDG_CURRENT_DESKTOP="Hyprland")
    sys_file = xdg.write(xdg.sys_b, "org.xfce.about.desktop", entry("About Xfce", OnlyShowIn="XFCE;"))
    xdg.write(xdg.sys_b, "kde.desktop", entry("KDE thing", NotShowIn="GNOME;Hyprland;"))
    apps = {a.id: a for a in de.scan(env)}
    about = apps["org.xfce.about.desktop"]
    assert about.hidden and about.excluded_here and about.base_hidden and not about.no_display
    assert about.only_show_in == ("XFCE",)
    ov.set_hidden(about, False, env)
    d = group(xdg.user / "org.xfce.about.desktop")
    assert d["OnlyShowIn"] == "XFCE;Hyprland;" and "OnlyShowIn=XFCE;" in sys_file.read_text()
    assert not {a.id: a for a in de.scan(env)}["org.xfce.about.desktop"].hidden
    # Hiding again drops the copy, back to the system's rule.
    ov.set_hidden({a.id: a for a in de.scan(env)}["org.xfce.about.desktop"], True, env)
    assert not (xdg.user / "org.xfce.about.desktop").exists()
    kde = apps["kde.desktop"]
    ov.set_hidden(kde, False, env)
    assert group(xdg.user / "kde.desktop")["NotShowIn"] == "GNOME;"
    # On a desktop the rule allows, nothing is hidden.
    assert not {a.id: a for a in de.scan(dict(xdg.env, XDG_CURRENT_DESKTOP="XFCE"))}["org.xfce.about.desktop"].hidden
