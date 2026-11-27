from app_entries import app_updates as au


def fake(answers):
    def run(argv):
        for key, out in answers.items():
            if tuple(argv[:len(key)]) == key:
                return out
        return None
    return run


def test_flatpaks_with_an_update_waiting():
    run = fake({
        ("flatpak", "remote-ls", "--system"): (0, ("Application ID\tCommit\norg.gimp.GIMP\taaaaaaaaaaaa\n"
                                                   "md.obsidian.Obsidian\tbbbbbbbbbbbb\nio.held.App\tcccccccccccc\n")),
        ("flatpak", "list", "--system"): (0, ("org.gimp.GIMP\t111111111111\n"
                                             "md.obsidian.Obsidian\tbbbbbbbbbbbb\nio.held.App\t222222222222\n")),
        ("flatpak", "mask", "--system"): (0, "  io.held.*\n"),
        ("flatpak", "remote-ls", "--user"): (0, "com.spotify.Client\tdddddddddddd\n"),
        ("flatpak", "list", "--user"): (0, "com.spotify.Client\t333333333333\n"),
        ("flatpak", "mask", "--user"): (0, ""),
    })
    found = au.flatpak_waiting(run, lambda t: "/usr/bin/flatpak")
    # Obsidian is listed but already at that commit; the held-back one is masked: neither gets a dot.
    assert found == {"org.gimp.GIMP": {"scope": "system", "commit": "111111111111"},
                     "com.spotify.Client": {"scope": "user", "commit": "333333333333"}}
    assert au.flatpak_waiting(run, lambda t: None) == {}             # no Flatpak, no question
    assert au.flatpak_waiting(fake({}), lambda t: "/usr/bin/flatpak") == {}      # it couldn't say
    assert au.flatpak_still_waiting("org.gimp.GIMP", "system", run) is True
    assert au.flatpak_still_waiting("md.obsidian.Obsidian", "system", run) is False
    assert au.flatpak_still_waiting("org.gimp.GIMP", "user", run) is False      # not in that installation
    assert au.flatpak_still_waiting("x", "system", fake({})) is None


def test_the_installed_flatpak_commit_is_read_from_its_folder(tmp_path):
    import os
    d = tmp_path / ".local/share/flatpak/app/org.gimp.GIMP/x86_64/stable"
    d.mkdir(parents=True)
    os.symlink("1111111111112222", d / "active")
    assert au.flatpak_commit("org.gimp.GIMP", "user", str(tmp_path)) == "1111111111112222"
    assert au.flatpak_commit("org.other.App", "user", str(tmp_path)) == ""
    assert au._same_commit("111111111111", "1111111111112222") and not au._same_commit("1111", "1111")


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
