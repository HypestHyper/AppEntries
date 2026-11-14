from app_entries import terminal


def test_run_opens_the_terminal_with_just_the_program():
    seen = {}
    terminal.run(["sh", "-c", "echo hi; read _", "sh"], env={"TERMINAL": "foot"},
                 which=lambda n: "/usr/bin/" + n if n == "foot" else None,
                 popen=lambda argv, **kw: seen.setdefault("argv", argv))
    assert seen["argv"] == ["foot", "sh", "-c", "echo hi; read _", "sh"]
