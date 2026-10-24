"""Uninstall an app, whatever installed it: Flatpak, Snap, an AppImage,
Steam, a Distrobox export or the system's package manager. Pure Python,
no GTK.

Nothing is removed here. plan() finds out what would go, which other apps
and packages need it, and the commands that remove it; the window shows
all of that first, and runs the commands only when the user presses
Uninstall. Commands that need the password run in the user's own
terminal (terminal.py). Afterwards the files App Entries itself removes
(menu entries, icons, its own settings for the app, data folders the user
chose) become overrides.Change deletions or go to the Trash, so Undo puts
them back; the app itself comes back with the reinstall command.
"""
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import appimages, autostart, defaults, launchers, pkgmanagers
from . import desktop_entries as de
from .health import program_of, search_dirs
from .overrides import Change, read_text
from .pkgmanagers import Option, Run, as_root

SELF_ID = "io.github.HypestHyper.AppEntries"


@dataclass
class Line:
    """One thing in "What's removed"."""
    glyph: str
    text: str
    size: int = 0


@dataclass
class Plan:
    """Everything the Uninstall window shows, and what pressing Uninstall does."""
    app: de.App
    kind: str                       # flatpak, snap, appimage, steam, distrobox, package
    kind_label: str                 # "Flatpak · installed for you"
    target: str                     # the package, app ID or file
    version: str = ""
    size: int = 0
    removes: List[Line] = field(default_factory=list)
    also: List[Option] = field(default_factory=list)       # "Also remove": off unless turned on
    advanced: List[Option] = field(default_factory=list)
    folders: Dict[str, List[str]] = field(default_factory=dict)   # option key -> folders to the Trash
    folder_sizes: Dict[str, int] = field(default_factory=dict)
    blocked: str = ""               # why it can't be uninstalled here at all
    notes: List[str] = field(default_factory=list)          # what else it affects, in plain words
    goes_too: List[str] = field(default_factory=list)       # other apps in your menus removed with it
    stop_working: List[str] = field(default_factory=list)   # apps in your menus that use it
    in_terminal: bool = False
    opens_steam: bool = False
    password: bool = False
    manager: Optional[pkgmanagers.Manager] = None
    packages: List[str] = field(default_factory=list)
    app_ids: List[str] = field(default_factory=list)        # menu entries that go with it
    trash_paths: List[str] = field(default_factory=list)    # always moved to the Trash (the AppImage)
    entry_files: List[str] = field(default_factory=list)    # your files deleted with Undo (entries, icons)
    info: Dict[str, pkgmanagers.Info] = field(default_factory=dict)
    # Filled in by update():
    preview: Optional[pkgmanagers.Preview] = None
    stops: str = ""                 # why it would stop with these options
    warnings: Dict[str, str] = field(default_factory=dict)  # option key -> its warning, filled in
    # Set by the kind:
    _commands: Callable = None
    _reinstall: Callable = None
    _gone: Callable = None
    _update: Callable = None

    @property
    def options(self) -> List[Option]:
        return self.also + self.advanced

    def defaults(self) -> List[str]:
        return [o.key for o in self.options if o.default]

    def update(self, opts: Sequence[str]) -> None:
        """Ask again what would happen with these options (runs the package
        manager's dry run, so call it in the background)."""
        self.stops = ""
        if self._update is not None:
            self._update(self, list(opts))
        deps = ", ".join(self.preview.dependents) if self.preview and self.preview.dependents else "none"
        self.warnings = {o.key: o.warning.replace("{dependents}", deps) for o in self.options if o.warning}

    def commands(self, opts: Sequence[str]) -> List[List[str]]:
        return self._commands(self, list(opts)) if self._commands else []

    def reinstall(self, opts: Sequence[str]) -> List[List[str]]:
        return self._reinstall(self, list(opts)) if self._reinstall else []

    def gone(self) -> bool:
        """It isn't installed any more (checked after the commands ran)."""
        return self._gone(self) if self._gone else True

    def can_go(self, opts: Sequence[str]) -> bool:
        return not self.blocked and not self.stops


# ---------------------------------------------------------------------------
# Shared helpers


def _home(env) -> str:
    return env.get("HOME") or os.path.expanduser("~")


def _short(p: str, env) -> str:
    home = _home(env)
    return "~" + p[len(home):] if p.startswith(home + os.sep) else p


def folder_size(path: str, limit: int = 200000) -> int:
    """Bytes in a folder (stops counting after `limit` files)."""
    total, n = 0, 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
            n += 1
            if n > limit:
                return total
    return total


def _flatpak_id(app: de.App) -> str:
    """The Flatpak an entry starts: its X-Flatpak key, or `flatpak run … <id>`."""
    for p in (app.base_path, app.source_path):
        if p:
            try:
                d = de.DesktopFile.load(p).group_dict()
            except OSError:
                continue
            if d.get("X-Flatpak", "").strip():
                return d["X-Flatpak"].strip()
    try:
        words = shlex.split(app.exec)
    except ValueError:
        words = app.exec.split()
    if "run" in words:
        for w in words[words.index("run") + 1:]:
            if not w.startswith("-") and w.count(".") >= 2:
                return w
    stem = app.id[:-len(".desktop")]
    return stem


def _snap_name(app: de.App) -> str:
    for p in (app.base_path, app.source_path):
        if p:
            try:
                d = de.DesktopFile.load(p).group_dict()
            except OSError:
                continue
            if d.get("X-SnapInstanceName", "").strip():
                return d["X-SnapInstanceName"].strip()
    base = os.path.basename(app.base_path or app.source_path)
    if "_" in base:
        return base.split("_", 1)[0]
    m = re.match(r"(?:/snap/bin/|snap run )(\S+?)(?:\.|\s|$)", app.exec)
    return m.group(1) if m else app.id[:-len(".desktop")]


def _distrobox(exec_line: str) -> Tuple[str, List[str]]:
    """(container, command inside) for an entry distrobox-export made."""
    try:
        words = shlex.split(exec_line)
    except ValueError:
        words = exec_line.split()
    box, rest = "", []
    for i, w in enumerate(words):
        base = os.path.basename(w)
        if base == "distrobox-enter" or (base == "distrobox" and i + 1 < len(words) and words[i + 1] == "enter"):
            j = i + (2 if base == "distrobox" else 1)
            while j < len(words) and words[j] != "--":
                if words[j] in ("-n", "--name") and j + 1 < len(words):
                    box = words[j + 1]
                    j += 2
                    continue
                if not words[j].startswith("-") and not box:
                    box = words[j]
                j += 1
            rest = words[j + 1:] if j < len(words) else []
            break
    return box, rest


def kind_of(app: de.App) -> str:
    """How an app was installed, as far as uninstalling goes, or "" if it
    isn't something that can be uninstalled from here."""
    if app.id.startswith(SELF_ID):
        return ""
    src = app.source
    if src == "distrobox" or _distrobox(app.exec)[0]:
        return "distrobox" if _distrobox(app.exec)[0] else ""
    if src in ("flatpak", "snap", "steam"):
        return src
    if appimages.appimage_of(app.exec):
        return "appimage"
    if src == "system" and app.base_path:
        return "package"
    return ""


def _your_files(apps: Sequence[de.App], ids: Sequence[str], env) -> List[Change]:
    """Files App Entries keeps for these apps (hide settings, edits, icons it
    drew) and autostart copies it made: they'd be left over once the app is
    gone. Undo puts them back."""
    out = []
    wanted = set(ids)
    for a in apps:
        if a.id not in wanted:
            continue
        if a.override_path and a.override_path != a.base_path and not a.created:
            text = read_text(a.override_path)
            if text is not None:
                out.append(Change(a.id, a.name, a.override_path, text, None, False))
        icon = launchers.icon_path(launchers.PREFIX + "icon-" + a.id, env)
        text = read_text(icon)
        if text is not None and launchers.symbols_icon(text):
            out.append(Change(a.id, a.name, icon, text, None, False))
    stems = {i[:-len(".desktop")] for i in wanted}
    for it in autostart.scan(env):
        stem = it.id[:-len(".desktop")]
        base = re.sub(r"-\d+$", "", stem)
        if it.created and it.user_path and (stem in stems or base in stems):
            text = read_text(it.user_path)
            if text is not None:
                out.append(Change(it.id, it.name, it.user_path, text, None, False))
    return out


def _notes(plan: Plan, apps: Sequence[de.App], env) -> None:
    """What else uninstalling it affects: being a default app, starting at
    login, and apps in your menus that use it or go with it."""
    ids = set(plan.app_ids)
    by_id = {a.id: a for a in apps}
    plan.goes_too = sorted({by_id[i].name for i in ids if i in by_id and i != plan.app.id})
    for cat in defaults.CATEGORIES:
        try:
            st = defaults.state(cat, list(apps), env)
        except OSError:
            continue
        if st.app_id in ids:
            what = cat.name if cat.name[1:2].isupper() else cat.name[:1].lower() + cat.name[1:]
            plan.notes.append("It's your default for %s. Afterwards choose another in Default apps, or your "
                              "desktop picks one." % what)
    for it in autostart.scan(env):
        stem = it.id[:-len(".desktop")]
        if it.enabled and re.sub(r"-\d+$", "", stem) in {i[:-len(".desktop")] for i in ids}:
            if it.created:
                plan.notes.append("It starts when you log in. That autostart entry is removed too.")
            else:
                plan.notes.append("It starts when you log in. Its autostart entry goes with the app.")
            break


def _users(plan: Plan, apps: Sequence[de.App], uses: Callable[[str, de.App], bool]) -> None:
    """Apps that stay in your menus but run what's being removed (your own
    launchers and web apps for it, say)."""
    ids = set(plan.app_ids)
    out = []
    for a in apps:
        if a.id in ids or a.id == plan.app.id:
            continue
        prog = program_of(a.exec)
        if prog and uses(prog, a):
            out.append(a.name)
    plan.stop_working = sorted(set(out), key=str.casefold)


def _data_option(plan: Plan, key: str, title: str, explanation: str, paths: List[str], env) -> None:
    paths = [p for p in paths if os.path.isdir(p) and not os.path.islink(p)]
    if not paths:
        return
    plan.also.append(Option(key, title, explanation))
    plan.folders[key] = paths
    plan.folder_sizes[key] = sum(folder_size(p) for p in paths)


# ---------------------------------------------------------------------------
# Flatpak


def _flatpak_fields(text: str) -> Dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([\w ]+?):\s*(.*)$", line)
        if m:
            out.setdefault(m.group(1).strip(), m.group(2).strip())
    return out


def _plan_flatpak(app: de.App, apps, env, run: Run) -> Plan:
    fid = _flatpak_id(app)
    home = _home(env)
    user = (app.base_path or "").startswith(os.path.join(home, ""))
    inst = "--user" if user else "--system"
    p = Plan(app, "flatpak", "Flatpak · " + ("installed for you" if user else "installed for all users"), fid)
    info = _flatpak_fields(pkgmanagers._ok(run(["flatpak", "info", inst, fid])))
    if not info:
        p.blocked = "Flatpak doesn't list %s as installed (%s)." % (fid, inst.strip("-"))
    p.version = info.get("Version", "")
    p.size = pkgmanagers._human_size(info.get("Installed", ""))
    origin = info.get("Origin", "") or "flathub"
    runtime = info.get("Runtime", "")
    p.removes.append(Line("package_2", "The %s Flatpak (%s)" % (app.name, fid), p.size))
    listing = pkgmanagers._ok(run(["flatpak", "list", inst, "--columns=application,ref,runtime"]))
    rows = [l.split("\t") for l in listing.splitlines() if l.strip()]
    rows = [r + [""] * (3 - len(r)) for r in rows]
    addons = [r[1] for r in rows if r[0].startswith(fid + ".") and r[0] != fid]
    if addons:
        p.removes.append(Line("apps", "Its add-ons: " + ", ".join(a.split("/")[0] for a in addons)))
    p.app_ids = [a.id for a in apps if a.source == "flatpak" and _flatpak_id(a) == fid]
    p.removes.append(Line("description", "Its menu entr%s" % ("ies" if len(p.app_ids) > 1 else "y")))
    users_of_runtime = [r[0] for r in rows if r[2] == runtime and r[0] != fid and not r[0].startswith(fid + ".")]
    runtime_refs = []
    if runtime and not users_of_runtime and any(r[1].startswith(runtime.split("/")[0] + "/") and
                                                r[1].endswith(runtime.split("/")[-1]) for r in rows):
        runtime_refs = [runtime]
        p.also.append(Option("runtime", "The runtime nothing else uses",
                             "%s is a shared part Flatpak apps need, and no other app installed this way uses "
                             "it. Flatpak can download it again." % runtime.split("/")[0]))
    _data_option(p, "data", "Its data and sign-ins",
                 "Settings, caches and logins in your home folder. Moved to the Trash, so you can restore them.",
                 [os.path.join(home, ".var", "app", fid)], env)
    p.advanced.append(Option("force", "Remove even if it's running",
                             "Normally Flatpak won't remove an app that's open.",
                             warning="%s is closed straight away, without saving anything it has open." % app.name))
    running = pkgmanagers._ok(run(["flatpak", "ps", "--columns=application"]))
    is_running = fid in running.split()
    p.in_terminal = not user
    p.password = not user

    def update(plan, opts):
        if is_running and "force" not in opts:
            plan.stops = "%s is running. Close it first, or turn on “Remove even if it's running”." \
                % app.name

    def commands(plan, opts):
        refs = [fid] + addons + (runtime_refs if "runtime" in opts else [])
        argv = ["flatpak", "uninstall", inst] + (["--force-remove"] if "force" in opts else [])
        if user:
            argv += ["--noninteractive", "-y"]
        return [argv + refs]

    def reinstall(plan, opts):
        return [["flatpak", "install", inst, origin, fid]]

    def gone(plan):
        r = run(["flatpak", "info", inst, fid])
        return r is not None and r[0] != 0

    p._update, p._commands, p._reinstall, p._gone = update, commands, reinstall, gone
    _users(p, apps, lambda prog, a: os.path.basename(prog) == "flatpak" and fid in a.exec.split())
    if fid in running.split():
        p.notes.append("It's running now.")
    return p


# ---------------------------------------------------------------------------
# Snap


def _plan_snap(app: de.App, apps, env, run: Run, which) -> Plan:
    name = _snap_name(app)
    p = Plan(app, "snap", "Snap · installed for all users", name)
    listing = pkgmanagers._ok(run(["snap", "list", name])).splitlines()
    row = listing[1].split() if len(listing) > 1 else []
    if not row:
        p.blocked = "Snap doesn't list %s as installed." % name
    p.version = row[1] if len(row) > 1 else ""
    tracking = row[3] if len(row) > 3 else ""
    notes = row[5] if len(row) > 5 else ""
    snaps = "/var/lib/snapd/snaps"
    try:
        p.size = sum(os.path.getsize(os.path.join(snaps, f)) for f in os.listdir(snaps)
                     if f.startswith(name + "_") and f.endswith(".snap"))
    except OSError:
        pass
    p.app_ids = [a.id for a in apps if a.source == "snap" and _snap_name(a) == name]
    p.removes.append(Line("package_2", "The %s snap, every version kept" % name, p.size))
    p.removes.append(Line("description", "Its menu entr%s" % ("ies" if len(p.app_ids) > 1 else "y")))
    data = os.path.join(_home(env), "snap", name)
    if os.path.isdir(data):
        p.removes.append(Line("folder", "Its data in %s. Snap keeps a copy (a snapshot) for 31 days, which "
                                        "“snap restore” brings back." % _short(data, env),
                              folder_size(data)))
    p.advanced.append(Option("purge", "Don't keep a snapshot of its data",
                             "Normally snap saves a copy of its data before removing it.",
                             warning="Its data is deleted for good, with no copy to restore."))
    users = []
    for line in pkgmanagers._ok(run(["snap", "connections", name])).splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 3 and cols[2].startswith(name + ":") and cols[1] != "-" \
                and not cols[1].startswith(name + ":"):
            users.append(cols[1].split(":")[0])
    users = sorted(set(users))
    if users:
        p.notes.append("Other snaps use parts of it and lose them: %s." % ", ".join(users))
    p.in_terminal = p.password = True
    classic = "classic" in notes.split(",")

    def commands(plan, opts):
        return [as_root(["snap", "remove"] + (["--purge"] if "purge" in opts else []) + [name], which)]

    def reinstall(plan, opts):
        argv = ["snap", "install", name]
        if tracking and tracking not in ("latest/stable", "stable", "-"):
            argv.append("--channel=" + tracking)
        if classic:
            argv.append("--classic")
        return [as_root(argv, which)]

    def gone(plan):
        r = run(["snap", "list", name])
        return r is not None and r[0] != 0

    p._commands, p._reinstall, p._gone = commands, reinstall, gone
    _users(p, apps, lambda prog, a: prog.startswith("/snap/bin/" + name) or prog == name and
           os.path.realpath(shutil.which(prog, path=":".join(search_dirs(env))) or "").startswith("/snap/"))
    return p


# ---------------------------------------------------------------------------
# AppImage


def _plan_appimage(app: de.App, apps, env) -> Plan:
    r = appimages.plan(app, env)
    p = Plan(app, "appimage", "AppImage · a single file", r.appimage, size=r.size)
    p.blocked = appimages.problem(r) or ""
    exists = os.path.isfile(r.appimage)
    if exists:
        p.removes.append(Line("deployed_code", "%s, to the Trash" % _short(r.appimage, env), r.size))
        p.trash_paths = [r.appimage]
    else:
        p.notes.append("The AppImage file itself is already gone; what was set up for it is still removed.")
    for f in r.entries + r.icons + r.others:
        p.removes.append(Line("description", _short(f, env)))
    p.entry_files = r.files
    p.app_ids = [de.desktop_id(de.user_apps_dir(env), f) for f in r.entries]
    if app.id not in p.app_ids:
        p.app_ids.append(app.id)
    if r.blocked:
        p.notes.append("%d more entr%s outside your folder start%s it and can't be removed here: %s." % (
            len(r.blocked), "y" if len(r.blocked) == 1 else "ies", "s" if len(r.blocked) == 1 else "",
            ", ".join(r.blocked)))
    _data_option(p, "data", "Folders that look like its settings",
                 "Found by name, so only a guess: check the list. Moved to the Trash, so you can restore them.",
                 r.settings, env)
    _users(p, apps, lambda prog, a: os.path.realpath(prog) == os.path.realpath(r.appimage))
    return p


# ---------------------------------------------------------------------------
# Steam


def steam_libraries(env) -> List[str]:
    """Every steamapps folder: the usual Steam folders (also for the Flatpak
    and Snap), and the libraries they list."""
    home = _home(env)
    roots = [os.path.join(home, ".local", "share", "Steam"), os.path.join(home, ".steam", "steam"),
             os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
             os.path.join(home, "snap", "steam", "common", ".local", "share", "Steam")]
    found = []
    for root in roots:
        apps_dir = os.path.join(root, "steamapps")
        if not os.path.isdir(apps_dir):
            continue
        found.append(apps_dir)
        try:
            with open(os.path.join(apps_dir, "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            found.append(os.path.join(m.group(1).replace("\\\\", "\\"), "steamapps"))
    out = []
    for d in found:
        real = os.path.realpath(d)
        if real not in out and os.path.isdir(real):
            out.append(real)
    return out


def _manifest(appid: str, env) -> Tuple[str, Dict[str, str]]:
    for lib in steam_libraries(env):
        path = os.path.join(lib, "appmanifest_%s.acf" % appid)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        return path, dict(re.findall(r'^\s*"(\w+)"\s+"([^"]*)"', text, flags=re.M))
    return "", {}


def _plan_steam(app: de.App, apps, env, which) -> Plan:
    m = re.search(r"steam://rungameid/(\d+)", app.exec)
    appid = m.group(1) if m else ""
    p = Plan(app, "steam", "Steam game", appid)
    if not appid:
        p.blocked = "Couldn't tell which Steam game this starts."
        return p
    manifest, fields = _manifest(appid, env)
    p.size = int(fields.get("SizeOnDisk", "0") or 0) if fields.get("SizeOnDisk", "").isdigit() else 0
    p.app_ids = [a.id for a in apps if "steam://rungameid/%s" % appid in a.exec]
    icon = de.DesktopFile.load(app.source_path).group_dict().get("Icon", "") if app.source_path else ""
    icon_files = appimages._icon_files(icon, de.user_data_dir(env)) if icon and not os.path.isabs(icon) else []
    others_use = any(a.icon == icon for a in apps if a.id not in p.app_ids)
    p.entry_files = [a.source_path for a in apps if a.id in p.app_ids and a.source_path.startswith(
        de.user_apps_dir(env) + os.sep)] + ([] if others_use else icon_files)
    if manifest:
        p.removes.append(Line("sports_esports", "The game, removed by Steam (%s)" % fields.get("name", app.name),
                              p.size))
        p.opens_steam = True
    else:
        p.notes.append("Steam doesn't list it as installed, so only its menu entry and icons are removed.")
    for f in p.entry_files:
        p.removes.append(Line("description", _short(f, env)))
    steam = "steam" if which("steam") else ""

    def commands(plan, opts):
        if not manifest:
            return []
        if steam:
            return [[steam, "steam://uninstall/" + appid]]
        return [["xdg-open", "steam://uninstall/" + appid]]

    def reinstall(plan, opts):
        return [[steam or "xdg-open", "steam://install/" + appid]]

    p._commands, p._reinstall = commands, reinstall
    p._gone = lambda plan: not manifest or not os.path.exists(manifest)
    return p


# ---------------------------------------------------------------------------
# Distrobox


def _in_box(box: str, run: Run) -> Run:
    def inner(argv):
        return run(["distrobox-enter", "-n", box, "--"] + argv)
    return inner


def _plan_distrobox(app: de.App, apps, env, run: Run) -> Plan:
    box = _distrobox(app.exec)[0]
    p = Plan(app, "distrobox", "Distrobox · from the %s container" % box, box)
    user_apps = de.user_apps_dir(env)
    if not app.source_path.startswith(user_apps + os.sep):
        p.blocked = "Its menu entry isn't in your folder, so it wasn't exported by distrobox-export."
        return p
    p.app_ids = [app.id]
    icon = de.DesktopFile.load(app.source_path).group_dict().get("Icon", "")
    files = [app.source_path]
    others_use = any(a.icon == icon for a in apps if a.id != app.id)
    if icon and not others_use:
        if os.path.isabs(icon):
            if icon.startswith(de.user_data_dir(env) + os.sep) and os.path.isfile(icon):
                files.append(icon)
        else:
            files += appimages._icon_files(icon, de.user_data_dir(env))
    p.entry_files = files
    for f in files:
        p.removes.append(Line("description", _short(f, env)))
    p.notes.append("The program stays installed inside the %s container unless you choose to uninstall it "
                   "there too (under Advanced)." % box)
    exported = os.path.basename(app.source_path)
    original = exported[len(box) + 1:] if exported.startswith(box + "-") else exported
    p.advanced.append(Option("inside", "Also uninstall it inside %s" % box,
                             "Runs the container's own package manager in your terminal, after it shows what "
                             "it would remove."))
    found: Dict[str, Tuple[Optional[pkgmanagers.Manager], str]] = {}

    def probe():
        if "m" in found:
            return found["m"]
        code = "for t in pacman dpkg-query rpm dnf dnf5 zypper xbps-query apk; do command -v $t >/dev/null && " \
               "echo $t; done"
        r = run(["distrobox-enter", "-n", box, "--", "sh", "-c", code])
        tools = set((r[1] if r else "").split())
        inside = _in_box(box, run)
        managers = pkgmanagers.detect(inside, lambda t: t if t in tools else None, booted_ostree=False)
        found["m"] = pkgmanagers.owner_of("/usr/share/applications/" + original, managers)
        return found["m"]

    def update(plan, opts):
        if "inside" not in opts:
            plan.preview, plan.manager, plan.packages = None, None, []
            return
        m, pkg = probe()
        if m is None:
            plan.stops = "Couldn't tell which package installed it inside %s." % box
            return
        plan.manager, plan.packages = m, [pkg]
        plan.preview = m.preview([pkg], [o.key for o in m.options if o.default])
        plan.stops = plan.preview.stops

    def commands(plan, opts):
        if "inside" not in opts or plan.manager is None:
            return []
        enter = ["distrobox-enter", "-n", box, "--"]
        return [enter + c for c in plan.manager.commands(plan.packages,
                                                          [o.key for o in plan.manager.options if o.default])]

    def reinstall(plan, opts):
        enter = ["distrobox-enter", "-n", box, "--"]
        out = [enter + c for c in plan.manager.reinstall(plan.packages)] if "inside" in opts and plan.manager \
            else []
        return out + [enter + ["distrobox-export", "--app", original[:-len(".desktop")]]]

    def gone(plan):
        if plan.manager is None:
            return True
        return not plan.manager.owner("/usr/share/applications/" + original)

    p._update, p._commands, p._reinstall, p._gone = update, commands, reinstall, gone
    return p


# ---------------------------------------------------------------------------
# System packages


def _plan_package(app: de.App, apps, env, run: Run, which, managers=None) -> Plan:
    managers = pkgmanagers.detect(run, which) if managers is None else managers
    m, pkg = pkgmanagers.owner_of(app.base_path, managers)
    p = Plan(app, "package", "Package", pkg or os.path.basename(app.base_path))
    if m is None:
        names = ", ".join(x.label for x in managers) or "no package manager found"
        p.blocked = "Couldn't tell which package installed it (%s). Its entry is %s." % (names, app.base_path)
        return p
    p.manager, p.packages = m, [pkg]
    p.kind_label = "%s · installed for all users" % m.label
    info = m.info(pkg)
    p.info[pkg] = info
    p.version, p.size = info.version, info.size
    p.blocked = pkgmanagers.blocked(m, [pkg])
    p.in_terminal, p.password = True, m.needs_root
    files = m.files(pkg)
    owned = set(files)
    p.app_ids = sorted({a.id for a in apps if a.base_path in owned} | {app.id})
    p.advanced = list(m.options)
    names = {app.name, app.name.replace(" ", ""), app.name.replace(" ", "-"), pkg,
             os.path.basename(program_of(app.exec) or "")}
    _data_option(p, "data", "Its settings in your home folder",
                 "Folders named like it in ~/.config, ~/.local/share and ~/.cache. Found by name, so only a "
                 "guess: check the list. Moved to the Trash, so you can restore them.",
                 appimages.folders_named(names, env), env)
    file_cache: Dict[str, set] = {pkg: owned}

    def update(plan, opts):
        pv = m.preview([pkg], opts)
        plan.preview = pv
        plan.stops = pv.stops
        plan.removes = [Line("package_2", "%s %s" % (pkg, plan.version), plan.size)]
        for d in pv.removed:
            if d == pkg:
                continue
            why = ("needs %s" % pkg if d in pv.dependents else "only %s needed it" % pkg if d in pv.unneeded else "")
            plan.removes.append(Line("package_2", "%s (%s)" % (d, why) if why else d))
        going = set(pv.removed) if pv.dependents_go or pv.exact else {pkg}
        why_not = pkgmanagers.blocked(m, sorted(going - {pkg}))
        if why_not and not plan.stops:
            plan.stops = why_not
        all_files = set()
        for d in going:
            if d not in file_cache and len(file_cache) < 40:
                file_cache[d] = set(m.files(d))
            all_files |= file_cache.get(d, set())
        plan.app_ids = sorted({a.id for a in apps if a.base_path in all_files} | {app.id})
        by_id = {a.id: a for a in apps}
        plan.goes_too = sorted({by_id[i].name for i in plan.app_ids if i in by_id and i != app.id},
                               key=str.casefold)

        def uses(prog, a):
            path = prog if os.path.isabs(prog) else shutil.which(prog, path=":".join(search_dirs(env))) or ""
            return bool(path) and (path in all_files or os.path.realpath(path) in all_files)
        _users(plan, apps, uses)

    def commands(plan, opts):
        return m.commands([pkg], opts)

    def reinstall(plan, opts):
        pv = plan.preview
        again = [pkg] + ([d for d in pv.dependents if d in pv.removed] if pv and pv.dependents_go else [])
        return m.reinstall(again, plan.info)

    def gone(plan):
        return not os.path.exists(app.base_path) or m.owner(app.base_path) != pkg

    p._update, p._commands, p._reinstall, p._gone = update, commands, reinstall, gone
    return p


# ---------------------------------------------------------------------------


def plan(app: de.App, apps: Sequence[de.App], env=None, run: Run = pkgmanagers.run,
         which: Callable = shutil.which, managers=None) -> Plan:
    """What uninstalling `app` involves. Only looks; changes nothing. Raises
    ValueError for apps that can't be uninstalled from here."""
    env = os.environ if env is None else env
    kind = kind_of(app)
    if kind == "flatpak":
        p = _plan_flatpak(app, apps, env, run)
    elif kind == "snap":
        p = _plan_snap(app, apps, env, run, which)
    elif kind == "appimage":
        p = _plan_appimage(app, apps, env)
    elif kind == "steam":
        p = _plan_steam(app, apps, env, which)
    elif kind == "distrobox":
        p = _plan_distrobox(app, apps, env, run)
    elif kind == "package":
        p = _plan_package(app, apps, env, run, which, managers)
    else:
        raise ValueError("%s can't be uninstalled from here." % app.name)
    if not p.app_ids:
        p.app_ids = [app.id]
    _notes(p, apps, env)
    p.update(p.defaults())
    return p


def file_changes(p: Plan, apps: Sequence[de.App], env=None) -> List[Change]:
    """The files App Entries removes once the app itself is gone: entries
    and icons it was given (AppImage, Steam, Distrobox), and App Entries' own
    files for it. Undo puts them back."""
    env = os.environ if env is None else env
    out: List[Change] = []
    seen = set()
    for f in p.entry_files:
        if f in seen or not os.path.lexists(f):
            continue
        seen.add(f)
        text_like = f.endswith((".desktop", ".svg", ".xml", ".xpm"))
        before = read_text(f) if text_like else _read_bytes(f)
        if before is not None:
            out.append(Change(p.app.id, p.app.name, f, before, None, False))
    for c in _your_files(apps, p.app_ids, env):
        if c.path not in seen:
            seen.add(c.path)
            out.append(c)
    return out


def _read_bytes(path: str):
    from .overrides import read_bytes
    return read_bytes(path)


def to_trash(p: Plan, opts: Sequence[str]) -> List[str]:
    """What goes to the Trash afterwards: the AppImage, and data folders the
    user chose."""
    out = list(p.trash_paths)
    for key in opts:
        out += p.folders.get(key, [])
    return [x for x in out if os.path.lexists(x)]


def stream(argv: List[str], on_line: Callable[[str], None]) -> int:
    """Run a command that needs no password and pass on each line it prints.
    Returns its exit code."""
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                text=True, bufsize=1, env=dict(os.environ, LC_ALL="C", LANG="C"))
    except OSError as e:
        on_line("Couldn't start %s: %s" % (argv[0], e.strerror or e))
        return 127
    assert proc.stdout is not None
    for line in proc.stdout:
        on_line(line.rstrip("\n"))
    return proc.wait()


# ---------------------------------------------------------------------------
# Several at once


@dataclass
class Batch:
    plans: List[Plan]
    skipped: List[Tuple[str, str]] = field(default_factory=list)   # (name, why)

    def groups(self) -> Dict[str, List[Plan]]:
        """By how they're removed, in the order they run."""
        out: Dict[str, List[Plan]] = {}
        for p in self.plans:
            key = p.kind if p.kind != "package" else "package:" + (p.manager.name if p.manager else "")
            out.setdefault(key, []).append(p)
        return out

    def commands(self, opts: Dict[str, Sequence[str]]) -> Tuple[List[List[str]], List[List[str]]]:
        """(run here, run in the terminal). Packages of one manager are
        removed with one command, so it shows them all and asks once."""
        here, term = [], []
        for key, plans in self.groups().items():
            if key.startswith("package:") and plans and plans[0].manager is not None:
                m = plans[0].manager
                pkgs = list(dict.fromkeys(pkg for p in plans for pkg in p.packages))
                chosen = set(plans[0].defaults())
                for p in plans:
                    chosen &= set(opts.get(p.app.id, p.defaults()))
                term += m.commands(pkgs, sorted(chosen))
                continue
            for p in plans:
                cmds = p.commands(opts.get(p.app.id, p.defaults()))
                (term if p.in_terminal else here).extend(cmds)
        return here, term


def plan_batch(apps_chosen: Sequence[de.App], apps: Sequence[de.App], env=None, run: Run = pkgmanagers.run,
               which: Callable = shutil.which) -> Batch:
    env = os.environ if env is None else env
    managers = pkgmanagers.detect(run, which)
    b = Batch([])
    seen_targets = set()
    for a in apps_chosen:
        kind = kind_of(a)
        if not kind:
            b.skipped.append((a.name, "it isn't something App Entries can uninstall"))
            continue
        if kind == "steam":
            b.skipped.append((a.name, "Steam games are uninstalled one at a time, in Steam's own window"))
            continue
        try:
            p = plan(a, apps, env, run, which, managers)
        except (ValueError, OSError) as e:
            b.skipped.append((a.name, str(e)))
            continue
        if p.blocked:
            b.skipped.append((a.name, p.blocked))
            continue
        key = (p.kind, p.target)
        if key in seen_targets:
            continue   # another entry for the same package
        seen_targets.add(key)
        b.plans.append(p)
    return b
