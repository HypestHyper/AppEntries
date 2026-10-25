import os
import subprocess

import pytest

from app_entries import desktop_entries as de
from app_entries import launchers as ln
from app_entries import overrides as ov
from app_entries import symbols


def make_script(folder, name="run me.sh"):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text('#!/bin/sh\nfor a in "$@"; do printf "[%s]\\n" "$a"; done\n')
    os.chmod(p, 0o755)
    return p


def launch(text, files=()):
    """Run an entry's Exec the way a launcher does: unescape the string,
    split it per the spec, substitute %F, run it."""
    d = de.DesktopFile(text).group_dict()
    argv = []
    for a in ln.parse_exec(de.unescape(d["Exec"])):
        if a == "%F":
            argv += list(files)
        else:
            argv.append(a)
    return subprocess.run(argv, capture_output=True, text=True, input="\n", timeout=10).stdout


def test_quote_arg():
    assert ln.quote_arg("plain") == "plain"
    assert ln.quote_arg("a b") == '"a b"'
    assert ln.quote_arg('say "hi" $HOME `x` \\') == '"say \\"hi\\" \\$HOME \\`x\\` \\\\"'
    assert ln.quote_arg("100%") == "100%%"


def test_script_with_awkward_path_and_args_runs_exactly(xdg):
    script = make_script(xdg.tmp / "My Scripts" / "it's \"here\" $now")
    spec = ln.Spec(name="Backup", program=str(script), args="--to '/mnt/My Disk' \"a\\\\b\" 50% $HOME",
                   accepts_files=True)
    did, changes = ln.plan_save(spec, env=xdg.env)
    ov.apply_all(changes)
    text = (xdg.user / did).read_text()
    out = launch(text, files=["/tmp/one file.txt"])
    assert out.splitlines() == ["[--to]", "[/mnt/My Disk]", "[a\\b]", "[50%]", "[$HOME]", "[/tmp/one file.txt]"]


def test_glib_parses_it_the_same_way(xdg):
    from gi.repository import GLib
    script = make_script(xdg.tmp / "dir with space")
    spec = ln.Spec(name="X", program=str(script), args="'one two' three")
    exec_line = ln.build_exec(spec)
    ok, argv = GLib.shell_parse_argv(exec_line.replace("%%", "%"))
    assert ok and argv == ln.parse_exec(exec_line) == [str(script), "one two", "three"]


def test_keep_open_waits_and_reports_status(xdg):
    script = make_script(xdg.tmp / "s")
    spec = ln.Spec(name="T", program=str(script), args="hello", terminal=True, keep_open=True, accepts_files=True)
    text = ln.build_entry(spec, "app-entries-t.desktop", xdg.env)
    out = launch(text, files=["f 1"])
    assert "[hello]\n[f 1]\n" in out and "Finished with exit code 0" in out


def test_entry_round_trips_to_spec_and_detects_hand_edits(xdg):
    spec = ln.Spec(name="Notes; draft", comment="Line\nbreak", program="~/bin/notes", args="-n",
                   workdir=str(xdg.tmp), categories=["Office"], keywords=["write", "a;b"],
                   icon=symbols.IconChoice("edit_note", "filled", "circle", "#6aa6ff"))
    text = ln.build_entry(spec, "app-entries-notes.desktop", xdg.env)
    back = ln.read_spec(text)
    assert back.program == "~/bin/notes" and back.args == "-n" and back.comment == "Line\nbreak"
    assert back.keywords == ["write", "a;b"] and back.icon == spec.icon and back.workdir == str(xdg.tmp)
    d = de.DesktopFile(text).group_dict()
    assert d["Exec"].startswith(os.path.expanduser("~/bin/notes"))   # ~ is expanded for launchers
    hand = text.replace("Exec=", "Exec=nice ")
    assert ln.read_spec(hand) is None


def test_plan_save_writes_icon_and_entry_and_ids_dont_clash(xdg):
    script = make_script(xdg.tmp / "s")
    spec = ln.Spec(name="My Tool", program=str(script))
    did, changes = ln.plan_save(spec, env=xdg.env)
    ov.apply_all(changes)
    assert did == "app-entries-my-tool.desktop"
    icon = ln.icon_path(did, xdg.env)
    assert os.path.isfile(icon) and "<svg" in open(icon).read()
    assert group_icon(xdg.user / did) == icon
    did2, _ = ln.plan_save(spec, env=xdg.env)
    assert did2 == "app-entries-my-tool-2.desktop"
    (app,) = [a for a in de.scan(xdg.env) if a.id == did]
    assert app.name == "My Tool" and app.created
    # Deleting removes the icon too, and undo brings both back.
    changes = ln.plan_delete(app, xdg.env)
    ov.apply_all(changes)
    assert not os.path.exists(icon) and not (xdg.user / did).exists()
    ov.undo_all(changes)
    assert os.path.exists(icon) and (xdg.user / did).exists()


def group_icon(path):
    return de.DesktopFile(path.read_text()).group_dict()["Icon"]


def test_editing_keeps_the_id_and_switching_to_a_theme_icon_drops_ours(xdg):
    script = make_script(xdg.tmp / "s")
    did, changes = ln.plan_save(ln.Spec(name="A", program=str(script)), env=xdg.env)
    ov.apply_all(changes)
    spec = ln.read_spec((xdg.user / did).read_text())
    spec.name, spec.icon_kind, spec.icon_value = "Renamed", "theme", "utilities-terminal"
    did2, changes = ln.plan_save(spec, did, env=xdg.env)
    ov.apply_all(changes)
    assert did2 == did and group_icon(xdg.user / did) == "utilities-terminal"
    assert not os.path.exists(ln.icon_path(did, xdg.env))


def test_problems(xdg):
    assert ln.problems(ln.Spec()) == ["Give the launcher a name.", "Choose the script or program it runs."]
    assert ln.problems(ln.Spec(name="x", program="y", args="'open")) == ["There's a quote without its closing quote."]
    assert ln.problems(ln.Spec(name="x", program="y", workdir=str(xdg.tmp / "nope"))) == \
        ["The working folder doesn't exist."]
    with pytest.raises(ValueError):
        ln.plan_save(ln.Spec(), env=xdg.env)


def test_program_status(xdg):
    script = make_script(xdg.tmp / "s")
    assert ln.program_status(str(script)) == "ok"
    os.chmod(script, 0o644)
    assert ln.program_status(str(script)) == "not-executable"
    ln.make_executable(str(script))
    assert ln.program_status(str(script)) == "ok"
    assert ln.program_status("sh") == "command"
    assert ln.program_status(str(xdg.tmp / "nothing")) == "missing"


def test_check_raw():
    good = "[Desktop Entry]\nType=Application\nName=X\nExec=x\n"
    assert ln.check_raw(good)[0] == []
    assert ln.check_raw("Name=X\n")[0] == ["The first section must be [Desktop Entry]."]
    errors, _ = ln.check_raw("[Desktop Entry]\nType=Link\nExec=\"open\n")
    assert "Type must be Application." in errors and "Name is missing." in errors
    assert any("quote" in e for e in errors)


def test_symbol_search_and_render():
    assert symbols.search("terminal")[0] == "terminal"
    assert "backup" in symbols.search("back up")
    svg = symbols.render(symbols.IconChoice("terminal", "outlined", "circle", "#ffffff"))
    assert svg.startswith("<svg") and "<circle" in svg and 'fill="#1b1b1f"' in svg  # dark glyph on light tile
    with pytest.raises(KeyError):
        symbols.render(symbols.IconChoice("not_an_icon"))


def test_program_field_can_hold_a_whole_command(xdg):
    assert ln.split_program("htop --help") == ("htop", "--help")
    assert ln.split_program("htop -d 10", "--tree") == ("htop", "-d 10 --tree")
    script = make_script(xdg.tmp / "dir", "with space.sh")
    assert ln.split_program(str(script)) == (str(script), "")     # an existing path is kept whole
    assert ln.program_status("sh -c true") == "command"
    spec = ln.Spec(name="Top", program="sh -c 'echo hi'")
    assert ln.parse_exec(ln.build_exec(spec)) == ["sh", "-c", "echo hi"]


def test_hidden_launcher_stays_hidden_when_saved_again(xdg):
    script = make_script(xdg.tmp / "s")
    did, changes = ln.plan_save(ln.Spec(name="H", program=str(script), hidden=True), env=xdg.env)
    ov.apply_all(changes)
    (app,) = [a for a in de.scan(xdg.env) if a.id == did]
    assert app.hidden
    spec = ln.read_spec((xdg.user / did).read_text())
    assert spec.hidden
    # Hiding from the card writes NoDisplay into the file; the form reads it back.
    did2, changes = ln.plan_save(ln.Spec(name="V", program=str(script)), env=xdg.env)
    ov.apply_all(changes)
    (v,) = [a for a in de.scan(xdg.env) if a.id == did2]
    ov.set_hidden(v, True, xdg.env)
    assert ln.read_spec((xdg.user / did2).read_text()).hidden


def test_every_icon_option_round_trips(xdg):
    ic = symbols.IconChoice("home", "filled", "circle", "#6aa6ff", source="material", border=True,
                            border_width=7, border_inner=True, border_color="white")
    spec = ln.Spec(name="X", program="sh", icon=ic)
    back = ln.read_spec(ln.build_entry(spec, "app-entries-x.desktop", xdg.env))
    assert back.icon == ic


def apply(changes):
    from app_entries import overrides
    overrides.apply_all(changes)


def test_commands_run_through_their_shell(xdg, tmp_path):
    out = tmp_path / "out"
    spec = ln.Spec(name="Update all", kind="commands", shell="sh",
                   commands=["echo one > %s && echo two >> %s\nfor x in a b; do echo $x >> %s; done" % (out, out, out)])
    assert ln.problems(spec) == []
    did, changes = ln.plan_save(spec, env=xdg.env)
    apply(changes)
    text = (xdg.user / did).read_text()
    exec_line = de.unescape(de.DesktopFile(text).group_dict()["Exec"])
    argv = ln.parse_exec(exec_line)
    assert argv[0] == "sh" and argv[1].endswith(".sh") and "app-entries/scripts" in argv[1]
    subprocess.run(argv, check=True)
    assert out.read_text().split() == ["one", "two", "a", "b"]
    again = ln.read_spec(text)
    assert again.kind == "commands" and again.commands == spec.commands and again.shell == "sh"


def test_several_commands_each_open_in_a_terminal(xdg, tmp_path):
    out = tmp_path / "out"
    spec = ln.Spec(name="Two", kind="commands", shell="sh", terminal=True,
                   commands=["echo first >> %s" % out, "echo second >> %s" % out])
    did, changes = ln.plan_save(spec, env=xdg.env)
    apply(changes)
    d = de.DesktopFile((xdg.user / did).read_text()).group_dict()
    assert d["Terminal"] == "false"   # the starter opens the terminals itself
    argv = ln.parse_exec(de.unescape(d["Exec"]))
    assert argv[0] == "sh" and argv[1].endswith("-start.sh")
    fake = tmp_path / "fake-term"
    fake.write_text('#!/bin/sh\n[ "$1" = "-e" ] && shift\nexec "$@"\n')
    os.chmod(fake, 0o755)
    subprocess.run(argv, check=True, env=dict(os.environ, TERMINAL=str(fake)), timeout=20)
    assert sorted(out.read_text().split()) == ["first", "second"]
    spec2 = ln.read_spec((xdg.user / did).read_text())
    assert spec2.commands == spec.commands and spec2.terminal

    # Back to one set: the second file and the starter go.
    spec2.commands = spec2.commands[:1]
    _did, changes = ln.plan_save(spec2, did, env=xdg.env)
    gone = [c.path for c in changes if c.after is None]
    assert any(p.endswith("-start.sh") for p in gone) and any(p.endswith("-2.sh") for p in gone)


def test_deleting_a_commands_launcher_takes_its_files(xdg):
    spec = ln.Spec(name="Gone", kind="commands", commands=["true", "true"])
    did, changes = ln.plan_save(spec, env=xdg.env)
    apply(changes)
    apps = {a.id: a for a in de.scan(xdg.env)}
    paths = [c.path for c in ln.plan_delete(apps[did], xdg.env)]
    assert len([p for p in paths if "/scripts/" in p]) == 3


def test_shell_syntax_in_a_program_line_is_caught():
    assert ln.uses_shell_syntax("paru -Syu && flatpak update")
    assert ln.uses_shell_syntax("ls | less")
    assert ln.uses_shell_syntax("echo $(date)")
    assert not ln.uses_shell_syntax("htop --tree")
    assert not ln.uses_shell_syntax("notify-send 'a && b'")
    p = ln.problems(ln.Spec(name="x", program="paru -Syu && flatpak update"))
    assert p and "Choose Commands" in p[0]
