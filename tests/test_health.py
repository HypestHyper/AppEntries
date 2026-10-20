import os

from conftest import entry
from app_entries import desktop_entries as de
from app_entries import health
from app_entries import overrides as ov


def with_path(xdg, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for prog in ("thing", "real"):
        p = bin_dir / prog
        p.write_text("#!/bin/sh\n")
        os.chmod(p, 0o755)
    return dict(xdg.env, PATH=str(bin_dir))


def by_id(apps):
    return {a.id: a for a in apps}


def test_sources(xdg, tmp_path):
    flat = xdg.tmp / "flat" / "exports" / "share" / "applications"
    flat.mkdir(parents=True)
    (flat.parent.parent.parent / "flatpak").mkdir()
    env = dict(xdg.env, XDG_DATA_DIRS=xdg.env["XDG_DATA_DIRS"] + ":" + str(xdg.tmp / "flatpak" / "exports" / "share"))
    fp = xdg.tmp / "flatpak" / "exports" / "share" / "applications"
    fp.mkdir(parents=True)
    xdg.write(fp, "org.x.App.desktop", entry("Flat", "/usr/bin/flatpak run org.x.App"))
    xdg.write(xdg.sys_b, "sys.desktop", entry("Sys"))
    xdg.write(xdg.sys_b, "snapapp.desktop", entry("Snappy", "/snap/bin/snappy"))
    xdg.write(xdg.user, "img.desktop", entry("Img", "/home/me/Apps/Tool.AppImage"))
    xdg.write(xdg.user, "game.desktop", entry("Game", "steam steam://rungameid/620"))
    xdg.write(xdg.user, "mine.desktop", entry("Mine", "/home/me/run.sh"))
    apps = by_id(de.scan(env))
    got = {k: health.source_of(a) for k, a in apps.items()}
    assert got == {"org.x.App.desktop": "flatpak", "sys.desktop": "system", "snapapp.desktop": "snap",
                   "img.desktop": "appimage", "game.desktop": "steam", "mine.desktop": "user"}


def test_missing_programs(xdg, tmp_path):
    env = with_path(xdg, tmp_path)
    xdg.write(xdg.sys_b, "ok.desktop", entry("Ok", "env FOO=1 thing %U"))
    xdg.write(xdg.sys_b, "gone.desktop", entry("Gone", "nothere --x"))
    xdg.write(xdg.sys_b, "try.desktop", entry("Try", "real", TryExec="also-missing"))
    xdg.write(xdg.sys_b, "abs.desktop", entry("Abs", "/opt/nope/bin/app"))
    xdg.write(xdg.sys_b, "var.desktop", entry("Var", "$HOME/bin/x"))
    apps = de.scan(env)
    report = health.check(apps, env)
    got = {a.id: a.missing for a in apps}
    assert got == {"ok.desktop": "", "gone.desktop": "nothere", "try.desktop": "also-missing",
                   "abs.desktop": "/opt/nope/bin/app", "var.desktop": ""}
    assert sorted(a.id for a in report.missing) == ["abs.desktop", "gone.desktop", "try.desktop"]


def test_hidden_apps_with_missing_programs_are_not_reported(xdg, tmp_path):
    env = with_path(xdg, tmp_path)
    xdg.write(xdg.sys_b, "gone.desktop", entry("Gone", "nothere"))
    ov.set_hidden(de.scan(env)[0], True, env)
    assert health.check(de.scan(env), env).missing == []


def test_leftovers(xdg):
    xdg.write(xdg.sys_b, "still.desktop", entry("Still"))
    ov.set_hidden(de.scan(xdg.env)[0], True, xdg.env)
    # Files for apps that are gone: one App Entries made, one bare Hidden file.
    xdg.write(xdg.user, "gone.desktop", entry("Gone", NoDisplay="true", **{de.MANAGED_KEY: "true"}))
    xdg.write(xdg.user, "bare.desktop", "[Desktop Entry]\nType=Application\nName=Bare\nHidden=true\n")
    # The user's own launcher is not a leftover.
    xdg.write(xdg.user, "mine.desktop", entry("Mine"))
    got = [(l.id, l.name) for l in health.find_leftovers(xdg.env)]
    assert got == [("bare.desktop", "Bare"), ("gone.desktop", "Gone")]


def test_duplicates(xdg):
    xdg.write(xdg.sys_b, "firefox.desktop", entry("Firefox"))
    xdg.write(xdg.sys_a, "org.mozilla.firefox.desktop", entry("firefox "))
    xdg.write(xdg.sys_b, "solo.desktop", entry("Solo"))
    xdg.write(xdg.sys_b, "a.desktop", entry("Twice"))
    xdg.write(xdg.sys_b, "b.desktop", entry("Twice", NoDisplay="true"))
    groups = health.find_duplicates(de.scan(xdg.env))
    assert [sorted(a.id for a in g) for g in groups] == [["firefox.desktop", "org.mozilla.firefox.desktop"]]
    # Once one copy is hidden, it's no longer a duplicate in the launcher.
    apps = by_id(de.scan(xdg.env))
    ov.set_hidden(apps["firefox.desktop"], True, xdg.env)
    assert health.find_duplicates(de.scan(xdg.env)) == []


def test_legacy_hidden(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Thing"))
    xdg.write(xdg.sys_b, "new.desktop", entry("New"))
    xdg.write(xdg.user, "app.desktop",
              "[Desktop Entry]\nType=Application\nName=Thing\nHidden=true\n%s=true\n" % de.MANAGED_KEY)
    ov.set_hidden(by_id(de.scan(xdg.env))["new.desktop"], True, xdg.env)
    assert [a.id for a in health.legacy_hidden(de.scan(xdg.env))] == ["app.desktop"]


def test_program_of_handles_env_and_assignments():
    assert health.program_of("env -u GTK_THEME prog --x") == "prog"
    assert health.program_of("env --chdir /tmp FOO=1 prog") == "prog"
    assert health.program_of("env -i PATH=/bin /opt/app/run") == "/opt/app/run"
    assert health.program_of("FOO=1 BAR=2 prog %U") == "prog"
    assert health.program_of('"/opt/My App/app" --x') == "/opt/My App/app"
    assert health.program_of("systemsettings kcm_style") == "systemsettings"


def test_extra_program_folders(xdg, tmp_path):
    env = dict(xdg.env, PATH="")
    dirs = health.search_dirs(env)
    for d in ("/usr/games", "/snap/bin", "/run/current-system/sw/bin"):
        assert d in dirs
    assert os.path.join(env["HOME"], ".nix-profile", "bin") in dirs


def test_related_entries_in_opposite_states(xdg):
    xdg.write(xdg.sys_b, "gammastep.desktop", entry("gammastep", "gammastep", Icon="gammastep", NoDisplay="true"))
    xdg.write(xdg.sys_b, "gammastep-indicator.desktop",
              entry("Gammastep Indicator", "gammastep-indicator", Icon="gammastep"))
    # Same first word, different icon: not related.
    xdg.write(xdg.sys_b, "gammastep-cli.desktop", entry("Gammastep CLI", "gammastep", Icon="terminal"))
    # Same icon, same state: nothing to point out.
    xdg.write(xdg.sys_b, "office-a.desktop", entry("Office Writer", "a", Icon="office"))
    xdg.write(xdg.sys_b, "office-b.desktop", entry("Office Calc", "b", Icon="office"))
    apps = de.scan(xdg.env)
    health.check(apps, xdg.env)
    got = {a.id: a.related for a in apps}
    assert got["gammastep.desktop"] == ("Gammastep Indicator",)
    assert got["gammastep-indicator.desktop"] == ("gammastep",)
    assert got["gammastep-cli.desktop"] == () and got["office-a.desktop"] == ()


def test_customised(xdg):
    from app_entries import editing as ed
    xdg.write(xdg.sys_b, "a.desktop", entry("A"))
    xdg.write(xdg.sys_b, "b.desktop", entry("B"))
    xdg.write(xdg.sys_b, "c.desktop", entry("C"))
    apps = by_id(de.scan(xdg.env))
    ov.set_hidden(apps["a.desktop"], True, xdg.env)                      # plain hide: not customised
    ov.apply(ed.plan_edit(apps["b.desktop"], ed.copy_fields(ed.read_fields(apps["b.desktop"], xdg.env),
                                                            name="Bee"), xdg.env))
    xdg.write(xdg.user, "c.desktop", entry("C", "c --mine"))             # the user's own copy
    apps = de.scan(xdg.env)
    health.check(apps, xdg.env)
    assert {a.id: a.customised for a in apps} == {"a.desktop": False, "b.desktop": True, "c.desktop": True}


def test_bare_hide_file_is_not_customised(xdg):
    xdg.write(xdg.sys_b, "x.desktop", entry("X"))
    xdg.write(xdg.user, "x.desktop", "[Desktop Entry]\nType=Application\nName=X\nHidden=true\n")
    apps = de.scan(xdg.env)
    health.check(apps, xdg.env)
    assert apps[0].hidden and not apps[0].customised
