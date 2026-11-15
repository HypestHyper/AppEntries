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
