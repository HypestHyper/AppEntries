"""Updates for apps from GitHub, in one list, and how many system, Flatpak
and Snap updates are waiting. Pure Python, no GTK.

Nothing is asked online until the user checks (or turns on the daily
check). Updating is done the way each kind of app is updated: an AppImage
by App Entries (download, check, swap, with Undo), everything else by its
own command in the user's terminal."""
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import cli_tools, github_apps, install_info, pkgmanagers, uninstall

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


def save_state(checked: float, newer: list[str], env=None) -> None:
    p = _state_path(env)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"checked": checked, "newer": sorted(newer)}, f)
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


def _packages(run, which) -> list[Candidate]:
    """Packages not from the distribution whose home is a GitHub project:
    AUR packages (pacman) and package files installed by hand (apt)."""
    out = []
    if which("pacman"):
        r = run(["pacman", "-Qqm"])
        for pkg in (r[1].split() if r and r[0] == 0 else []):
            f = install_info._fields((run(["pacman", "-Qi", pkg]) or (1, ""))[1])
            src = github_apps.source_of("pkg:" + pkg, project=f.get("URL", ""), how="homepage")
            if src:
                out.append(Candidate("pkg:" + pkg, pkg, src, f.get("Version", ""), kind="aur", manager="pacman"))
    elif which("apt"):
        r = run(["apt", "list", "--installed"])
        local = [line.split("/", 1)[0] for line in (r[1].splitlines() if r and r[0] == 0 else [])
                 if "[installed,local]" in line]
        for pkg in local:
            r2 = run(["dpkg-query", "-W", "-f", "${Version}\t${Homepage}\n", pkg])
            version, _t, home = ((r2[1] if r2 and r2[0] == 0 else "") + "\t\t").split("\n")[0].partition("\t")
            src = github_apps.source_of("pkg:" + pkg, project=home.strip(), how="homepage")
            if src:
                out.append(Candidate("pkg:" + pkg, pkg, src, version, kind="package", manager="apt"))
    return out


def _tools(apps) -> list[Candidate]:
    out = []
    for t in cli_tools.scan(apps=apps):
        if t.github and t.update:
            owner, _s, repo = t.github.partition("/")
            out.append(Candidate("tool:" + t.name, t.name, github_apps.Source(owner, repo, how="tool"), t.version,
                                 kind="tool", tool=t, update_cmd=t.update))
    return out


def gather(apps, run=pkgmanagers.run, which=shutil.which) -> list[Candidate]:
    """Everything with a GitHub project App Entries can check. Only reads
    local files and asks the package manager; nothing goes online."""
    seen, out = set(), []
    for c in _apps(apps) + _packages(run, which) + _tools(apps):
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


# ---------------------------------------------------------------------------
# the system's own updates (read only)


@dataclass
class Waiting:
    source: str          # e.g. "pacman", "Flatpak", "Snap"
    count: int
    names: list[str]
    command: list        # what updates them, run in a terminal


def _lines(run, argv, none=(1, 2)) -> Optional[list[str]]:
    """Its output lines; [] for the exit codes that mean "nothing to update"
    (checkupdates gives 2, pacman -Qu 1; dnf check-update gives 100 when there
    are some); None if it couldn't say."""
    r = run(argv)
    if r is None:
        return None
    code, out = r
    if code in (0, 100):
        return [line for line in out.splitlines() if line.strip()]
    return [] if code in none else None


def system_updates(run=pkgmanagers.run, which=shutil.which) -> list[Waiting]:
    """How many updates each source has waiting. Uses what each manager
    already knows where it can (pacman's checkupdates and apt read lists
    that may be a few hours old); Flatpak and Snap ask their servers."""
    out = []
    helper = next((h for h in ("paru", "yay") if which(h)), "")
    if which("pacman"):
        lines = _lines(run, ["checkupdates"]) if which("checkupdates") else _lines(run, ["pacman", "-Qu"])
        if lines is not None:
            names = [line.split()[0] for line in lines]
            cmd = [helper, "-Syu"] if helper else pkgmanagers.as_root(["pacman", "-Syu"], which)
            out.append(Waiting("pacman", len(names), names, [cmd]))
    elif which("apt"):
        lines = _lines(run, ["apt", "list", "--upgradable"])
        if lines is not None:
            names = [line.split("/", 1)[0] for line in lines if "/" in line]
            out.append(Waiting("apt", len(names), names, [pkgmanagers.as_root(["apt", "update"], which),
                                                          pkgmanagers.as_root(["apt", "upgrade"], which)]))
    elif which("dnf"):
        lines = _lines(run, ["dnf", "check-update", "-q"])
        if lines is not None:
            names = [line.split()[0] for line in lines if len(line.split()) >= 3]
            out.append(Waiting("dnf", len(names), names, [pkgmanagers.as_root(["dnf", "upgrade"], which)]))
    elif which("zypper"):
        lines = _lines(run, ["zypper", "-q", "lu"])
        if lines is not None:
            names = [line.split("|")[2].strip() for line in lines if line.count("|") >= 4 and
                     not line.lstrip().startswith(("S ", "--"))]
            out.append(Waiting("zypper", len(names), names, [pkgmanagers.as_root(["zypper", "update"], which)]))
    if which("flatpak"):
        lines = _lines(run, ["flatpak", "remote-ls", "--updates", "--columns=application"])
        if lines is not None:
            names = [line.strip() for line in lines if not line.startswith("Application")]
            out.append(Waiting("Flatpak", len(names), names, [["flatpak", "update"]]))
    if which("snap"):
        lines = _lines(run, ["snap", "refresh", "--list"])
        if lines is not None:
            names = [line.split()[0] for line in lines[1:]] if lines and lines[0].startswith("Name") else []
            out.append(Waiting("Snap", len(names), names, [pkgmanagers.as_root(["snap", "refresh"], which)]))
    return out
