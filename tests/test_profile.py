import json
import os

import pytest

from conftest import entry
from app_entries import cli, profile
from app_entries import desktop_entries as de
from app_entries import overrides as ov


def app(xdg, did):
    return next(a for a in de.scan(xdg.env) if a.id == did)


def moved(xdg, tmp_name="other"):
    """The same system apps under another user's home."""
    home = xdg.tmp / tmp_name
    (home / ".local" / "share" / "applications").mkdir(parents=True)
    env = dict(xdg.env, HOME=str(home))
    return env, home / ".local" / "share"


def test_export_stores_hidden_apps_by_id_and_launchers_in_full(xdg):
    xdg.write(xdg.sys_b, "a.desktop", entry("Alpha", Icon="alpha"))
    xdg.write(xdg.sys_b, "b.desktop", entry("Beta"))
    ov.set_hidden(app(xdg, "a.desktop"), True, xdg.env)
    icon = xdg.tmp / "home" / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "app-entries-mine.svg"
    icon.parent.mkdir(parents=True)
    icon.write_text("<svg/>")
    xdg.write(xdg.user, "mine.desktop", entry("Mine", exec_="mine", Icon=str(icon), **{"X-AppEntries-Created": "true"}))
    xdg.write(xdg.user, "own.desktop", entry("Own", exec_="own"))  # not made by App Entries

    text, items, others = profile.export_text(de.scan(xdg.env), env=xdg.env)
    doc = json.loads(text)
    kinds = {i["id"]: i["kind"] for i in doc["items"]}
    assert kinds == {"a.desktop": "hidden", "mine.desktop": "launcher"}
    assert others == 1
    assert "text" not in doc["items"][0]  # the hidden app is stored by ID only
    launcher = next(i for i in doc["items"] if i["id"] == "mine.desktop")
    assert "Icon=@DATA@/icons/hicolor/scalable/apps/app-entries-mine.svg" in launcher["text"]
    assert list(doc["files"]) == ["@DATA@/icons/hicolor/scalable/apps/app-entries-mine.svg"]

    _, items, others = profile.export_text(de.scan(xdg.env), include_others=True, env=xdg.env)
    assert {i.id for i in items} == {"a.desktop", "mine.desktop", "own.desktop"} and others == 0


def test_import_on_another_home_hides_installed_apps_and_adds_launchers(xdg):
    xdg.write(xdg.sys_b, "a.desktop", entry("Alpha"))
    ov.set_hidden(app(xdg, "a.desktop"), True, xdg.env)
    icon = xdg.tmp / "home" / ".local" / "share" / "icons" / "app-entries-mine.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"\x89PNG\r\n\x1a\nbinary\x00\xff")
    xdg.write(xdg.user, "mine.desktop", entry("Mine", exec_="mine", Icon=str(icon),
                                              **{"X-AppEntries-Created": "true"}))
    doc = json.loads(profile.export_text(de.scan(xdg.env), env=xdg.env)[0])
    doc["items"].append({"id": "gone.desktop", "name": "Gone", "kind": "hidden"})

    env, data = moved(xdg)
    plan = profile.plan_import(profile.parse(doc), de.scan(env), env)
    assert ("Gone", "not installed here") in plan.skipped
    assert sorted(plan.adds) == ["Add launcher Mine", "Hide Alpha"]
    ov.apply_all(plan.changes)

    apps = {a.id: a for a in de.scan(env)}
    assert apps["a.desktop"].hidden
    new_icon = data / "icons" / "app-entries-mine.png"
    assert new_icon.read_bytes() == icon.read_bytes()
    assert de.DesktopFile((data / "applications" / "mine.desktop").read_text()).group_dict()["Icon"] == str(new_icon)

    # Importing again changes nothing; undoing puts everything back.
    again = profile.plan_import(profile.parse(doc), de.scan(env), env)
    assert not again.changes and again.unchanged == 2
    ov.undo_all(plan.changes)
    assert not new_icon.exists() and not (data / "applications" / "mine.desktop").exists()
    assert not next(a for a in de.scan(env) if a.id == "a.desktop").hidden


def test_import_refuses_paths_outside_the_icon_folders(xdg):
    doc = {"format": 1, "items": [{"id": "x.desktop", "name": "X", "kind": "launcher",
                                   "text": entry("X", exec_="x", Icon="@DATA@/../../.bashrc")}],
           "files": {"@DATA@/../../.bashrc": "ZXZpbA=="}}
    plan = profile.plan_import(profile.parse(doc), [], xdg.env)
    assert all(c.path.endswith(".desktop") for c in plan.changes)
    with pytest.raises(profile.ProfileError):
        profile.parse({"items": [{"id": "../evil.desktop", "kind": "launcher"}]})
    with pytest.raises(profile.ProfileError):
        profile.parse({"format": 99, "items": []})


def test_cli_hide_list_and_unhide(xdg, monkeypatch, capsys):
    xdg.write(xdg.sys_b, "org.example.Alpha.desktop", entry("Alpha"))
    for k, v in xdg.env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert cli.wants_cli(["x", "--list"]) and not cli.wants_cli(["x"])
    assert cli.main(["x", "--hide", "alpha"]) == 0
    assert (xdg.user / "org.example.Alpha.desktop").exists()
    capsys.readouterr()
    assert cli.main(["x", "--list", "--hidden"]) == 0
    assert "org.example.Alpha.desktop" in capsys.readouterr().out
    assert cli.main(["x", "--unhide", "org.example.Alpha"]) == 0
    assert not (xdg.user / "org.example.Alpha.desktop").exists()
    assert cli.main(["x", "--hide", "nothing-like-this"]) == 1


def test_cli_export_then_import_needs_yes_without_a_terminal(xdg, monkeypatch, capsys):
    xdg.write(xdg.sys_b, "a.desktop", entry("Alpha"))
    for k, v in xdg.env.items():
        monkeypatch.setenv(k, v)
    out = str(xdg.tmp / "backup.json")
    cli.main(["x", "--hide", "a"])
    assert cli.main(["x", "--export", out]) == 0
    cli.main(["x", "--unhide", "a"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["x", "--import", out]) == 1
    assert not os.path.exists(xdg.user / "a.desktop")
    assert cli.main(["x", "--import", out, "--yes"]) == 0
    assert app(xdg, "a.desktop").hidden
