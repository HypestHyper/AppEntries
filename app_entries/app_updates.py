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


def _flag(scope: str) -> str:
    return "--" + scope if scope in ("user", "system") else "--installation=" + scope


def _installations(root: str = "") -> list[str]:
    """Every Flatpak installation: the system's, the user's and any others
    (an SD card, say)."""
    return ["system", "user"] + [name for name, _p in install_info.flatpak_installations(root)]


def flatpak_scope_of(path: str, home: str = "") -> str:
    """The installation a Flatpak's launcher was exported from (its .desktop
    file's path), or ""."""
    real = os.path.realpath(path) if path else ""
    for scope in _installations():
        base = install_info.flatpak_dir(scope, home)
        if base and real.startswith(os.path.realpath(base) + os.sep):
            return scope
    return ""


def flatpak_commit(fid: str, scope: str, home: str = "", arch: str = "", branch: str = "") -> str:
    """The commit of the Flatpak installed now, read from its folder (no
    question to Flatpak, no internet), or "". The arch and branch the check
    found it on; without them, the one the app's `current` link names."""
    app_dir = os.path.join(install_info.flatpak_dir(scope, home), "app", fid)
    if not (arch and branch):
        try:
            arch, _s, branch = os.readlink(os.path.join(app_dir, "current")).partition("/")
        except OSError:
            return ""
    active = os.path.join(app_dir, arch, branch, "active")
    try:
        return os.path.basename(os.readlink(active))
    except OSError:
        return ""


def _rows(text: str) -> list[list[str]]:
    return [[c.strip() for c in line.split("\t")] for line in text.splitlines()
            if line.strip() and not line.startswith(("Application", "Application ID"))]


def _same_commit(a: str, b: str) -> bool:
    n = min(len(a), len(b))
    return n >= 8 and a[:n] == b[:n]


def _mask_hits(pattern: str, fid: str, arch: str, branch: str) -> bool:
    """Whether a `flatpak mask` pattern holds this app back. Patterns name an
    ID (globs allowed) and may add an arch and branch: org.foo.Bar,
    org.foo.*, org.foo.Bar//stable, app/org.foo.Bar/x86_64/stable."""
    p = pattern.strip()
    if p.startswith("runtime/"):
        return False
    p = p.removeprefix("app/")
    parts = p.split("/")
    for want, part in zip((fid, arch, branch), parts[:3]):
        if part and not fnmatch.fnmatchcase(want, part):
            return False
    return bool(parts[0])


def _waiting_in(scope: str, run) -> Optional[list[dict]]:
    """What has an update in one installation: [{id, arch, branch, commit}],
    or None if Flatpak couldn't say."""
    flag = _flag(scope)
    r = run(["flatpak", "remote-ls", flag, "--updates", "--app", "--columns=application,arch,branch,commit"])
    if r is None or r[0] != 0:
        return None
    installed = {}
    lr = run(["flatpak", "list", flag, "--app", "--columns=application,arch,branch,active"])
    if lr is not None and lr[0] == 0:
        installed = {tuple(row[:3]): row[3] for row in _rows(lr[1]) if len(row) >= 4}
    masked = []
    mr = run(["flatpak", "mask", flag])
    if mr is not None and mr[0] == 0:
        masked = [line.strip() for line in mr[1].splitlines() if line.strip()]
    out = []
    for row in _rows(r[1]):
        if len(row) < 3:
            continue
        ref, remote = tuple(row[:3]), (row[3] if len(row) > 3 else "")
        if ref not in installed or any(_mask_hits(m, *ref) for m in masked):
            continue
        if remote and _same_commit(remote, installed[ref]):
            continue        # listed, but what's installed is already that commit
        out.append({"id": ref[0], "arch": ref[1], "branch": ref[2], "commit": installed[ref]})
    return out


def flatpak_waiting(run=None, which=None, home: str = "", prefer: Optional[dict] = None) -> dict[str, dict]:
    """Flatpaks with an update waiting (Flatpak updates them, not the
    system's package manager): {app ID: {"scope", "arch", "branch",
    "commit"}}. Each installation (user, system and any others) is asked on
    its own, and an app only counts when the remote's commit differs from
    the installed one and it isn't held back with `flatpak mask`, so a dot
    always means `flatpak update` has something to do. An app in more than
    one installation: the one `prefer` names (where its launcher comes
    from), else the first found."""
    import shutil

    from . import pkgmanagers
    run = run or pkgmanagers.run
    prefer = prefer or {}
    if not (which or shutil.which)("flatpak"):
        return {}
    out: dict[str, dict] = {}
    for scope in _installations():
        for w in _waiting_in(scope, run) or []:
            fid = w["id"]
            if fid in out and (out[fid]["scope"] == prefer.get(fid) or scope != prefer.get(fid)):
                continue
            out[fid] = {"scope": scope, "arch": w["arch"], "branch": w["branch"], "commit": w["commit"]}
    return out


def flatpak_still_waiting(fid: str, scope: str, run=None, arch: str = "", branch: str = "") -> Optional[bool]:
    """Ask Flatpak again about one app (for its page). None if it couldn't say."""
    from . import pkgmanagers
    run = run or pkgmanagers.run
    found = _waiting_in(scope or "system", run)
    if found is None:
        return None
    return any(w["id"] == fid and (not arch or w["arch"] == arch) and (not branch or w["branch"] == branch)
               for w in found)


def flatpak_update_cmd(fid: str, scope: str, branch: str = "") -> list[str]:
    """`flatpak update` for just this app, in its installation and branch."""
    return ["flatpak", "update", _flag(scope or "system"), f"{fid}//{branch}" if branch else fid]


def still_waiting(newer: list, info: dict, execs: dict, home: str = "") -> tuple[list, dict]:
    """The saved dots, minus AppImages whose file has changed since the check
    (updated with Use a newer file, or outside App Entries) and Flatpaks
    updated since. `execs`: each app's command, by key. Only reads files;
    nothing goes online, so it can run in the background."""
    from . import appimages
    keep = []
    for key in newer:
        found = info.get(key)
        if isinstance(found, dict) and found.get("file") and key in execs:
            now = appimages.appimage_of(execs[key])
            if now and os.path.basename(now) != found["file"]:
                continue
        if isinstance(found, dict) and found.get("flatpak") and found.get("commit"):
            # Updated since the check (here, in a software centre or a terminal): the dot goes.
            now = flatpak_commit(found["flatpak"], found.get("scope", "system"), home,
                                 found.get("arch", ""), found.get("branch", ""))
            if now and not _same_commit(now, found["commit"]):
                continue
        keep.append(key)
    return keep, {k: v for k, v in info.items() if k in keep}
