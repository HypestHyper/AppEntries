import pytest

from conftest import entry
from app_entries import autostart as au
from app_entries import desktop_entries as de
from app_entries import overrides as ov


@pytest.fixture
def cfg(tmp_path):
    home = tmp_path / "home"
    sysdir = tmp_path / "etc" / "xdg" / "autostart"
    sysdir.mkdir(parents=True)
    env = {"HOME": str(home), "XDG_CONFIG_DIRS": str(tmp_path / "etc" / "xdg"), "LANG": "C",
           "XDG_CURRENT_DESKTOP": "GNOME", "XDG_DATA_DIRS": str(tmp_path / "usr")}

    class C:
        pass
    c = C()
    c.env, c.sys, c.user, c.tmp = env, sysdir, home / ".config" / "autostart", tmp_path
    return c


def item(cfg, did):
    return next(i for i in au.scan(cfg.env) if i.id == did)


def test_turning_a_system_entry_off_and_on_never_touches_it(cfg):
    sys_file = cfg.sys / "applet.desktop"
    sys_file.write_text(entry("Applet", "applet --tray"))
    original = sys_file.read_text()
    it = item(cfg, "applet.desktop")
    assert it.enabled and it.system and not it.user_path

    change = au.plan_set_enabled(it, False, cfg.env)
    ov.apply(change)
    d = de.DesktopFile((cfg.user / "applet.desktop").read_text()).group_dict()
    assert d["Hidden"] == "true" and d["Exec"] == "applet --tray"
    it = item(cfg, "applet.desktop")
    assert not it.enabled and it.managed

    ov.apply(au.plan_set_enabled(it, True, cfg.env))
    assert not (cfg.user / "applet.desktop").exists()  # our copy goes, the system one is used again
    assert item(cfg, "applet.desktop").enabled
    assert sys_file.read_text() == original


def test_gnome_disabled_key_and_desktop_rules_count(cfg):
    (cfg.sys / "a.desktop").write_text(entry("A", **{"X-GNOME-Autostart-enabled": "false"}))
    (cfg.sys / "b.desktop").write_text(entry("B", OnlyShowIn="KDE;"))
    a, b = item(cfg, "a.desktop"), item(cfg, "b.desktop")
    assert not a.enabled and not b.enabled and b.excluded_here
    ov.apply(au.plan_set_enabled(b, True, cfg.env))
    d = de.DesktopFile((cfg.user / "b.desktop").read_text()).group_dict()
    assert "GNOME" in d["OnlyShowIn"] and item(cfg, "b.desktop").enabled


def test_your_own_entries_are_switched_in_place_and_deleted(cfg):
    cfg.user.mkdir(parents=True)
    (cfg.user / "mine.desktop").write_text(entry("Mine", "mine"))
    it = item(cfg, "mine.desktop")
    ov.apply(au.plan_set_enabled(it, False, cfg.env))
    assert "Hidden=true" in (cfg.user / "mine.desktop").read_text()
    ov.apply(au.plan_set_enabled(item(cfg, "mine.desktop"), True, cfg.env))
    assert "Hidden" not in (cfg.user / "mine.desktop").read_text()
    change = au.plan_delete(item(cfg, "mine.desktop"))
    ov.apply(change)
    assert not (cfg.user / "mine.desktop").exists()
    ov.undo(change)
    assert (cfg.user / "mine.desktop").exists()


def test_adding_an_app_and_a_command(cfg):
    app = de.App(id="org.x.Notes.desktop", name="Notes", source_path=str(cfg.tmp / "notes.desktop"))
    (cfg.tmp / "notes.desktop").write_text(entry("Notes", "notes %U", NoDisplay="true", OnlyShowIn="KDE;"))
    ov.apply(au.plan_add_app(app, cfg.env))
    it = item(cfg, "org.x.Notes.desktop")
    assert it.enabled and it.created and it.exec == "notes"
    ov.apply(au.plan_add_app(app, cfg.env))  # a second copy gets its own name
    assert item(cfg, "org.x.Notes-2.desktop")

    ov.apply(au.plan_add_command("Sync folder", 'rclone sync "a b" c', cfg.env))
    it = item(cfg, "app-entries-sync-folder.desktop")
    assert it.exec == 'rclone sync "a b" c' and it.created
    with pytest.raises(ValueError):
        au.plan_add_command(" ", "x", cfg.env)


def test_desktops_that_dont_run_autostart():
    assert not au.runs_autostart({"XDG_CURRENT_DESKTOP": "Hyprland"})
    assert au.runs_autostart({"XDG_CURRENT_DESKTOP": "KDE"})
