from app_entries import app_updates as au


def fake(answers):
    def run(argv):
        for key, out in answers.items():
            if tuple(argv[:len(key)]) == key:
                return out
        return None
    return run


def test_flatpaks_with_an_update_waiting():
    run = fake({("flatpak", "remote-ls"): (0, "Application ID\norg.gimp.GIMP\nmd.obsidian.Obsidian\n")})
    assert au.flatpak_waiting(run, lambda t: "/usr/bin/flatpak") == {"org.gimp.GIMP", "md.obsidian.Obsidian"}
    assert au.flatpak_waiting(run, lambda t: None) == set()          # no Flatpak, no question
    assert au.flatpak_waiting(fake({}), lambda t: "/usr/bin/flatpak") == set()     # it couldn't say


def test_only_what_the_package_manager_doesnt_update_is_watched(tmp_path, monkeypatch):
    """Packages (the AUR among them) are the package manager's: not watched,
    whatever their homepage says."""
    from app_entries import desktop_entries as de
    monkeypatch.setenv("HOME", str(tmp_path))
    pkg = de.App(id="tool-bin.desktop", name="Tool", exec="/usr/bin/tool", base_path="/usr/share/applications/t",
                 system=True, source="system")
    assert au.gather([pkg]) == []


def test_the_daily_check_runs_once_a_day(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    t = 1_800_000_000
    assert au.due(now=t)                     # never checked
    au.save_state(t, ["a.desktop"], info={"a.desktop": "2.0"})
    assert not au.due(now=t + 3600) and au.due(now=t + 25 * 3600)
    assert au.load_state()["newer"] == ["a.desktop"] and au.load_state()["info"] == {"a.desktop": "2.0"}
