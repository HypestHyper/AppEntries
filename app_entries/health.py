"""Spot problems in the app list: missing programs, leftover files,
duplicates and files hidden the old way. Only reports; nothing here changes
a file. Pure Python, no GTK.
"""
import os
import shlex
import shutil
from dataclasses import dataclass, field
from typing import Dict, List

from . import APP_ID, packages
from . import desktop_entries as de
from .overrides import is_minimal_managed, is_pristine

SOURCES = ("system", "flatpak", "snap", "appimage", "steam", "webapp", "user")


@dataclass
class Leftover:
    """A file in the user's folder for an app that's no longer installed."""
    id: str
    name: str
    path: str


@dataclass
class Report:
    legacy: List[de.App] = field(default_factory=list)       # hidden the old way
    leftovers: List[Leftover] = field(default_factory=list)
    missing: List[de.App] = field(default_factory=list)      # shown, but the program is gone
    duplicates: List[List[de.App]] = field(default_factory=list)
    owners: Dict[str, "packages.Owner"] = field(default_factory=dict)  # for `missing`, by app ID

    @property
    def count(self) -> int:
        return len(self.legacy) + len(self.leftovers) + len(self.missing) + len(self.duplicates)


def source_of(app: de.App) -> str:
    path = (app.base_path or app.source_path).replace(os.sep, "/")
    exec_line = app.exec.lower()
    if "/flatpak/exports/" in path or exec_line.split()[:2] in (["flatpak", "run"], ["/usr/bin/flatpak", "run"]):
        return "flatpak"
    if "/snapd/desktop/" in path or exec_line.startswith("/snap/bin/") or exec_line.startswith("snap run"):
        return "snap"
    if ".appimage" in exec_line:
        return "appimage"
    if app.created and " --app=" in " " + exec_line:
        return "webapp"
    if exec_line.startswith("steam steam://") or "steam://rungameid" in exec_line:
        return "steam"
    return "system" if app.system else "user"


def search_dirs(env) -> List[str]:
    """Where programs are looked for: PATH, plus the usual places a launcher's
    PATH may have and this process's may not."""
    home = env.get("HOME") or os.path.expanduser("~")
    extra = [os.path.join(home, ".local", "bin"), os.path.join(home, "bin"),
             "/usr/local/bin", "/usr/bin", "/bin", "/usr/local/sbin", "/usr/sbin", "/sbin",
             "/usr/games", "/usr/local/games",
             "/var/lib/flatpak/exports/bin", os.path.join(home, ".local", "share", "flatpak", "exports", "bin"),
             "/snap/bin", os.path.join(home, ".nix-profile", "bin"), "/run/current-system/sw/bin",
             "/nix/var/nix/profiles/default/bin"]
    return list(dict.fromkeys([p for p in (env.get("PATH") or "").split(":") if p] + extra))


# env options that take a value as the next word.
_ENV_ARG_OPTS = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}


def program_of(exec_line: str) -> str:
    """The program an Exec line runs, skipping `env [options] VAR=x` and
    leading VAR=x assignments."""
    try:
        parts = shlex.split(exec_line)
    except ValueError:
        parts = exec_line.split()
    if parts and os.path.basename(parts[0]) == "env":
        parts = parts[1:]
        while parts:
            p = parts[0]
            if p in _ENV_ARG_OPTS:
                parts = parts[2:]
            elif p.startswith("-") or ("=" in p and not p.startswith("/")):
                parts = parts[1:]
            else:
                break
    while parts and "=" in parts[0] and not parts[0].startswith("/"):
        parts = parts[1:]
    return parts[0] if parts else ""


def is_installed(program: str, env) -> bool:
    if not program or "$" in program or "%" in program:
        return True  # can't tell, so don't report it
    if os.path.isabs(program):
        return os.path.isfile(program) and os.access(program, os.X_OK)
    return shutil.which(program, path=":".join(search_dirs(env))) is not None


def missing_program(app: de.App, env=None) -> str:
    """The program this entry needs that isn't installed, or ""."""
    env = os.environ if env is None else env
    data = {}
    try:
        data = de.DesktopFile.load(app.source_path).group_dict()
    except OSError:
        pass
    try_exec = de.unescape(data.get("TryExec", "")).strip()
    if try_exec and not is_installed(try_exec, env):
        return try_exec
    program = program_of(app.exec)
    return "" if is_installed(program, env) else program


def is_customised(app: de.App) -> bool:
    """A system app whose user file is more than a hide file App Entries made."""
    if not (app.override_path and app.system):
        return False
    try:
        df = de.DesktopFile.load(app.override_path)
    except OSError:
        return False
    if not df.group_dict().get("Exec", "").strip():
        return False  # a bare file that only hides it
    return not is_pristine(df)


def find_leftovers(env=None) -> List[Leftover]:
    """Files in the user's folder that only change an app (hide it, or were
    made by App Entries) for an app that's no longer installed anywhere."""
    dirs = de.application_dirs(env)
    user_dir = os.path.normpath(de.user_apps_dir(env))
    others = set()
    for d in dirs:
        if d != user_dir:
            others |= set(de.scan_dir(d, False))
    out = []
    for did, entry in sorted(de.scan_dir(user_dir, True).items()):
        if did in others:
            continue
        data = entry.data
        managed = de.is_true(data.get(de.MANAGED_KEY))
        bare = not data.get("Exec", "").strip()
        if managed or (bare and de.is_true(data.get("Hidden"))):
            out.append(Leftover(did, de.unescape(data.get("Name", "")) or did, entry.path))
    return out


def find_duplicates(apps: List[de.App]) -> List[List[de.App]]:
    """Apps that share a name, at least two of them shown in launchers."""
    groups: Dict[str, List[de.App]] = {}
    for a in apps:
        if a.no_display and not a.has_override:
            continue
        groups.setdefault(a.name.strip().casefold(), []).append(a)
    return [g for _k, g in sorted(groups.items())
            if len(g) > 1 and sum(1 for a in g if not a.hidden) > 1]


def _first_word(name: str) -> str:
    words = name.casefold().split()
    return words[0] if words else ""


def find_related(apps: List[de.App]) -> None:
    """Set `related` on entries that belong to the same app but are in the
    opposite state, like a hidden service entry next to a shown indicator."""
    groups: Dict[tuple, List[de.App]] = {}
    for a in apps:
        key = (a.icon, _first_word(a.name))
        if a.icon and key[1]:
            groups.setdefault(key, []).append(a)
    for group in groups.values():
        if len(group) < 2:
            continue
        for a in group:
            a.related = tuple(o.name for o in group if o is not a and o.hidden != a.hidden)


def legacy_hidden(apps: List[de.App]) -> List[de.App]:
    out = []
    for a in apps:
        if not (a.override_path and a.base_path and a.hidden):
            continue
        try:
            if is_minimal_managed(de.DesktopFile.load(a.override_path)):
                out.append(a)
        except OSError:
            continue
    return out


def check(apps: List[de.App], env=None) -> Report:
    """Fill in each app's `source` and `missing`, and build the report."""
    for a in apps:
        a.source = source_of(a)
        a.missing = missing_program(a, env)
        a.customised = is_customised(a)
    find_related(apps)
    return Report(
        legacy=legacy_hidden(apps),
        leftovers=find_leftovers(env),
        # App Entries never offers to hide itself.
        missing=[a for a in apps if a.missing and not a.hidden and a.id != APP_ID + ".desktop"],
        duplicates=find_duplicates(apps),
    )


def scan_and_check(env=None):
    apps = de.scan(env)
    report = check(apps, env)
    report.owners = packages.owners(report.missing)
    return apps, report

