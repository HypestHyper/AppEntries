import os

from app_entries import cli_tools


def test_finds_tools_by_how_they_were_installed(tmp_path):
    home = tmp_path
    env = {"HOME": str(home)}
    lbin = home / ".local/bin"
    lbin.mkdir(parents=True)
    # pipx, installed from GitHub
    venv = home / ".local/share/pipx/venvs/black"
    info = venv / "lib/python3.12/site-packages/black-24.1.dist-info"
    info.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (info / "METADATA").write_text("Name: black\nVersion: 24.1\n\n")
    (info / "direct_url.json").write_text('{"url": "https://github.com/psf/black.git", "vcs_info": {}}')
    (venv / "bin").mkdir()
    (venv / "bin" / "black").write_text("#!/bin/sh\n")
    os.symlink(venv / "bin" / "black", lbin / "black")
    # cargo
    (home / ".cargo/bin").mkdir(parents=True)
    (home / ".cargo/bin/rg").write_bytes(b"x" * 10)
    (home / ".cargo/.crates2.json").write_text(
        '{"installs": {"ripgrep 14.1.0 (registry+https://github.com/rust-lang/crates.io-index)": {"bins": ["rg"]}, '
        '"zellij 0.41.0 (git+https://github.com/zellij-org/zellij?branch=main#abc)": {"bins": ["zellij"]}}}')
    # go, with the build information Go writes into programs
    (home / "go/bin").mkdir(parents=True)
    (home / "go/bin/lazygit").write_bytes(b"\x7fELF...path\tgithub.com/jesseduffield/lazygit\nmod\t"
                                         b"github.com/jesseduffield/lazygit\tv0.44.1\th1:x=\n...")
    # npm
    pkg = home / ".npm-global/lib/node_modules/prettier"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name": "prettier", "version": "3.3.0", "bin": {"prettier": "bin.js"}, '
                                      '"repository": {"url": "git+https://github.com/prettier/prettier.git"}}')
    # a file put there by hand, and App Entries' own command, which isn't listed
    (lbin / "backup").write_text("#!/bin/sh\n")
    (lbin / "io.github.HypestHyper.AppEntries").write_text("#!/bin/sh\n")

    tools = {t.name: t for t in cli_tools.scan(env)}
    assert set(tools) == {"black", "ripgrep", "zellij", "lazygit", "prettier", "backup"}
    b = tools["black"]
    assert (b.kind, b.version, b.github, b.commands) == ("pipx", "24.1", "psf/black", ["black"])
    assert b.update == [["pipx", "upgrade", "black"]] and b.remove == [["pipx", "uninstall", "black"]]
    rg = tools["ripgrep"]
    assert (rg.version, rg.commands, rg.size, rg.github) == ("14.1.0", ["rg"], 10, "")
    assert tools["zellij"].update == [["cargo", "install", "--git", "https://github.com/zellij-org/zellij", "zellij"]]
    lg = tools["lazygit"]
    assert (lg.version, lg.github, lg.update) == ("v0.44.1", "jesseduffield/lazygit",
                                                   [["go", "install", "github.com/jesseduffield/lazygit@latest"]])
    assert lg.trash == [str(home / "go/bin/lazygit")]
    pr = tools["prettier"]
    assert (pr.version, pr.github) == ("3.3.0", "prettier/prettier")
    assert pr.remove == [["npm", "uninstall", "-g", "prettier"]]
    assert tools["backup"].kind == "file" and tools["backup"].trash == [str(lbin / "backup")]
    assert [k for k, _items in cli_tools.by_kind(list(tools.values()))] == ["cargo", "go", "pipx", "npm", "file"]


def test_commands_of_apps_with_a_menu_entry_are_left_out(tmp_path):
    from app_entries import desktop_entries as de
    lbin = tmp_path / ".local/bin"
    lbin.mkdir(parents=True)
    (lbin / "iridia-gui").write_text("#!/bin/sh\n")
    (lbin / "iridia-gui").chmod(0o755)
    (lbin / "other").write_text("#!/bin/sh\n")
    app = de.App(id="iridia.desktop", name="Iridia", exec=str(lbin / "iridia-gui"))
    assert [t.name for t in cli_tools.scan({"HOME": str(tmp_path)}, [app])] == ["other"]


def _run(answers):
    def run(argv):
        for key, out in answers.items():
            if tuple(argv[:len(key)]) == key:
                return (0, out)
        return (1, "")
    return run


def test_terminal_programs_you_installed_with_pacman():
    from app_entries import desktop_entries as de
    from app_entries import pkgmanagers as pm
    run = _run({
        ("pacman", "-Qqe"): "ripgrep\ngimp\nbase\nlibfoo\nbtop\n",
        ("pacman", "-Ql"): "ripgrep /usr/bin/rg\nripgrep /usr/share/man/man1/rg.1.gz\n"
                           "gimp /usr/bin/gimp\ngimp /usr/share/applications/gimp.desktop\n"
                           "libfoo /usr/lib/libfoo.so\nbtop /usr/bin/btop\nbtop /usr/share/btop/\n",
        ("pacman", "-Qqm"): "btop\n",
        ("pacman", "-Qi"): "Name : ripgrep\nVersion : 14.1-1\nInstalled Size : 4.00 MiB\n\n"
                           "Name : btop\nVersion : 1.4-1\nInstalled Size : 2.00 MiB\n",
    })
    m = pm.Pacman(run, lambda t: "/usr/bin/" + t)
    tools = {t.name: t for t in cli_tools._packages([m], [])}
    # gimp has a menu entry (it's in the app list), base the system needs, libfoo adds no command.
    assert set(tools) == {"ripgrep", "btop"}
    rg = tools["ripgrep"]
    assert (rg.kind, rg.version, rg.commands, rg.size, rg.needs_password) == ("pacman", "14.1-1", ["rg"],
                                                                              4 * 1024 * 1024, True)
    assert rg.remove == [["sudo", "pacman", "-Rs", "ripgrep"]] and rg.update == []
    # An app with a menu entry the user made for it doesn't count as a terminal program either.
    btop_entry = de.App(id="btop.desktop", name="btop", source_path="/usr/bin/btop")
    assert "btop" not in {t.name for t in cli_tools._packages([m], [btop_entry])}


def test_apt_reads_dpkg_once_and_leaves_the_base_system_out(tmp_path, monkeypatch):
    from app_entries import pkgmanagers as pm
    info = tmp_path / "info"
    info.mkdir()
    (info / "ripgrep.list").write_text("/usr\n/usr/bin\n/usr/bin/rg\n")
    (info / "adduser.list").write_text("/usr/sbin/adduser\n")
    (info / "tmux.list").write_text("/usr/bin/tmux\n")
    status = tmp_path / "status"
    status.write_text("Package: ripgrep\nStatus: install ok installed\nPriority: optional\nVersion: 14.1\n"
                      "Installed-Size: 4000\n\nPackage: adduser\nStatus: install ok installed\nPriority: important\n"
                      "Version: 3\n\nPackage: tmux\nStatus: install ok installed\nPriority: optional\nVersion: 3.4\n")
    m = pm.Apt(_run({("apt-mark", "showmanual"): "ripgrep\nadduser\ntmux\n"}), lambda t: "/usr/bin/" + t)
    monkeypatch.setattr(m, "files_many", lambda pkgs: pm.Apt.files_many(m, pkgs, str(info)))
    m._status_cache = None
    real_status = pm.Apt._status
    monkeypatch.setattr(m, "_status", lambda: real_status(m, str(status)))
    tools = {t.name: t for t in cli_tools._packages([m], [])}
    assert set(tools) == {"ripgrep", "tmux"}          # adduser: part of Ubuntu's base system
    assert (tools["ripgrep"].version, tools["ripgrep"].size, tools["ripgrep"].commands) == ("14.1", 4000 * 1024, ["rg"])
    assert tools["ripgrep"].remove == [["sudo", "apt", "remove", "ripgrep"]]


def test_what_each_package_manager_says_you_installed(tmp_path):
    from app_entries import pkgmanagers as pm
    which = lambda t: "/usr/bin/" + t  # noqa: E731
    assert pm.Dnf(_run({("dnf", "repoquery"): "htop\nripgrep\n"}), which).user_installed() == ["htop", "ripgrep"]
    zyp = "S  | Name    | Summary | Type\n---+---------+---------+--------\ni+ | htop    | top     | package\n" \
          "i  | libfoo  | lib     | package\n"
    assert pm.Zypper(_run({("zypper",): zyp}), which).user_installed() == ["htop"]
    ostree = '{"deployments": [{"requested-packages": ["htop"], "requested-local-packages": ["tool"]}]}'
    assert pm.RpmOstree(_run({("rpm-ostree", "status"): ostree}), which).user_installed() == ["htop", "tool"]
    assert pm.Xbps(_run({("xbps-query", "-m"): "htop-3.3.0_1\nripgrep-14.1.0_1\n"}), which).user_installed() == \
        ["htop", "ripgrep"]
    world = tmp_path / "world"
    world.write_text("alpine-base\nhtop>3\nripgrep@edge\n")
    assert pm.Apk(_run({}), which).user_installed(str(world)) == ["alpine-base", "htop", "ripgrep"]
    pw = tmp_path / "pworld"
    pw.write_text("app-misc/tmux\nsys-process/htop\n@selected\n")
    assert pm.Portage(_run({}), which).user_installed(str(pw)) == ["app-misc/tmux", "sys-process/htop"]
    listing = "htop\t/usr/bin/htop\nhtop\t/usr/share/man/htop.1\ntmux\t/usr/bin/tmux\n"
    rpm = pm.Dnf(_run({("rpm", "-q", "--qf"): listing}), which)
    assert rpm.files_many(["htop", "tmux"]) == {"htop": ["/usr/bin/htop", "/usr/share/man/htop.1"],
                                                 "tmux": ["/usr/bin/tmux"]}
