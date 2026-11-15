import gzip
import os
import shutil
import subprocess

import pytest

from app_entries import desktop_entries as de
from app_entries import install_info as ii


def fake(answers, calls=None):
    """run(argv) answering from {first words: output}."""
    def run(argv):
        if calls is not None:
            calls.append(argv)
        for key, out in answers.items():
            if len(argv) >= len(key) and all(a.startswith(k) for a, k in zip(argv, key)):
                return (0, out) if out is not None else (1, "")
        return (1, "")
    return run


def system(tmp_path, answers, tools, calls=None):
    ii._cache.clear()
    return ii.System(fake(answers, calls), lambda t: "/usr/bin/" + t if t in tools else None,
                     root=str(tmp_path / "root"), home=str(tmp_path / "home"))


def put(tmp_path, path, text="", mtime=None):
    p = tmp_path / "root" / path.lstrip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


ENTRY = "/usr/share/applications/gimp.desktop"
GIMP = de.App(id="gimp.desktop", name="GIMP", exec="gimp %U", base_path=ENTRY, source_path=ENTRY,
              system=True, source="system")

QI = """Name            : gimp
Version         : 2.10.38-2
Depends On      : babl  dbus-glib  gegl>=0.4.48  libmypaint
Optional Deps   : gutenprint: for sophisticated printing only as gimp has
                  built-in cups print support
                  ghostscript: for postscript support [installed]
Required By     : gimp-help
Installed Size  : 120.35 MiB
Install Date    : Mon Mar  3 10:00:00 2025
Install Reason  : Explicitly installed
"""


def test_pacman(tmp_path):
    put(tmp_path, "/var/lib/pacman/local/gimp-2.10.38-2/desc", "%NAME%\ngimp\n\n%INSTALLDATE%\n1741000000\n")
    s = system(tmp_path, {("pacman", "-Qoq"): "gimp\n", ("pacman", "-Qi"): QI, ("pacman", "-Qqm"): None},
               {"pacman"})
    d = ii.summary(GIMP, s)
    assert (d.kind, d.manager, d.package, d.version) == ("package", "pacman", "gimp", "2.10.38-2")
    assert d.repo == "distribution" and d.reason == "you" and d.date == 1741000000 and d.date_label == "installed"
    assert d.size == int(120.35 * 1024 * 1024) and d.by == ""      # pacman doesn't record who
    d = ii.dependencies(GIMP, s)
    assert [x.name for x in d.depends] == ["babl", "dbus-glib", "gegl", "libmypaint"]
    assert d.required_by == ["gimp-help"]
    assert [(x.name, x.installed) for x in d.optional] == [("gutenprint", False), ("ghostscript", True)]
    assert d.optional[0].why.startswith("for sophisticated printing")


def test_answers_are_remembered_until_the_database_changes(tmp_path):
    db = put(tmp_path, "/var/lib/pacman/local/ALPM_DB_VERSION", "9")
    calls = []
    s = system(tmp_path, {("pacman", "-Qoq"): "gimp\n", ("pacman", "-Qi"): QI}, {"pacman"}, calls)
    ii.summary(GIMP, s)
    n = len(calls)
    ii.summary(GIMP, s)
    assert len(calls) == n and ii.cached(GIMP, s) is not None
    os.utime(db.parent, (1, 1))       # something was installed or removed
    assert ii.cached(GIMP, s) is None
    ii.summary(GIMP, s)
    assert len(calls) > n


def test_apt_with_history(tmp_path):
    put(tmp_path, "/var/lib/apt/extended_states",
        "Package: libgimp2.0\nArchitecture: amd64\nAuto-Installed: 1\n\nPackage: gimp\nArchitecture: amd64\n"
        "Auto-Installed: 0\n")
    put(tmp_path, "/var/log/apt/history.log",
        "Start-Date: 2025-05-01  09:00:00\nCommandline: apt upgrade\nUpgrade: gimp:amd64 (2.10.36, 2.10.38)\n"
        "End-Date: 2025-05-01  09:01:00\n")
    old = tmp_path / "root/var/log/apt/history.log.1.gz"
    with gzip.open(old, "wt") as f:
        f.write("Start-Date: 2025-03-03  10:00:00\nCommandline: apt install gimp\nRequested-By: sam (1000)\n"
                "Install: gimp:amd64 (2.10.36), libgimp2.0:amd64 (2.10.36, automatic)\n"
                "End-Date: 2025-03-03  10:01:00\n")
    s = system(tmp_path, {
        ("dpkg-query", "-S"): "gimp: /usr/share/applications/gimp.desktop\n",
        ("dpkg-query", "-W", "-f", "${Version}"): "2.10.38-1\t90000\tamd64\tDebian\n",
        ("apt-cache", "policy"): "gimp:\n  Installed: 2.10.38-1\n  Version table:\n *** 2.10.38-1 500\n"
                                 "        500 http://deb.debian.org/debian trixie/main amd64 Packages\n"
                                 "        100 /var/lib/dpkg/status\n     2.10.36-1 400\n",
    }, {"dpkg-query"})
    put(tmp_path, "/var/lib/dpkg/status",
        "Package: gimp\nStatus: install ok installed\nDepends: libc6 (>= 2.34), libgtk2.0-0 | libgtk-3-0\n"
        "Recommends: gvfs\n\nPackage: libc6\nStatus: install ok installed\n\n"
        "Package: libgtk-3-0\nStatus: install ok installed\n\n"
        "Package: gimp-plugin-registry\nStatus: install ok installed\nDepends: gimp (>= 2.10)\n\n"
        "Package: gimp-data-extras\nStatus: install ok installed\nPre-Depends: foo | gimp:any\n\n"
        "Package: gimp-gone\nStatus: deinstall ok config-files\nDepends: gimp\n")
    d = ii.summary(GIMP, s)
    assert (d.manager, d.version, d.size, d.reason) == ("apt", "2.10.38-1", 90000 * 1024, "you")
    assert d.by == "sam" and d.date_label == "installed"
    assert d.date == ii._parse_date("2025-03-03 10:00:00")     # the first install, not the upgrade
    d = ii.dependencies(GIMP, s)
    assert [(x.name, x.installed) for x in d.depends] == [("libc6", True), ("libgtk2.0-0 or libgtk-3-0", True)]
    assert [(x.name, x.installed) for x in d.optional] == [("gvfs", False)]
    assert d.required_by == ["gimp-data-extras", "gimp-plugin-registry"]
    assert ii.origin(GIMP, s).repo == "deb.debian.org/debian (trixie/main)"


def test_apt_without_logs_says_the_date_is_approximate(tmp_path):
    put(tmp_path, "/var/lib/dpkg/info/gimp:amd64.list", "/usr/bin/gimp\n", mtime=1700000000)
    s = system(tmp_path, {("dpkg-query", "-S"): "gimp: /x\n",
                          ("dpkg-query", "-W", "-f", "${Version}"): "1\t1\tamd64\tx\n"}, {"dpkg-query"})
    d = ii.summary(GIMP, s)
    assert d.date == 1700000000 and d.date_label == "updated" and d.by == ""


def test_rpm(tmp_path):
    s = system(tmp_path, {
        ("rpm", "-qf"): "gimp\n",
        ("rpm", "-q", "--qf"): "2.10.38-1.fc41\t1741000000\t125000000\tFedora Project\n",
        ("rpm", "-q", "--requires"): "rpmlib(PayloadIsZstd) <= 5.4.18-1\nlibc.so.6()(64bit)\nbabl >= 0.1\n",
        ("rpm", "-q", "--whatprovides"): "glibc\nbabl\n",
        ("rpm", "-q", "--whatrequires"): "gimp-help\n",
    }, {"rpm", "dnf"})
    d = ii.summary(GIMP, s)
    assert (d.version, d.date, d.size, d.repo) == ("2.10.38-1.fc41", 1741000000, 125000000, "Fedora Project")
    d = ii.dependencies(GIMP, s)
    assert [x.name for x in d.depends] == ["glibc", "babl"] and d.required_by == ["gimp-help"]


def test_flatpak(tmp_path):
    app = de.App(id="org.gimp.GIMP.desktop", name="GIMP", exec="flatpak run org.gimp.GIMP", source="flatpak",
                 base_path="/var/lib/flatpak/exports/share/applications/org.gimp.GIMP.desktop")
    deploy = tmp_path / "home/.local/share/flatpak/app/org.gimp.GIMP/x86_64/stable/active/deploy"
    deploy.parent.mkdir(parents=True)
    deploy.write_text("")
    os.utime(deploy, (1730000000, 1730000000))
    s = system(tmp_path, {
        ("flatpak", "info"): "GIMP - GNU Image Manipulation Program\n\n          ID: org.gimp.GIMP\n"
                             "         Ref: app/org.gimp.GIMP/x86_64/stable\n     Version: 2.10.38\n"
                             "      Origin: flathub\nInstallation: user\n   Installed: 300.5\xa0MB\n"
                             "     Runtime: org.gnome.Platform/x86_64/46\n",
        ("flatpak", "list"): "org.gimp.GIMP\torg.gnome.Platform/x86_64/46\norg.gnome.Maps\t"
                             "org.gnome.Platform/x86_64/46\norg.kde.kate\torg.kde.Platform/x86_64/6.7\n",
    }, {"flatpak"})
    d = ii.summary(app, s)
    assert (d.kind, d.package, d.version, d.repo, d.scope) == ("flatpak", "org.gimp.GIMP", "2.10.38", "flathub",
                                                                  "user")
    assert d.size == int(300.5 * 1000 * 1000) or d.size > 300 * 1000 * 1000
    assert d.date == 1730000000 and d.date_label == "updated"
    d = ii.dependencies(app, s)
    assert d.depends[0].name == "org.gnome.Platform/x86_64/46" and d.shared_with == 1


def test_snap(tmp_path):
    app = de.App(id="firefox_firefox.desktop", name="Firefox", exec="/snap/bin/firefox %u", source="snap",
                 base_path="/var/lib/snapd/desktop/applications/firefox_firefox.desktop")
    put(tmp_path, "/var/lib/snapd/snaps/firefox_5000.snap", "x" * 10)
    put(tmp_path, "/snap/firefox/5000/meta/snap.yaml", "name: firefox\nbase: core22\n")
    put(tmp_path, "/snap/firefox/current/meta/snap.yaml", "name: firefox\nbase: core22\n")
    s = system(tmp_path, {("snap", "list"): "Name     Version  Rev   Tracking       Publisher   Notes\n"
                                            "firefox  133.0    5000  latest/stable  mozilla**   -\n"}, {"snap"})
    d = ii.summary(app, s)
    assert (d.version, d.repo, d.size, d.publisher) == ("133.0", "latest/stable", 10, "mozilla**".rstrip("*"))
    assert d.date and ii.dependencies(app, s).depends[0].name == "core22"


@pytest.mark.skipif(not shutil.which("objcopy"), reason="binutils isn't installed")
def test_appimage_from_github(tmp_path):
    info = tmp_path / "upd"
    info.write_bytes(b"gh-releases-zsync|owner|tool|latest|Tool-*x86_64.AppImage.zsync")
    img = tmp_path / "home" / "Applications" / "Tool.AppImage"
    img.parent.mkdir(parents=True)
    subprocess.run(["objcopy", "--add-section", f".upd_info={info}", "/bin/true", str(img)], check=True)
    assert ii.appimage_updates(str(img)) == "GitHub: owner/tool"
    try:
        os.setxattr(img, "user.xdg.origin.url", b"https://github.com/owner/tool/releases/download/v1/Tool.AppImage")
    except OSError:
        pytest.skip("this file system doesn't keep extended attributes")
    app = de.App(id="tool.desktop", name="Tool", exec=f"{img} %U", source="user", system=False)
    s = system(tmp_path, {}, set())
    d = ii.summary(app, s)
    assert (d.kind, d.path, d.scope) == ("appimage", str(img), "user")
    assert d.origin.startswith("https://github.com/owner/tool/") and d.updates_from == "GitHub: owner/tool"
    assert d.size == os.path.getsize(img) and d.date_label == "file"


def test_a_program_no_package_owns(tmp_path):
    prog = tmp_path / "opt" / "thing" / "thing"
    prog.parent.mkdir(parents=True)
    prog.write_text("#!/bin/sh\n")
    prog.chmod(0o755)
    app = de.App(id="thing.desktop", name="Thing", exec=f"{prog} --go", source="user", system=False)
    s = system(tmp_path, {}, {"pacman"})
    d = ii.summary(app, s)
    assert d.kind == "file" and d.path == str(prog) and d.origin == "" and d.updates_from == ""
    assert ii.github_of("https://github.com/a/b/releases") == "GitHub: a/b" and ii.github_of("https://x.org") == ""


def test_app_entries_itself(tmp_path):
    from app_entries import APP_ID, VERSION
    me = de.App(id=APP_ID + ".desktop", name="App Entries", exec="/home/x/.local/bin/" + APP_ID, source="user")
    d = ii.summary(me, system(tmp_path, {}, set()))
    assert d.kind == "self" and d.version == VERSION and d.size > 100_000     # the whole program, not its start script
    assert os.path.isdir(os.path.join(d.folder, "app_entries"))


def test_launchers_made_with_app_entries(tmp_path):
    profile = tmp_path / "profile"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Cookies").write_bytes(b"x" * 5000)
    web_file = tmp_path / "home" / "web.desktop"
    web_file.parent.mkdir(parents=True)
    web_file.write_text("[Desktop Entry]\n")
    browser = tmp_path / "usr" / "bin" / "chromium"
    browser.parent.mkdir(parents=True)
    browser.write_text("#!/bin/sh\n")
    web = de.App(id="web.desktop", name="Site", source="webapp", created=True, override_path=str(web_file),
                 exec=f"{browser} --app=https://example.org --user-data-dir={profile} --class=Site")
    s = system(tmp_path, {("pacman", "-Qoq"): "chromium\n", ("pacman", "-Qi"): "Name : chromium\nVersion : 131\n"},
               {"pacman"})
    d = ii.summary(web, s)
    assert (d.made, d.site, d.folder, d.data_size) == ("webapp", "https://example.org", str(profile), 5000)
    assert d.browser == "Chromium (pacman package chromium)" and d.made_date

    from app_entries import launchers
    spec = launchers.Spec(name="Update", kind="commands", commands=["paru -Syu"], shell="bash")
    cmd_file = tmp_path / "home" / "cmd.desktop"
    cmd_file.write_text(launchers.build_entry(spec, "cmd.desktop", {"HOME": str(tmp_path / "home")}))
    cmd = de.App(id="cmd.desktop", name="Update", source="user", created=True, override_path=str(cmd_file),
                 exec="sh -c true")
    d = ii.summary(cmd, s)
    assert d.made == "commands" and d.shell == "bash"


def test_a_start_script_is_followed_to_the_app_and_its_folder(tmp_path):
    app_dir = tmp_path / "Apps" / "Tool"
    (app_dir / "bin").mkdir(parents=True)
    (app_dir / "bin" / "tool").write_bytes(b"\x7fELF" + b"x" * 3000)
    (app_dir / "data.pak").write_bytes(b"x" * 7000)
    script = tmp_path / "home" / ".local" / "bin" / "tool"
    script.parent.mkdir(parents=True)
    script.write_text(f'#!/bin/sh\nexec "{app_dir}/bin/tool" "$@"\n')
    script.chmod(0o755)
    app = de.App(id="tool.desktop", name="Tool", exec=f"{script} %U", source="user", system=False)
    d = ii.summary(app, system(tmp_path, {}, set()))
    assert d.kind == "file" and d.folder == str(app_dir) and d.size == 3004 + 7000


def test_flatpak_runtime_size(tmp_path):
    app = de.App(id="org.gimp.GIMP.desktop", name="GIMP", exec="flatpak run org.gimp.GIMP", source="flatpak")
    s = system(tmp_path, {
        ("flatpak", "info", "org.gimp.GIMP"): "Ref: app/org.gimp.GIMP/x86_64/stable\n"
                                               "Runtime: org.gnome.Platform/x86_64/50\n",
        ("flatpak", "info", "org.gnome.Platform"): "     Ref: runtime/org.gnome.Platform/x86_64/50\n"
                                                    "Installed: 1.1\xa0GB\n",
    }, {"flatpak"})
    d = ii.dependencies(app, s)
    assert d.runtime == "org.gnome.Platform/x86_64/50" and d.runtime_size >= 1_000_000_000


def _venv(root, dist="iridia", version="0.4.2", direct_url=None, prog="iridia-gui"):
    (root / "bin").mkdir(parents=True)
    (root / "pyvenv.cfg").write_text("home = /usr/bin\n")
    info = root / "lib" / "python3.12" / "site-packages" / f"{dist}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n\nlong text\n")
    if direct_url:
        (info / "direct_url.json").write_text(direct_url)
    pip = root / "lib" / "python3.12" / "site-packages" / "pip-24.0.dist-info"
    pip.mkdir()
    (pip / "METADATA").write_text("Name: pip\nVersion: 24.0\n")
    script = root / "bin" / prog
    script.write_text(f"#!{root}/bin/python\nfrom iridia.gui import main\nmain()\n")
    script.chmod(0o755)
    return script


def test_a_python_app_installed_with_pip_from_github(tmp_path):
    home = tmp_path / "home"
    script = _venv(home / ".local/share/iridia/venv",
                   direct_url='{"url": "https://github.com/someone/iridia.git", "vcs_info": {"vcs": "git"}}')
    app = de.App(id="iridia.desktop", name="Iridia", exec=str(script), source="user", system=False)
    d = ii.summary(app, system(tmp_path, {}, set()))
    assert (d.kind, d.installer, d.package, d.version) == ("file", "pip", "iridia", "0.4.2")
    assert d.folder == str(home / ".local/share/iridia") and d.size > 100      # the app's folder, not the script
    assert d.project == "https://github.com/someone/iridia" and d.updates_from == "GitHub: someone/iridia"
    assert d.update_cmd == [[str(home / ".local/share/iridia/venv/bin/python"), "-m", "pip", "install", "--upgrade",
                             "git+https://github.com/someone/iridia"]]


def test_pipx_uv_and_git_checkouts(tmp_path):
    home = tmp_path / "home"
    s = system(tmp_path, {}, set())
    script = _venv(home / ".local/share/pipx/venvs/iridia")
    d = ii.summary(de.App(id="a.desktop", name="A", exec=str(script), source="user", system=False), s)
    assert d.installer == "pipx" and d.update_cmd == [["pipx", "upgrade", "iridia"]]
    script = _venv(home / ".local/share/uv/tools/tool", dist="tool", prog="tool")
    d = ii.summary(de.App(id="b.desktop", name="B", exec=str(script), source="user", system=False), s)
    assert d.installer == "uv" and d.update_cmd == [["uv", "tool", "upgrade", "tool"]]
    # A program run from a git copy of a project.
    repo = home / "src" / "thing"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_text('[core]\n\tbare = false\n[remote "origin"]\n'
                                          '\turl = git@github.com:me/thing.git\n')
    (repo / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (repo / "run.sh").chmod(0o755)
    d = ii.summary(de.App(id="c.desktop", name="C", exec=str(repo / "run.sh"), source="user", system=False), s)
    assert (d.installer, d.project) == ("git", "https://github.com/me/thing")
    assert d.update_cmd == [["git", "-C", str(repo), "pull"]]


def test_a_package_from_github_is_noticed_by_its_homepage(tmp_path):
    s = system(tmp_path, {("dpkg-query", "-S"): "tool: /x\n",
                          ("dpkg-query", "-W", "-f", "${Version}"): "1.2.0\t10\tamd64\thttps://github.com/o/tool\n"},
               {"dpkg-query"})
    d = ii.summary(GIMP, s)
    assert d.homepage == "https://github.com/o/tool"
    from app_entries import github_apps as gh
    src = gh.source_of("x", project=d.homepage, how="homepage")
    assert (src.name, src.how) == ("o/tool", "homepage")
    rel = {"tag_name": "v1.3.0", "assets": [
        {"name": "tool_1.3.0_amd64.deb", "browser_download_url": "https://x/a", "size": 3},
        {"name": "tool_1.3.0_arm64.deb", "browser_download_url": "https://x/b", "size": 3},
        {"name": "tool-1.3.0.x86_64.rpm", "browser_download_url": "https://x/c", "size": 3}]}
    c = gh.check_version(src, d.version, "apt", get=lambda url: rel, machine="x86_64")
    assert c.newer and c.current == "1.2.0" and c.asset.name == "tool_1.3.0_amd64.deb"
    assert gh.check_version(src, "1.3.0", "dnf", get=lambda url: rel, machine="x86_64").asset.name.endswith(".rpm")
    assert not gh.check_version(src, "1.3.0", "apt", get=lambda url: rel, machine="x86_64").newer
