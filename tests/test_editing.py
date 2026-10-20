import pytest

from app_entries import desktop_entries as de
from app_entries import editing as ed
from app_entries import overrides as ov

FULL = """[Desktop Entry]
Type=Application
Name=Files
Name[de]=Dateien
GenericName=File Manager
Comment=Access and organize files
Keywords=folder;manager;
Icon=org.gnome.Nautilus
Exec=nautilus --new-window %U
Categories=GNOME;GTK;Utility;Core;
Actions=new-window;
X-Custom=keep me

[Desktop Action new-window]
Name=New Window
Exec=nautilus --new-window
"""


def only(xdg):
    (app,) = de.scan(xdg.env)
    return app


def group(path):
    return de.DesktopFile(path.read_text()).group_dict()


def test_read_fields(xdg):
    xdg.write(xdg.sys_b, "files.desktop", FULL)
    f = ed.read_fields(only(xdg), xdg.env)
    assert f.name == "Files" and f.generic_name == "File Manager" and f.keywords == ["folder", "manager"]
    assert f.command == "nautilus --new-window %U" and f.env == []
    assert f.categories == ["Utility"] and f.show_in == "all"
    assert [(a.id, a.name, a.enabled) for a in f.actions] == [("new-window", "New Window", True)]


def test_edit_system_app_writes_copy_with_only_changes(xdg):
    sys_file = xdg.write(xdg.sys_b, "files.desktop", FULL)
    app = only(xdg)
    f = ed.read_fields(app, xdg.env)
    new = ed.copy_fields(f, name="My Files", env=["GTK_THEME=Adwaita:dark"], terminal=True,
                         categories=["Utility", "System"], show_in="except", desktops=["KDE"])
    new.actions[0].enabled = False
    change = ed.plan_edit(app, new, xdg.env)
    ov.apply(change)
    d = group(xdg.user / "files.desktop")
    assert d["Name"] == "My Files" and "Name[de]" not in d          # the new name shows in any language
    assert d["Exec"] == "env GTK_THEME=Adwaita:dark nautilus --new-window %U"
    assert d["Terminal"] == "true" and d["NotShowIn"] == "KDE;" and "OnlyShowIn" not in d
    assert d["Categories"] == "System;Utility;GNOME;GTK;Core;"
    assert "Actions" not in d
    assert d["X-Custom"] == "keep me" and d["Comment"] == "Access and organize files"
    assert d[de.MANAGED_KEY] == "true" and de.CHECKSUM_KEY not in d
    assert "[Desktop Action new-window]" in (xdg.user / "files.desktop").read_text()
    assert sys_file.read_text() == FULL
    app = only(xdg)
    assert app.name == "My Files"
    # Restore original takes it all back.
    ov.apply(ov.plan_restore_original(app))
    assert only(xdg).name == "Files"


def test_edit_users_own_file_in_place(xdg):
    text = "[Desktop Entry]\n# mine\nType=Application\nName=Mine\nExec=/home/me/run.sh\n"
    user = xdg.write(xdg.user, "mine.desktop", text)
    app = only(xdg)
    new = ed.copy_fields(ed.read_fields(app, xdg.env), icon="/home/me/icon.png", prefers_gpu=True)
    ov.apply(ed.plan_edit(app, new, xdg.env))
    out = user.read_text()
    assert "# mine" in out and "Icon=/home/me/icon.png" in out and "PrefersNonDefaultGPU=true" in out
    assert de.MANAGED_KEY not in out


def test_editing_a_hidden_copy_keeps_it_hidden(xdg):
    xdg.write(xdg.sys_b, "files.desktop", FULL)
    ov.set_hidden(only(xdg), True, xdg.env)
    app = only(xdg)
    ov.apply(ed.plan_edit(app, ed.copy_fields(ed.read_fields(app, xdg.env), comment="Mine"), xdg.env))
    app = only(xdg)
    assert app.hidden and app.comment == "Mine"
    assert not ov.is_pristine(de.DesktopFile((xdg.user / "files.desktop").read_text()))


def test_no_change_is_none(xdg):
    xdg.write(xdg.sys_b, "files.desktop", FULL)
    app = only(xdg)
    assert ed.plan_edit(app, ed.read_fields(app, xdg.env), xdg.env) is None
    assert not (xdg.user / "files.desktop").exists()


def test_validation(xdg):
    xdg.write(xdg.sys_b, "files.desktop", FULL)
    app = only(xdg)
    f = ed.read_fields(app, xdg.env)
    assert ed.validate(ed.copy_fields(f, name=" ")) == ["The name can't be empty."]
    assert ed.validate(ed.copy_fields(f, env=["bad value"]))
    assert ed.validate(ed.copy_fields(f, show_in="only", desktops=[]))
    with pytest.raises(ValueError):
        ed.plan_edit(app, ed.copy_fields(f, command=""), xdg.env)


def test_env_split_and_join():
    assert ed.split_env("env A=1 B=x/y prog --flag %U") == (["A=1", "B=x/y"], "prog --flag %U")
    assert ed.split_env('env "A=a b" prog') == (["A=a b"], "prog")
    assert ed.split_env("env -u X prog") == ([], "env -u X prog")
    assert ed.split_env("prog") == ([], "prog")
    assert ed.join_env(["A=a b", "B=1"], "prog %F") == 'env "A=a b" B=1 prog %F'
    assert ed.join_env([], "prog") == "prog"


def test_values_are_escaped(xdg):
    xdg.write(xdg.sys_b, "files.desktop", FULL)
    app = only(xdg)
    new = ed.copy_fields(ed.read_fields(app, xdg.env), comment="line one\nline two",
                         command="sh -c \"echo a\\\\b\"", keywords=["a;b", "c"])
    ov.apply(ed.plan_edit(app, new, xdg.env))
    raw = group(xdg.user / "files.desktop")
    assert raw["Comment"] == "line one\\nline two"
    assert raw["Keywords"] == "a\\;b;c;"
    assert de.unescape(raw["Exec"]) == "sh -c \"echo a\\\\b\""
    back = ed.read_fields(only(xdg), xdg.env)
    assert back.comment == "line one\nline two" and back.keywords == ["a;b", "c"]


def test_current_desktops():
    assert ed.current_desktops({"XDG_CURRENT_DESKTOP": "Hyprland"}) == ["Hyprland"]
    assert ed.current_desktops({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}) == ["ubuntu", "GNOME"]
    assert ed.current_desktops({}) == []


def test_hidden_switch_in_edit(xdg):
    xdg.write(xdg.sys_b, "files.desktop", FULL)
    app = only(xdg)
    f = ed.read_fields(app, xdg.env)
    assert f.hidden is False
    ov.apply(ed.plan_edit(app, ed.copy_fields(f, name="Mine", hidden=True), xdg.env))
    app = only(xdg)
    assert app.hidden and app.name == "Mine"
    ov.apply(ed.plan_edit(app, ed.copy_fields(ed.read_fields(app, xdg.env), hidden=False), xdg.env))
    app = only(xdg)
    assert not app.hidden and app.name == "Mine"


def test_edit_reads_through_a_bare_hide_file(xdg):
    xdg.write(xdg.sys_b, "files.desktop", FULL)
    user = xdg.write(xdg.user, "files.desktop", "[Desktop Entry]\nType=Application\nName=Files\nHidden=true\n")
    app = only(xdg)
    f = ed.read_fields(app, xdg.env)
    assert f.command == "nautilus --new-window %U" and f.hidden
    ov.apply(ed.plan_edit(app, ed.copy_fields(f, hidden=False), xdg.env))
    d = group(user)
    assert d["Exec"] == "nautilus --new-window %U" and "Hidden" not in d and not only(xdg).hidden


def test_preview_shows_the_file_after_saving(xdg):
    xdg.write(xdg.sys_b, "files.desktop", FULL)
    app = only(xdg)
    f = ed.read_fields(app, xdg.env)
    assert ed.preview(app, f, xdg.env) == FULL
    assert "Name=Changed" in ed.preview(app, ed.copy_fields(f, name="Changed"), xdg.env)
    assert ed.preview(app, ed.copy_fields(f, name=""), xdg.env) == FULL   # invalid: shows the file as it is
