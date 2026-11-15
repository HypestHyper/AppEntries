from app_entries import terminal


def test_run_opens_the_terminal_with_just_the_program():
    seen = {}
    terminal.run(["sh", "-c", "echo hi; read _", "sh"], env={"TERMINAL": "foot"},
                 which=lambda n: "/usr/bin/" + n if n == "foot" else None,
                 popen=lambda argv, **kw: seen.setdefault("argv", argv))
    assert seen["argv"] == ["foot", "sh", "-c", "echo hi; read _", "sh"]


def test_the_window_waits_for_enter_instead_of_starting_your_shell(tmp_path):
    """Your shell's startup (fastfetch in its config, say) would print over
    what the commands said."""
    import subprocess
    started = []
    terminal.start([["echo", "hi"]], {"TERMINAL": "kitty"}, lambda t: "/usr/bin/" + t,
                   lambda argv, **kw: started.append(argv))
    script = started[0][-1]
    assert "SHELL" not in script and script.endswith("read -r _")
    out = subprocess.run(["/bin/sh", "-c", script], input="\n", capture_output=True, text=True).stdout
    assert out == "hi\n\nPress Enter to close this window."
