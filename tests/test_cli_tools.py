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
