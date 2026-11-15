from app_entries import app_updates as au
from app_entries import github_apps as gh


def fake(answers):
    def run(argv):
        for key, out in answers.items():
            if tuple(argv[:len(key)]) == key:
                return out
        return None
    return run


def test_counts_waiting_system_updates():
    which = lambda t: "/usr/bin/" + t if t in ("pacman", "checkupdates", "paru", "flatpak", "snap") else None  # noqa: E731
    run = fake({("checkupdates",): (0, "linux 6.1 -> 6.2\nmesa 24 -> 25\n"),
                ("flatpak", "remote-ls"): (0, "org.gimp.GIMP\n"),
                ("snap", "refresh", "--list"): (0, "All snaps up to date.\n")})
    got = {w.source: w for w in au.system_updates(run, which)}
    assert got["pacman"].count == 2 and got["pacman"].names == ["linux", "mesa"]
    assert got["pacman"].command == [["paru", "-Syu"]]           # the AUR helper updates the AUR too
    assert got["Flatpak"].count == 1 and got["Flatpak"].command == [["flatpak", "update"]]
    assert got["Snap"].count == 0
    # checkupdates says "nothing" with exit code 2.
    none = au.system_updates(fake({("checkupdates",): (2, "")}), lambda t: "/x" if t in ("pacman", "checkupdates")
                             else None)
    assert none[0].count == 0


def test_gathers_apps_packages_and_tools(tmp_path, monkeypatch):
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    # an AppImage that says where its updates come from is found by install_info; here an AUR package
    run = fake({("pacman", "-Qqm"): (0, "tool-bin\nlocal-thing\n"),
                ("pacman", "-Qi", "tool-bin"): (0, "Name : tool-bin\nVersion : 1.2-1\nURL : https://github.com/o/tool\n"),
                ("pacman", "-Qi", "local-thing"): (0, "Name : local-thing\nVersion : 1\nURL : https://example.org\n")})
    items = au.gather([], run, lambda t: "/usr/bin/pacman" if t == "pacman" else None)
    assert [(c.key, c.kind, c.version, c.src.name) for c in items] == [("pkg:tool-bin", "aur", "1.2-1", "o/tool")]
    c = au.check(items[0], get=lambda url: {"tag_name": "v1.3", "assets": []})
    assert c.result.newer and c.result.current == "1.2" and not c.error
    c = au.check(items[0], get=lambda url: (_ for _ in ()).throw(gh.GitHubError("limit")))
    assert c.error == "limit" and c.result is None


def test_the_daily_check_runs_once_a_day(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    t = 1_800_000_000
    assert au.due(now=t)                     # never checked
    au.save_state(t, ["a.desktop"])
    assert not au.due(now=t + 3600) and au.due(now=t + 25 * 3600)
    assert au.load_state()["newer"] == ["a.desktop"]
