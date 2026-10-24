import os
import subprocess

import pytest

from conftest import entry
from app_entries import desktop_entries as de
from app_entries import health, history, overrides, pkgmanagers as pm, terminal, uninstall


def fake(answers):
    """A run() that answers from {"command words": (code, output)}, by the
    longest matching start of the command."""
    def run(argv):
        line = " ".join(argv)
        best = None
        for start, answer in answers.items():
            if line.startswith(start) and (best is None or len(start) > len(best)):
                best = start
        return answers[best] if best is not None else (1, "")
    return run


def which_only(*tools):
    return lambda t: "/usr/bin/" + t if t in tools else None


PACMAN_QI = """Name            : gimp
Version         : 2.10.38-1
Installed Size  : 112.34 MiB
Required By     : gimp-plugin-resynthesizer
Optional For    : darktable
"""


def test_pacman_says_what_needs_it_and_stops_until_told():
    run = fake({
        "pacman -Qi gimp": (0, PACMAN_QI),
        "pacman -Qqm gimp": (1, ""),
        "pacman -Rsp": (1, "error: failed to prepare transaction (could not satisfy dependencies)\n"
                           ":: removing gimp breaks dependency 'gimp' required by gimp-plugin-resynthesizer\n"),
        "pacman -Rscp": (0, "gimp\ngimp-plugin-resynthesizer\ngimp-help-en\n"),
    })
    m = pm.Pacman(run, which_only("pacman", "sudo"))
    info = m.info("gimp")
    assert info.version == "2.10.38-1" and info.size == int(112.34 * 1024 * 1024)
    p = m.preview(["gimp"], ["deps"])
    assert p.dependents == ["gimp-plugin-resynthesizer"] and p.optional_for == ["darktable"]
    assert "pacman would stop" in p.stops and not p.dependents_go
    p = m.preview(["gimp"], ["deps", "cascade"])
    assert p.exact and not p.stops and p.dependents_go
    assert p.removed == ["gimp", "gimp-plugin-resynthesizer", "gimp-help-en"] and p.unneeded == ["gimp-help-en"]
    assert m.commands(["gimp"], ["deps", "cascade"]) == [["sudo", "pacman", "-Rsc", "gimp"]]
    assert m.commands(["gimp"], ["nosave", "deps", "nodeps"]) == [["sudo", "pacman", "-Rnsdd", "gimp"]]
    assert not m.preview(["gimp"], ["nodeps"]).stops


def test_pacman_reinstalls_aur_packages_with_the_helper():
    m = pm.Pacman(fake({}), which_only("pacman", "sudo", "paru"))
    cmds = m.reinstall(["gimp", "zen-browser-bin"], {"zen-browser-bin": pm.Info("zen-browser-bin", foreign=True)})
    assert cmds == [["sudo", "pacman", "-S", "--needed", "gimp"], ["paru", "-S", "zen-browser-bin"]]


APT_SIM = """NOTE: This is only a simulation!
Reading package lists...
The following packages will be REMOVED:
  libreoffice-calc libreoffice-common libreoffice-writer ubuntu-desktop
Remv libreoffice-calc [4:24.2.7]
Remv libreoffice-writer [4:24.2.7]
Remv ubuntu-desktop [1.539]
Remv libreoffice-common [4:24.2.7]
"""


def test_apt_lists_what_goes_with_it_and_group_packages():
    run = fake({
        "apt-get -s remove": (0, APT_SIM),
        "apt-get -s --auto-remove remove": (0, APT_SIM + "Remv libabw-0.1-1 [0.1.3]\n"),
        "dpkg-query -W -f ${Version}\t${Installed-Size}\t${Essential}\t${Priority}\t${Section}\n ubuntu-desktop":
            (0, "1.539\t10\tno\toptional\tmetapackages\n"),
        "dpkg-query -W": (0, "4:24.2.7\t1000\tno\toptional\teditors\n"),
        "dpkg-query -S /usr/share/applications/libreoffice-startcenter.desktop":
            (0, "libreoffice-common: /usr/share/applications/libreoffice-startcenter.desktop\n"),
    })
    m = pm.Apt(run, which_only("dpkg-query", "sudo"))
    assert m.owner("/usr/share/applications/libreoffice-startcenter.desktop") == "libreoffice-common"
    p = m.preview(["libreoffice-common"], [])
    assert p.dependents == ["libreoffice-calc", "libreoffice-writer", "ubuntu-desktop"] and p.dependents_go
    assert p.group_packages == ["ubuntu-desktop"] and not p.stops
    p = m.preview(["libreoffice-common"], ["autoremove"])
    assert p.unneeded == ["libabw-0.1-1"] and "libabw-0.1-1" in p.removed
    assert m.commands(["x"], ["purge", "autoremove"]) == [["sudo", "apt", "remove", "--purge", "--autoremove", "x"]]
    assert m.commands(["x"], ["nodeps"]) == [["sudo", "dpkg", "--remove", "--force-depends", "x"]]


def test_apt_refuses_essential_packages():
    run = fake({
        "dpkg-query -W": (0, "5.2\t1900\tyes\trequired\tshells\n"),
        "apt-get -s remove": (0, "WARNING: The following essential packages will be removed.\n"
                                 "This should NOT be done unless you know exactly what you are doing!\n"
                                 "  bash\n"),
    })
    m = pm.Apt(run, which_only("dpkg-query"))
    assert "essential" in pm.blocked(m, ["bash"])
    assert "can't run without" in m.preview(["bash"], []).stops


DNF_TABLE = """Dependencies resolved.
================================================================================
 Package                Arch     Version          Repository    Size
================================================================================
Removing:
 gimp                   x86_64   2:2.10.38-1.fc40 @fedora       100 M
Removing dependent packages:
 gimp-resynthesizer     x86_64   2.0-1.fc40       @fedora       1 M
Removing unused dependencies:
 babl                   x86_64   0.1.108-1.fc40   @fedora       5 M

Transaction Summary
================================================================================
Remove  3 Packages

Operation aborted.
"""


def test_dnf_reads_its_transaction_table_and_rpm_dependents():
    run = fake({
        "rpm -e --test gimp": (1, "error: Failed dependencies:\n\tgimp = 2:2.10.38 is needed by (installed) "
                                  "gimp-resynthesizer-2.0-1.fc40.x86_64\n"),
        "dnf remove --assumeno": (1, DNF_TABLE),
    })
    m = pm.Dnf(run, which_only("dnf", "rpm", "sudo"))
    p = m.preview(["gimp"], ["deps"])
    assert p.dependents == ["gimp-resynthesizer"] and p.dependents_go and p.exact
    assert p.unneeded == ["babl"] and p.removed == ["gimp", "gimp-resynthesizer", "babl"]
    assert m.commands(["gimp"], []) == [["sudo", "dnf", "remove", "--setopt=clean_requirements_on_remove=False",
                                          "gimp"]]
    assert m.commands(["gimp"], ["nodeps"]) == [["sudo", "rpm", "-e", "--nodeps", "gimp"]]


def test_zypper_xbps_apk_eopkg_and_portage_answers_are_read():
    z = pm.Zypper(fake({"zypper --non-interactive --no-refresh remove --dry-run":
                        (0, "The following 2 packages are going to be REMOVED:\n  gimp libgimp\n")}),
                  which_only("zypper", "rpm", "sudo"))
    assert z.preview(["gimp"], ["deps"]).removed == ["gimp", "libgimp"]
    assert z.commands(["gimp"], ["deps"]) == [["sudo", "zypper", "remove", "--clean-deps", "gimp"]]

    x = pm.Xbps(fake({"xbps-query -o": (0, "gimp-2.10.38_1: /usr/share/applications/gimp.desktop (regular file)\n"),
                      "xbps-query -X gimp": (0, "gimp-plugin-x-1.0_1\n"),
                      "xbps-remove -n": (0, "gimp-2.10.38_1 remove x86_64\n")}), which_only("xbps-query"))
    assert x.owner("/usr/share/applications/gimp.desktop") == "gimp"
    p = x.preview(["gimp"], ["deps"])
    assert p.dependents == ["gimp-plugin-x"] and "xbps would stop" in p.stops
    assert not x.preview(["gimp"], ["force"]).stops

    a = pm.Apk(fake({"apk info --who-owns": (0, "/usr/share/applications/gimp.desktop is owned by gimp-2.10.38-r2\n"),
                     "apk info -r gimp": (0, "gimp-2.10.38-r2 is required by:\ngimp-plugin-x-1.0-r0\n"),
                     "apk del -s": (0, "World updated, but the following packages are not removed due to:\n"
                                       "  gimp: gimp-plugin-x\n")}), which_only("apk", "doas"))
    assert a.owner("/usr/share/applications/gimp.desktop") == "gimp"
    p = a.preview(["gimp"], [])
    assert p.dependents == ["gimp-plugin-x"] and "apk would keep it" in p.stops
    assert a.commands(["gimp"], ["rdepends"]) == [["doas", "apk", "del", "-r", "gimp"]]

    e = pm.Eopkg(fake({"eopkg search-file": (0, "Package gimp has file /usr/share/applications/gimp.desktop\n")}),
                 which_only("eopkg", "sudo"))
    assert e.owner("/usr/share/applications/gimp.desktop") == "gimp"

    g = pm.Portage(fake({"qfile -qC": (0, "media-gfx/gimp\n"),
                         "emerge --pretend --depclean": (0, "media-gfx/gimp-2.10 pulled in by:\n"
                                                            "    media-plugins/gimp-x-1.0 requires media-gfx/gimp\n")}),
                   which_only("emerge", "qfile", "sudo"))
    assert g.owner("/usr/share/applications/gimp.desktop") == "media-gfx/gimp"
    p = g.preview(["media-gfx/gimp"], [])
    assert p.dependents == ["media-plugins/gimp-x"] and "Portage would keep it" in p.stops
    assert g.commands(["media-gfx/gimp"], []) == [["sudo", "emerge", "--ask", "--deselect", "media-gfx/gimp"],
                                                   ["sudo", "emerge", "--ask", "--depclean", "media-gfx/gimp"]]


def test_core_packages_are_never_offered():
    m = pm.Pacman(fake({}), which_only("pacman"))
    assert "system needs it" in pm.blocked(m, ["systemd"])
    assert "desktop needs it" in pm.blocked(m, ["plasma-workspace"])
    assert "App Entries itself" in pm.blocked(m, ["gtk4"])
    assert "linux-image-6.8.0-45-generic" and pm.needed_by_system("linux-image-6.8.0-45-generic")
    assert pm.blocked(m, ["gimp"]) == ""


def test_nix_system_packages_point_to_the_configuration(tmp_path):
    n = pm.Nix(fake({}), which_only("nix-env"), home=str(tmp_path))
    assert n.owner("/run/current-system/sw/share/applications/gimp.desktop") == ""   # not in /nix here
    n._where["gimp"] = "system"
    assert "configuration" in n.blocked("gimp")
    assert n.commands(["hello"], []) == [["nix-env", "--uninstall", "hello"]]


def test_privilege_tool_and_su_fallback():
    assert pm.as_root(["apt", "remove", "x"], which_only("doas")) == ["doas", "apt", "remove", "x"]
    assert pm.as_root(["apt", "remove", "x y"], which_only()) == ["su", "-c", "apt remove 'x y'"]


# ---------------------------------------------------------------------------


def test_terminal_choice_and_script(tmp_path):
    assert terminal.find({"TERMINAL": "foot"}, which_only("foot", "kitty")) == ["foot"]
    assert terminal.find({"XDG_CURRENT_DESKTOP": "KDE"}, which_only("konsole", "xterm")) == ["/usr/bin/konsole", "-e"]
    assert terminal.find({}, which_only("xdg-terminal-exec", "konsole")) == ["/usr/bin/xdg-terminal-exec"]
    with pytest.raises(terminal.NoTerminal):
        terminal.find({}, which_only())

    result = str(tmp_path / "r")
    text = terminal.script("test", [["#", "a note"], ["true"], ["sh", "-c", "exit 3"], ["touch", str(tmp_path / "no")]],
                           result)
    out = subprocess.run(["sh", "-c", text], input="\n", capture_output=True, text=True)
    assert open(result).read().strip() == "3" and "a note" in out.stdout
    assert not (tmp_path / "no").exists()     # stops at the first that fails


def test_terminal_start_writes_a_script_and_the_job_reports(tmp_path):
    started = []
    env = {"XDG_RUNTIME_DIR": str(tmp_path), "TERMINAL": "kitty"}

    def popen(argv, **_kw):
        started.append(argv)
        subprocess.run(argv[1:], input="\n", capture_output=True, text=True)
        return subprocess.Popen(["true"])

    job = terminal.start("x", [["true"]], env, which_only("kitty"), popen)
    assert started[0][:2] == ["kitty", "/bin/sh"] and job.code() == 0
    job.clean()
    assert not os.path.exists(job.script)


# ---------------------------------------------------------------------------


def scan(env):
    apps = de.scan(env)
    for a in apps:
        a.source = health.source_of(a)
    return apps


def flatpak_setup(xdg, running=False, other_uses_runtime=False):
    exports = xdg.tmp / "home" / ".local" / "share" / "flatpak" / "exports" / "share" / "applications"
    xdg.write(exports, "com.example.Chat.desktop",
              entry("Chat", "/usr/bin/flatpak run --branch=stable com.example.Chat", **{"X-Flatpak": "com.example.Chat"}))
    env = dict(xdg.env, XDG_DATA_DIRS=str(exports.parent) + ":" + xdg.env["XDG_DATA_DIRS"])
    data = xdg.tmp / "home" / ".var" / "app" / "com.example.Chat"
    data.mkdir(parents=True)
    (data / "x").write_text("12345")
    rows = "com.example.Chat\tcom.example.Chat/x86_64/stable\torg.example.Platform/x86_64/24\n" \
           "org.example.Platform\torg.example.Platform/x86_64/24\t\n"
    if other_uses_runtime:
        rows += "org.other.App\torg.other.App/x86_64/stable\torg.example.Platform/x86_64/24\n"
    run = fake({
        "flatpak info --user com.example.Chat": (0, "Chat - talk\n\n          ID: com.example.Chat\n"
                                                    "     Version: 1.2\n      Origin: flathub\n"
                                                    "     Runtime: org.example.Platform/x86_64/24\n"
                                                    "   Installed: 1.2 GB\n"),
        "flatpak list --user": (0, rows),
        "flatpak ps": (0, "com.example.Chat\n" if running else ""),
    })
    return env, run


def test_flatpak_plan_options_and_commands(xdg):
    env, run = flatpak_setup(xdg)
    apps = scan(env)
    app = next(a for a in apps if a.id == "com.example.Chat.desktop")
    assert uninstall.kind_of(app) == "flatpak"
    p = uninstall.plan(app, apps, env, run, which_only("flatpak"), managers=[])
    assert p.target == "com.example.Chat" and p.size == 1200000000 and not p.in_terminal
    assert [o.key for o in p.also] == ["runtime", "data"] and p.defaults() == []
    assert p.folder_sizes["data"] == 5
    assert p.commands([]) == [["flatpak", "uninstall", "--user", "--noninteractive", "-y", "com.example.Chat"]]
    assert p.commands(["runtime", "force"])[0][-2:] == ["com.example.Chat", "org.example.Platform/x86_64/24"]
    assert "--force-remove" in p.commands(["force"])[0]
    assert p.reinstall([]) == [["flatpak", "install", "--user", "flathub", "com.example.Chat"]]
    assert uninstall.to_trash(p, ["data"]) == [str(xdg.tmp / "home" / ".var" / "app" / "com.example.Chat")]
    assert p.can_go([])


def test_flatpak_runtime_others_use_isnt_offered_and_running_apps_stop(xdg):
    env, run = flatpak_setup(xdg, running=True, other_uses_runtime=True)
    apps = scan(env)
    app = next(a for a in apps if a.id == "com.example.Chat.desktop")
    p = uninstall.plan(app, apps, env, run, which_only("flatpak"), managers=[])
    assert "runtime" not in [o.key for o in p.also]
    assert "is running" in p.stops and not p.can_go([])
    p.update(["force"])
    assert p.can_go(["force"]) and "closed straight away" in p.warnings["force"]


def test_package_plan_knows_what_goes_and_what_stops_working(xdg, tmp_path):
    xdg.write(xdg.sys_b, "gimp.desktop", entry("GIMP", "gimp-2.10 %U", MimeType="image/png;"))
    xdg.write(xdg.sys_b, "gimp-viewer.desktop", entry("GIMP Viewer", "gimp-viewer"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gimp-2.10").write_text("#!/bin/sh\n")
    os.chmod(bin_dir / "gimp-2.10", 0o755)
    xdg.write(xdg.user, "my-gimp.desktop", entry("My GIMP", str(bin_dir / "gimp-2.10") + " --no-splash"))
    cfg = xdg.tmp / "home" / ".config"
    (cfg / "GIMP").mkdir(parents=True)
    (cfg / "mimeapps.list").write_text("[Default Applications]\nimage/png=gimp.desktop\n")
    env = dict(xdg.env, PATH=str(bin_dir), XDG_CONFIG_HOME=str(cfg))
    apps = scan(env)
    gimp = next(a for a in apps if a.id == "gimp.desktop")
    path = gimp.base_path
    run = fake({
        "pacman -Qoq " + path: (0, "gimp\n"),
        "pacman -Qi gimp": (0, PACMAN_QI),
        "pacman -Qqm": (1, ""),
        "pacman -Qlq gimp": (0, "\n".join([path, str(xdg.sys_b / "gimp-viewer.desktop"),
                                            str(bin_dir / "gimp-2.10")]) + "\n"),
        "pacman -Rsp": (1, ":: removing gimp breaks dependency 'gimp' required by gimp-plugin-resynthesizer\n"),
    })
    managers = [pm.Pacman(run, which_only("pacman", "sudo"))]
    p = uninstall.plan(gimp, apps, env, run, which_only("pacman", "sudo"), managers)
    assert p.kind == "package" and p.target == "gimp" and p.in_terminal and p.password
    assert p.goes_too == ["GIMP Viewer"]
    assert p.stop_working == ["My GIMP"]
    assert any("default for pictures" in n for n in p.notes)
    assert "pacman would stop" in p.stops and not p.can_go(p.defaults())
    assert p.folders["data"] == [str(cfg / "GIMP")]
    assert p.commands(p.defaults()) == [["sudo", "pacman", "-Rs", "gimp"]]
    p.update(["deps", "nodeps"])
    assert "gimp-plugin-resynthesizer" in p.warnings["nodeps"]


def test_your_own_files_for_an_app_go_with_it_and_come_back(xdg):
    xdg.write(xdg.sys_b, "gimp.desktop", entry("GIMP", "gimp"))
    env = xdg.env
    apps = scan(env)
    overrides.apply(overrides.plan_set_hidden(apps[0], True, env))
    autostart_dir = xdg.tmp / "home" / ".config" / "autostart"
    autostart_dir.mkdir(parents=True)
    (autostart_dir / "gimp.desktop").write_text(entry("GIMP", "gimp", **{"X-AppEntries-Created": "true"}))
    env = dict(env, XDG_CONFIG_DIRS=str(xdg.tmp / "nothing"))
    apps = scan(env)
    p = uninstall.Plan(apps[0], "package", "Package", "gimp", app_ids=["gimp.desktop"])
    changes = uninstall.file_changes(p, apps, env)
    paths = sorted(os.path.basename(os.path.dirname(c.path)) for c in changes)
    assert paths == ["applications", "autostart"]
    overrides.apply_all(changes)
    assert not (autostart_dir / "gimp.desktop").exists()
    overrides.undo_all(changes)
    assert (autostart_dir / "gimp.desktop").exists()


def test_distrobox_entries_are_read():
    box, inner = uninstall._distrobox("/usr/bin/distrobox-enter -n arch -- gimp %U")
    assert box == "arch" and inner == ["gimp", "%U"]
    assert uninstall._distrobox("distrobox enter ubuntu -- code")[0] == "ubuntu"
    assert uninstall._distrobox("gimp")[0] == ""


def test_batch_uses_one_command_per_package_manager(xdg):
    for name in ("a", "b"):
        xdg.write(xdg.sys_b, name + ".desktop", entry(name.upper(), name))
    apps = scan(xdg.env)
    run = fake({"pacman -Qoq " + str(xdg.sys_b / "a.desktop"): (0, "pkg-a\n"),
                "pacman -Qoq " + str(xdg.sys_b / "b.desktop"): (0, "pkg-b\n"),
                "pacman -Rsp": (0, "")})
    b = uninstall.plan_batch(apps, apps, xdg.env, run, which_only("pacman", "sudo"))
    assert [p.target for p in b.plans] == ["pkg-a", "pkg-b"]
    here, term = b.commands({})
    assert here == [] and term == [["sudo", "pacman", "-Rs", "pkg-a", "pkg-b"]]


def test_history_keeps_the_reinstall_command(xdg):
    e = history.record("Uninstalled GIMP", [], [], xdg.env, reinstall=[["sudo", "pacman", "-S", "gimp"]])
    assert e is not None and not e.can_undo
    again = history.load(xdg.env)[0]
    assert again.reinstall == [["sudo", "pacman", "-S", "gimp"]]
    with pytest.raises(history.UndoError):
        history.undo(again.id, xdg.env)
