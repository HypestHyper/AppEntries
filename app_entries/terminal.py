"""Open the user's own terminal app running a command, so a package
manager can ask for the password there and the user sees everything it
prints. The terminal handles it all, errors included; App Entries never
sees or asks for a password. Pure Python, no GTK.

Afterwards the terminal keeps a shell open, so nothing it printed is lost
when the command ends; the user closes it.
"""
import os
import shlex
import shutil
import subprocess
from typing import Callable, Dict, List

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


def line(commands: List[List[str]]) -> str:
    """The commands as one shell line, each running only if the one before
    worked. Notes (lines starting with #) aren't run."""
    return " && ".join(shlex.join(c) for c in commands if c and not c[0].startswith("#"))


def start(commands: List[List[str]], env=None, which: Callable = shutil.which,
          popen: Callable = subprocess.Popen) -> subprocess.Popen:
    """Open the terminal running the commands, then a shell. Raises
    NoTerminal when there's no terminal app, and OSError when it couldn't be
    started."""
    prefix = find(env, which)
    cmd = line(commands) + '; exec "${SHELL:-/bin/sh}"'
    return popen(prefix + ["/bin/sh", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True)


def shown(commands: List[List[str]]) -> str:
    """The commands as they'd be typed, one per line."""
    return "\n".join(" ".join(c) if c and c[0].startswith("#") else shlex.join(c) for c in commands)
