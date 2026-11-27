from app_entries import app_updates as au


def fake(answers):
    def run(argv):
        for key, out in answers.items():
            if tuple(argv[:len(key)]) == key:
                return out
        return None
    return run


def test_flatpaks_with_an_update_waiting(monkeypatch):
    monkeypatch.setattr(au.install_info, "flatpak_installations", lambda root="": [])
    run = fake({
        ("flatpak", "remote-ls", "--system"): (0, ("Application ID\tArch\tBranch\tCommit\n"
                                                   "org.gimp.GIMP\tx86_64\tstable\taaaaaaaaaaaa\n"
                                                   "md.obsidian.Obsidian\tx86_64\tstable\tbbbbbbbbbbbb\n"
                                                   "io.held.App\tx86_64\tstable\tcccccccccccc\n")),
        ("flatpak", "list", "--system"): (0, ("org.gimp.GIMP\tx86_64\tstable\t111111111111\n"
                                             "md.obsidian.Obsidian\tx86_64\tstable\tbbbbbbbbbbbb\n"
                                             "io.held.App\tx86_64\tstable\t222222222222\n")),
        ("flatpak", "mask", "--system"): (0, "  io.held.*\n"),
        ("flatpak", "remote-ls", "--user"): (0, "com.spotify.Client\tx86_64\tstable\tdddddddddddd\n"),
        ("flatpak", "list", "--user"): (0, "com.spotify.Client\tx86_64\tstable\t333333333333\n"),
        ("flatpak", "mask", "--user"): (0, ""),
    })
    found = au.flatpak_waiting(run, lambda t: "/usr/bin/flatpak")
    # Obsidian is listed but already at that commit; the held-back one is masked: neither gets a dot.
    ref = {"arch": "x86_64", "branch": "stable"}
    assert found == {"org.gimp.GIMP": {"scope": "system", "commit": "111111111111", **ref},
                     "com.spotify.Client": {"scope": "user", "commit": "333333333333", **ref}}
    assert au.flatpak_waiting(run, lambda t: None) == {}             # no Flatpak, no question
    assert au.flatpak_waiting(fake({}), lambda t: "/usr/bin/flatpak") == {}      # it couldn't say
    assert au.flatpak_still_waiting("org.gimp.GIMP", "system", run) is True
    assert au.flatpak_still_waiting("org.gimp.GIMP", "system", run, branch="beta") is False
    assert au.flatpak_still_waiting("md.obsidian.Obsidian", "system", run) is False
    assert au.flatpak_still_waiting("io.held.App", "system", run) is False       # masked
    assert au.flatpak_still_waiting("org.gimp.GIMP", "user", run) is False      # not in that installation
    assert au.flatpak_still_waiting("x", "system", fake({})) is None


def test_flatpak_masks_naming_a_branch_or_ref():
    hit = au._mask_hits
    assert hit("org.gimp.GIMP", "org.gimp.GIMP", "x86_64", "stable")
    assert hit("org.gimp.*", "org.gimp.GIMP", "x86_64", "stable")
    assert hit("org.gimp.GIMP//stable", "org.gimp.GIMP", "x86_64", "stable")
    assert not hit("org.gimp.GIMP//beta", "org.gimp.GIMP", "x86_64", "stable")
    assert hit("app/org.gimp.GIMP/x86_64/stable", "org.gimp.GIMP", "x86_64", "stable")
    assert not hit("app/org.gimp.GIMP/aarch64/stable", "org.gimp.GIMP", "x86_64", "stable")
    assert not hit("runtime/org.gimp.GIMP", "org.gimp.GIMP", "x86_64", "stable")
    assert not hit("org.gimp.GIMP.Plugin", "org.gimp.GIMP", "x86_64", "stable")


def test_the_copy_the_launcher_uses_and_other_installations(monkeypatch):
    monkeypatch.setattr(au.install_info, "flatpak_installations", lambda root="": [("sdcard", "/mnt/sd/flatpak")])
    row = "org.gimp.GIMP\tx86_64\tstable\t"
    run = fake({
        ("flatpak", "remote-ls", "--system"): (0, row + "aaaaaaaaaaaa\n"),
        ("flatpak", "list", "--system"): (0, row + "111111111111\n"),
        ("flatpak", "remote-ls", "--user"): (0, row + "aaaaaaaaaaaa\n"),
        ("flatpak", "list", "--user"): (0, row + "222222222222\n"),
        ("flatpak", "remote-ls", "--installation=sdcard"): (0, "org.sd.App\tx86_64\tstable\tcccccccccccc\n"),
        ("flatpak", "list", "--installation=sdcard"): (0, "org.sd.App\tx86_64\tstable\t333333333333\n"),
    })
    yes = lambda t: "/usr/bin/flatpak"   # noqa: E731
    assert au.flatpak_waiting(run, yes)["org.gimp.GIMP"]["scope"] == "system"
    assert au.flatpak_waiting(run, yes, prefer={"org.gimp.GIMP": "user"})["org.gimp.GIMP"]["scope"] == "user"
    assert au.flatpak_waiting(run, yes)["org.sd.App"]["scope"] == "sdcard"
    assert au.flatpak_update_cmd("org.sd.App", "sdcard", "stable") == [
        "flatpak", "update", "--installation=sdcard", "org.sd.App//stable"]
    assert au.flatpak_update_cmd("org.gimp.GIMP", "user") == ["flatpak", "update", "--user", "org.gimp.GIMP"]


def test_the_installed_flatpak_commit_is_read_from_its_folder(tmp_path):
    import os
    app = tmp_path / ".local/share/flatpak/app/org.gimp.GIMP/x86_64"
    for branch, commit in (("beta", "9999999999999999"), ("stable", "1111111111112222")):
        (app / branch).mkdir(parents=True)
        os.symlink(commit, app / branch / "active")
    os.symlink("x86_64/stable", app.parent / "current")
    commit = au.flatpak_commit
    # The branch the check found the update on, not whichever sorts first.
    assert commit("org.gimp.GIMP", "user", str(tmp_path), "x86_64", "stable") == "1111111111112222"
    assert commit("org.gimp.GIMP", "user", str(tmp_path), "x86_64", "beta") == "9999999999999999"
    assert commit("org.gimp.GIMP", "user", str(tmp_path)) == "1111111111112222"      # the current one
    assert commit("org.other.App", "user", str(tmp_path)) == ""
    assert au._same_commit("111111111111", "1111111111112222") and not au._same_commit("1111", "1111")


def test_flatpak_folders_follow_the_environment(tmp_path):
    from app_entries import install_info as ii
    assert ii.flatpak_dir("user", env={"XDG_DATA_HOME": "/d"}) == "/d/flatpak"
    assert ii.flatpak_dir("user", env={"FLATPAK_USER_DIR": "/u", "XDG_DATA_HOME": "/d"}) == "/u"
    assert ii.flatpak_dir("system", env={}) == "/var/lib/flatpak"
    assert ii.flatpak_dir("system", env={"FLATPAK_SYSTEM_DIR": "/s"}) == "/s"
    assert ii.flatpak_dir("user", "/home/x", env={"XDG_DATA_HOME": "/d"}) == "/home/x/.local/share/flatpak"
    conf = tmp_path / "etc/flatpak/installations.d"
    conf.mkdir(parents=True)
    (conf / "sd.conf").write_text('[Installation "sdcard"]\nPath=/run/media/sd/flatpak\n')
    assert ii.flatpak_installations(str(tmp_path)) == [("sdcard", "/run/media/sd/flatpak")]
    assert ii.flatpak_dir("sdcard", root=str(tmp_path)) == str(tmp_path) + "/run/media/sd/flatpak"


def test_dots_for_what_changed_since_the_check_go(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("HOME", str(tmp_path))
    d = tmp_path / ".local/share/flatpak/app/org.gimp.GIMP/x86_64/stable"
    d.mkdir(parents=True)
    os.symlink("2222222222222222", d / "active")
    info = {"gimp": {"flatpak": "org.gimp.GIMP", "scope": "user", "arch": "x86_64", "branch": "stable",
                     "commit": "111111111111"},
            "foo": {"version": "2", "file": "Foo-1.AppImage"},
            "bar": {"version": "3", "file": "Bar-1.AppImage"}}
    execs = {"foo": "/apps/Foo-2.AppImage", "bar": "/apps/Bar-1.AppImage"}
    newer, kept = au.still_waiting(["gimp", "foo", "bar"], info, execs, str(tmp_path))
    assert newer == ["bar"] and list(kept) == ["bar"]


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
