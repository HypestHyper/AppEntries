"""Run commands in the user's own terminal app, so a package manager can
ask for the password there and the user sees everything it prints.
App Entries never sees or asks for a password. Pure Python, no GTK.

The commands are written to a small script that also records how they
ended, so App Entries can tell when they've finished.
"""
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from . import desktop_entries as de

# How each terminal is told to run a command: the words that go before it.
TERMINALS: Dict[str, List[str]] = {
    "xdg-terminal-exec": [],
    "kgx": ["--"], "ptyxis": ["--"], "gnome-terminal": ["--"], "konsole": ["-e"],
    "xfce4-terminal": ["-x"], "mate-terminal": ["-x"], "tilix": ["-e"], "terminator": ["-x"],
    "cosmic-term": ["-e"], "deepin-terminal": ["-e"], "qterminal": ["-e"], "lxterminal": ["-e"],
    "kitty": [], "foot": [], "alacritty": ["-e"], "ghostty": ["-e"], "wezterm": ["start", "--"],
    "rio": ["-e"], "terminology": ["-e"], "sakura": ["-x"], "urxvt": ["-e"], "st": ["-e"],
    "xterm": ["-e"],
}
# Tried first on these desktops: their own terminal.
_DESKTOP_FIRST = {"GNOME": ["kgx", "ptyxis", "gnome-terminal"], "KDE": ["konsole"], "XFCE": ["xfce4-terminal"],
                  "MATE": ["mate-terminal"], "X-CINNAMON": ["gnome-terminal"], "LXQT": ["qterminal"],
                  "LXDE": ["lxterminal"], "COSMIC": ["cosmic-term"], "DEEPIN": ["deepin-terminal"]}


class NoTerminal(Exception):
    pass


def find(env=None, which: Callable = shutil.which) -> List[str]:
    """The words that start a command in a terminal, like ["konsole", "-e"].
    $TERMINAL wins, then xdg-terminal-exec (the desktop's chosen one), then
    the desktop's own, then any known one."""
    env = os.environ if env is None else env
    chosen = (env.get("TERMINAL") or "").strip()
    if chosen:
        try:
            words = shlex.split(chosen)
        except ValueError:
            words = []
        if words and which(words[0]):
            name = os.path.basename(words[0])
            return words + (TERMINALS.get(name, ["-e"]) if len(words) == 1 else [])
    order = ["xdg-terminal-exec"]
    for d in de.current_desktops(env):
        order += _DESKTOP_FIRST.get(d.upper(), [])
    order += list(TERMINALS)
    for name in dict.fromkeys(order):
        path = which(name)
        if path:
            return [path] + TERMINALS[name]
    raise NoTerminal("No terminal app was found.")


def script(title: str, commands: List[List[str]], result: str) -> str:
    """A shell script that runs the commands one after another, stopping at
    the first that fails, and writes the exit code to `result`."""
    lines = ["#!/bin/sh", "# Written by App Entries for: %s. Safe to delete." % title.replace("\n", " "),
             "printf '%%s\\n\\n' %s" % shlex.quote("App Entries: " + title)]
    lines.append("status=0")
    for argv in commands:
        if argv and argv[0].startswith("#"):   # a note, not a command
            lines.append("printf '%%s\\n' %s" % shlex.quote(" ".join(argv)))
            continue
        cmd = shlex.join(argv)
        lines.append('if [ "$status" -eq 0 ]; then')
        lines.append("  printf '$ %%s\\n' %s" % shlex.quote(cmd))
        lines.append("  %s" % cmd)
        lines.append("  status=$?")
        lines.append("  echo")
        lines.append("fi")
    q = shlex.quote(result)
    lines += [
        "printf '%%s\\n' \"$status\" > %s.part && mv %s.part %s" % (q, q, q),
        'if [ "$status" -eq 0 ]; then',
        "  echo 'Finished. You can close this window.'",
        "else",
        "  echo \"It stopped with exit code $status. App Entries didn't change anything else.\"",
        "fi",
        "printf 'Press Enter to close. '",
        "read _ignored",
        "",
    ]
    return "\n".join(lines)


def _folder(env=None) -> str:
    env = os.environ if env is None else env
    runtime = env.get("XDG_RUNTIME_DIR") or ""
    if os.path.isabs(runtime) and os.path.isdir(runtime):
        return os.path.join(runtime, "app-entries")
    home = env.get("HOME") or os.path.expanduser("~")
    cache = env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(cache, "app-entries")


@dataclass
class Job:
    """Commands running in a terminal window."""
    script: str
    result: str
    process: Optional[subprocess.Popen] = None
    started: float = 0.0

    def code(self) -> Optional[int]:
        """The exit code once it has finished, None while it's running."""
        try:
            with open(self.result, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    def closed_early(self) -> bool:
        """The terminal went away without finishing. Only known for terminals
        that stay attached; ones that hand the window to a server return at
        once, so this is checked only after they had time to start."""
        if self.process is None or self.code() is not None:
            return False
        return self.process.poll() not in (None, 0) and time.time() - self.started > 2

    def clean(self) -> None:
        for p in (self.script, self.result):
            try:
                os.unlink(p)
            except OSError:
                pass


def start(title: str, commands: List[List[str]], env=None, which: Callable = shutil.which,
          popen: Callable = subprocess.Popen) -> Job:
    """Open the terminal running the commands. Raises NoTerminal when there's
    no terminal app, and OSError when it couldn't be started."""
    prefix = find(env, which)
    folder = _folder(env)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=folder, prefix="run-", suffix=".sh")
    result = path[:-3] + ".result"
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(script(title, commands, result))
    os.chmod(path, 0o700)
    proc = popen(prefix + ["/bin/sh", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True)
    return Job(path, result, proc, time.time())


def shown(commands: List[List[str]]) -> str:
    """The commands as they'd be typed, one per line."""
    return "\n".join(" ".join(c) if c and c[0].startswith("#") else shlex.join(c) for c in commands)
