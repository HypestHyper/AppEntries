"""Watching apps that come from GitHub for new versions: the ones the
system's package manager doesn't update (AppImages, apps linked to a
project, pip/pipx/uv apps, git copies and tools from cargo, go, pipx, uv and
npm). Pure Python, no GTK.

Checked at most once a day, reading only public release pages; a newer
version shows as a small dot on the app. Nothing is downloaded until the
user presses Update on its page."""
import fnmatch
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


def _flatpak_base(scope: str, home: str = "") -> str:
    home = home or os.path.expanduser("~")
    return os.path.join(home, ".local/share/flatpak") if scope == "user" else "/var/lib/flatpak"


def flatpak_commit(fid: str, scope: str, home: str = "") -> str:
    """The commit of the Flatpak installed now, read from its folder (no
    question to Flatpak, no internet), or ""."""
    app_dir = os.path.join(_flatpak_base(scope, home), "app", fid)
    try:
        arches = sorted(os.listdir(app_dir))
    except OSError:
        return ""
    for arch in arches:
        try:
            branches = sorted(os.listdir(os.path.join(app_dir, arch)))
        except OSError:
            continue
        for branch in branches:
            active = os.path.join(app_dir, arch, branch, "active")
            if os.path.islink(active):
                return os.path.basename(os.readlink(active))
    return ""


def _rows(text: str) -> list[list[str]]:
    return [[c.strip() for c in line.split("\t")] for line in text.splitlines()
            if line.strip() and not line.startswith(("Application", "Application ID"))]


def _same_commit(a: str, b: str) -> bool:
    n = min(len(a), len(b))
    return n >= 8 and a[:n] == b[:n]


def flatpak_waiting(run=None, which=None, home: str = "") -> dict[str, dict]:
    """Flatpaks with an update waiting (Flatpak updates them, not the
    system's package manager): {app ID: {"scope": "user" or "system",
    "commit": the installed commit}}. Asked of each installation on its
    own, and only counted when the remote's commit differs from the
    installed one and the app isn't held back with `flatpak mask`, so a dot
    always means `flatpak update` has something to do."""
    import shutil

    from . import pkgmanagers
    run = run or pkgmanagers.run
    if not (which or shutil.which)("flatpak"):
        return {}
    out: dict[str, dict] = {}
    for scope in ("system", "user"):
        flag = "--" + scope
        r = run(["flatpak", "remote-ls", flag, "--updates", "--app", "--columns=application,commit"])
        if r is None or r[0] != 0:
            continue
        installed = {}
        lr = run(["flatpak", "list", flag, "--app", "--columns=application,active"])
        if lr is not None and lr[0] == 0:
            installed = {row[0]: row[1] for row in _rows(lr[1]) if len(row) >= 2}
        masked = set()
        mr = run(["flatpak", "mask", flag])
        if mr is not None and mr[0] == 0:
            masked = {line.strip() for line in mr[1].splitlines() if line.strip()}
        for row in _rows(r[1]):
            fid, remote = row[0], (row[1] if len(row) > 1 else "")
            if fid not in installed or fid in out or any(fnmatch.fnmatchcase(fid, m) for m in masked):
                continue
            if remote and _same_commit(remote, installed[fid]):
                continue        # listed, but what's installed is already that commit
            out[fid] = {"scope": scope, "commit": installed[fid]}
    return out


def flatpak_still_waiting(fid: str, scope: str, run=None) -> Optional[bool]:
    """Ask Flatpak again about one app (for its page). None if it couldn't say."""
    from . import pkgmanagers
    run = run or pkgmanagers.run
    flag = "--" + (scope or "system")
    r = run(["flatpak", "remote-ls", flag, "--updates", "--app", "--columns=application,commit"])
    if r is None or r[0] != 0:
        return None
    lr = run(["flatpak", "list", flag, "--app", "--columns=application,active"])
    installed = {row[0]: row[1] for row in _rows(lr[1]) if len(row) >= 2} if lr and lr[0] == 0 else {}
    for row in _rows(r[1]):
        if row[0] == fid:
            remote = row[1] if len(row) > 1 else ""
            return not (remote and fid in installed and _same_commit(remote, installed[fid]))
    return False
