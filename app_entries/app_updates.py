"""Watching apps that come from GitHub for new versions: the ones the
system's package manager doesn't update (AppImages, apps linked to a
project, pip/pipx/uv apps, git copies and tools from cargo, go, pipx, uv and
npm). Pure Python, no GTK.

Checked at most once a day, reading only public release pages; a newer
version shows as a small dot on the app. Nothing is downloaded until the
user presses Update on its page."""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import cli_tools, github_apps, install_info, uninstall

DAY = 24 * 3600


@dataclass
class Candidate:
    key: str                         # stable: the app ID, "pkg:<name>" or "tool:<name>"
    name: str
    src: github_apps.Source
    version: str = ""
    kind: str = ""                   # appimage, command, package, aur or tool
    app: object = None               # the de.App, if it has a menu entry
    details: Optional[install_info.Details] = None
    tool: Optional[cli_tools.Tool] = None
    manager: str = ""                # for packages: apt, dnf, zypper or pacman
    update_cmd: list = field(default_factory=list)
    result: Optional[github_apps.Check] = None
    error: str = ""


def _state_path(env=None) -> str:
    return os.path.join(os.path.dirname(github_apps._links_path(env)), "app-updates.json")


def load_state(env=None) -> dict:
    try:
        with open(_state_path(env), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(checked: float, newer: list[str], env=None, info: Optional[dict] = None) -> None:
    """When it last looked, what has an update, and for each a few words
    (the new version) for the dot's tooltip."""
    p = _state_path(env)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"checked": checked, "newer": sorted(newer), "info": info or {}}, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


def due(env=None, now=None) -> bool:
    """The daily check hasn't run for a day."""
    now = time.time() if now is None else now
    return now - float(load_state(env).get("checked", 0) or 0) >= DAY


# ---------------------------------------------------------------------------
# what can be updated from GitHub


def _apps(apps) -> list[Candidate]:
    out = []
    for a in apps:
        kind = uninstall.kind_of(a)
        if kind not in ("appimage", "python", "folder") and not a.created:
            continue
        d = install_info.summary(a)
        src = github_apps.source_of(a.id, d.raw.get("update_info", ""), d.origin,
                                    project=d.project or d.homepage, how=d.installer or "homepage")
        if src is None:
            continue
        c = Candidate(a.id, a.name, src, d.version, app=a, details=d)
        if d.kind == "appimage":
            c.kind = "appimage"
        elif d.update_cmd:
            c.kind, c.update_cmd = "command", d.update_cmd
        else:
            continue        # nothing App Entries can update it with
        out.append(c)
    return out


def _tools(apps) -> list[Candidate]:
    out = []
    for t in cli_tools.scan(apps=apps):
        if t.github and t.update:
            owner, _s, repo = t.github.partition("/")
            out.append(Candidate("tool:" + t.name, t.name, github_apps.Source(owner, repo, how="tool"), t.version,
                                 kind="tool", tool=t, update_cmd=t.update))
    return out


def gather(apps) -> list[Candidate]:
    """Everything with a GitHub project that the system's package manager
    doesn't update: AppImages, apps you linked, pip/pipx/uv apps and git
    copies, and tools from cargo, go, pipx, uv and npm. Only reads local
    files; nothing goes online."""
    seen, out = set(), []
    for c in _apps(apps) + _tools(apps):
        if c.key not in seen:
            seen.add(c.key)
            out.append(c)
    return sorted(out, key=lambda c: c.name.lower())


def check(c: Candidate, get: Optional[Callable] = None) -> Candidate:
    """Ask GitHub about one; fills in c.result or c.error."""
    kw = {"get": get} if get else {}
    try:
        if c.kind == "appimage":
            c.result = github_apps.check(c.key, c.details.path, c.src, **kw)
        else:
            c.result = github_apps.check_version(c.src, c.version, c.manager if c.kind == "package" else "", **kw)
        c.error = ""
    except github_apps.GitHubError as e:
        c.result, c.error = None, str(e)
    return c


def flatpak_waiting(run=None, which=None) -> set[str]:
    """IDs of Flatpaks with an update waiting (Flatpak updates them, not
    the system's package manager). One question to Flatpak, which asks its
    remotes."""
    import shutil

    from . import pkgmanagers
    run = run or pkgmanagers.run
    if not (which or shutil.which)("flatpak"):
        return set()
    r = run(["flatpak", "remote-ls", "--updates", "--app", "--columns=application"])
    if r is None or r[0] != 0:
        return set()
    return {line.strip() for line in r[1].splitlines() if line.strip() and not line.startswith("Application")}
