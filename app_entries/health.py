"""Spot problems in the app list: missing programs, leftover files,
duplicates and files hidden the old way. Only reports; nothing here changes
a file. Pure Python, no GTK.
"""
import os
import shlex
import shutil
from dataclasses import dataclass, field

from . import APP_ID, packages
from . import desktop_entries as de
from .overrides import is_minimal_managed, is_pristine

SOURCES = ("system", "flatpak", "snap", "appimage", "steam", "distrobox", "webapp", "user")


@dataclass
class Leftover:
    """A file in the user's folder for an app that's no longer installed."""
    id: str
    name: str
    path: str
    hidden: bool = False   # kept out of menus (NoDisplay or Hidden)


@dataclass
class Report:
    legacy: list[de.App] = field(default_factory=list)       # hidden the old way
    leftovers: list[Leftover] = field(default_factory=list)
    # Your edited copies of apps that were uninstalled (not counted as leftovers).
    uninstalled: list[Leftover] = field(default_factory=list)
    # Copies App Entries hid that way, whose app is installed again.
    reinstalled: list[Leftover] = field(default_factory=list)
    missing: list[de.App] = field(default_factory=list)      # shown, but the program is gone
    duplicates: list[list[de.App]] = field(default_factory=list)
    owners: dict[str, "packages.Owner"] = field(default_factory=dict)  # for `missing`, by app ID

    @property
    def count(self) -> int:
        return (len(self.legacy) + len(self.leftovers) + len(self.uninstalled) + len(self.missing)
                + len(self.duplicates))


def source_of(app: de.App) -> str:
    path = (app.base_path or app.source_path).replace(os.sep, "/")
    exec_line = app.exec.lower()
    if "/flatpak/exports/" in path or exec_line.split()[:2] in (["flatpak", "run"], ["/usr/bin/flatpak", "run"]):
        return "flatpak"
    if "/snapd/desktop/" in path or exec_line.startswith(("/snap/bin/", "snap run")):
        return "snap"
    if ".appimage" in exec_line:
        return "appimage"
    if app.created and " --app=" in " " + exec_line:
        return "webapp"
    if exec_line.startswith("steam steam://") or "steam://rungameid" in exec_line:
        return "steam"
    if "distrobox-enter " in exec_line or "distrobox enter " in exec_line:
        return "distrobox"
    return "system" if app.system else "user"


def search_dirs(env) -> list[str]:
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


def _is_edited_copy(entry) -> bool:
    """A full copy of an app's entry made by App Entries and edited since
    (not a plain hide copy)."""
    data = entry.data
    if not de.is_true(data.get(de.MANAGED_KEY)) or not data.get("Exec", "").strip():
        return False
    from .overrides import is_pristine
    try:
        return not is_pristine(de.DesktopFile.load(entry.path))
    except OSError:
        return False


def find_uninstalled_edits(env=None) -> tuple[list[Leftover], list[Leftover]]:
    """(your edited copies of apps that are no longer installed, and copies
    App Entries hid for that reason whose app is installed again)."""
    user_dir = os.path.normpath(de.user_apps_dir(env))
    others = set()
    for d in de.application_dirs(env):
        if d != user_dir:
            others |= set(de.scan_dir(d, False))
    gone, back = [], []
    for did, entry in sorted(de.scan_dir(user_dir, True).items()):
        lo = Leftover(did, de.unescape(entry.data.get("Name", "")) or did, entry.path,
                      de.is_true(entry.data.get("NoDisplay")) or de.is_true(entry.data.get("Hidden")))
        if did in others:
            if de.is_true(entry.data.get(de.UNINSTALLED_KEY)):
                back.append(lo)
        elif _is_edited_copy(entry):
            gone.append(lo)
    return gone, back


def find_leftovers(env=None) -> list[Leftover]:
    """Files in the user's folder that only change an app (hide it, or were
    made by App Entries) for an app that's no longer installed anywhere.
    Edited copies are left to find_uninstalled_edits."""
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
        if (managed and not _is_edited_copy(entry)) or (bare and de.is_true(data.get("Hidden"))):
            out.append(Leftover(did, de.unescape(data.get("Name", "")) or did, entry.path))
    return out


def find_duplicates(apps: list[de.App]) -> list[list[de.App]]:
    """Apps that share a name, at least two of them shown in launchers."""
    groups: dict[str, list[de.App]] = {}
    for a in apps:
        if a.no_display and not a.has_override:
            continue
        groups.setdefault(a.name.strip().casefold(), []).append(a)
    return [g for _k, g in sorted(groups.items())
            if len(g) > 1 and sum(1 for a in g if not a.hidden) > 1]


def _first_word(name: str) -> str:
    words = name.casefold().split()
    return words[0] if words else ""


def find_related(apps: list[de.App]) -> None:
    """Set `related` on entries that belong to the same app but are in the
    opposite state, like a hidden service entry next to a shown indicator."""
    groups: dict[tuple, list[de.App]] = {}
    for a in apps:
        key = (a.icon, _first_word(a.name))
        if a.icon and key[1]:
            groups.setdefault(key, []).append(a)
    for group in groups.values():
        if len(group) < 2:
            continue
        for a in group:
            a.related = tuple(o.name for o in group if o is not a and o.hidden != a.hidden)


def legacy_hidden(apps: list[de.App]) -> list[de.App]:
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


def check(apps: list[de.App], env=None) -> Report:
    """Fill in each app's `source` and `missing`, and build the report."""
    for a in apps:
        a.source = source_of(a)
        a.missing = missing_program(a, env)
        a.customised = is_customised(a)
    find_related(apps)
    gone, back = find_uninstalled_edits(env)
    gone_ids = {lo.id for lo in gone}
    for a in apps:
        a.uninstalled = a.id in gone_ids
    return Report(
        legacy=legacy_hidden(apps),
        leftovers=find_leftovers(env),
        uninstalled=gone,
        reinstalled=back,
        # App Entries never offers to hide itself; uninstalled apps have their own section.
        missing=[a for a in apps if a.missing and not a.hidden and a.id != APP_ID + ".desktop"
                 and a.id not in gone_ids],
        duplicates=find_duplicates(apps),
    )


def scan_and_check(env=None, owners=True):
    """Scan and check. `owners` also asks the package manager which package
    each app with a missing program came from (slow: one query each)."""
    from . import timing
    apps = de.scan(env)
    timing.mark(f"  apps scanned ({len(apps)})")
    report = check(apps, env)
    timing.mark("  apps checked")
    if owners:
        report.owners = packages.owners(report.missing)
    return apps, report

