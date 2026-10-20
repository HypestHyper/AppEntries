"""Find and read freedesktop .desktop application entries.

Pure Python, no GTK, so it can be unit tested. Follows the Desktop Entry
Specification 1.5 and the XDG Base Directory Specification.
"""
import os
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

GROUP = "Desktop Entry"
MANAGED_KEY = "X-AppEntries-Managed"   # the file was made by App Entries
HIDDEN_KEY = "X-AppEntries-Hidden"     # App Entries added NoDisplay=true to it
CHECKSUM_KEY = "X-AppEntries-Checksum"  # of the copy as written, to spot later edits

# ---------------------------------------------------------------------------
# Parsing


class DesktopFile:
    """A .desktop file kept as lines, so it can be edited without losing
    comments, key order or other groups."""

    def __init__(self, text: str = ""):
        self.lines: List[str] = text.splitlines()

    @classmethod
    def load(cls, path: str) -> "DesktopFile":
        with open(path, encoding="utf-8", errors="replace") as f:
            return cls(f.read())

    def text(self) -> str:
        return "\n".join(self.lines) + "\n" if self.lines else ""

    # -- reading ----------------------------------------------------------

    def _group_span(self, group: str) -> Optional[Tuple[int, int]]:
        """(index of the header line, index after the last line) of a group."""
        start = None
        for i, raw in enumerate(self.lines):
            s = raw.strip()
            if s.startswith("[") and s.endswith("]"):
                if start is not None:
                    return start, i
                if s[1:-1] == group:
                    start = i
        return (start, len(self.lines)) if start is not None else None

    def items(self, group: str = GROUP) -> List[Tuple[str, str]]:
        span = self._group_span(group)
        if span is None:
            return []
        out = []
        for raw in self.lines[span[0] + 1:span[1]]:
            s = raw.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            out.append((k.strip(), v.strip()))
        return out

    def group_dict(self, group: str = GROUP) -> Dict[str, str]:
        d: Dict[str, str] = {}
        for k, v in self.items(group):
            d.setdefault(k, v)  # first occurrence wins
        return d

    def has_group(self, group: str = GROUP) -> bool:
        return self._group_span(group) is not None

    def groups(self) -> List[str]:
        out = []
        for raw in self.lines:
            s = raw.strip()
            if s.startswith("[") and s.endswith("]"):
                out.append(s[1:-1])
        return out

    # -- editing ----------------------------------------------------------

    def set(self, key: str, value: str, group: str = GROUP) -> None:
        span = self._group_span(group)
        if span is None:
            if self.lines and self.lines[-1].strip():
                self.lines.append("")
            self.lines += ["[%s]" % group, "%s=%s" % (key, value)]
            return
        start, end = span
        for i in range(start + 1, end):
            s = self.lines[i].strip()
            if "=" in s and not s.startswith("#") and s.split("=", 1)[0].strip() == key:
                self.lines[i] = "%s=%s" % (key, value)
                return
        # Append after the group's last non-blank line.
        pos = end
        while pos > start + 1 and not self.lines[pos - 1].strip():
            pos -= 1
        self.lines.insert(pos, "%s=%s" % (key, value))

    def remove(self, key: str, group: str = GROUP) -> bool:
        span = self._group_span(group)
        if span is None:
            return False
        start, end = span
        keep, removed = [], False
        for i in range(start + 1, end):
            s = self.lines[i].strip()
            if "=" in s and not s.startswith("#") and s.split("=", 1)[0].strip() == key:
                removed = True
                continue
            keep.append(self.lines[i])
        self.lines[start + 1:end] = keep
        return removed


def unescape(value: str) -> str:
    out, i = [], 0
    table = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value) and value[i + 1] in table:
            out.append(table[value[i + 1]])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def is_true(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("true", "1")


# ---------------------------------------------------------------------------
# Locale


def locale_names(env: Optional[Dict[str, str]] = None) -> List[str]:
    """Locale keys to try, best first, per the spec's matching rules."""
    env = os.environ if env is None else env
    raw = ""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if env.get(var):
            raw = env[var]
            break
    langs = [l for l in env.get("LANGUAGE", "").split(":") if l]
    if raw and raw not in ("C", "POSIX") and not raw.startswith("C."):
        langs.append(raw)
    out: List[str] = []
    for loc in langs:
        base, _, mod = loc.partition("@")
        base = base.split(".", 1)[0]
        lang, _, country = base.partition("_")
        for cand in (
            country and mod and "%s_%s@%s" % (lang, country, mod),
            country and "%s_%s" % (lang, country),
            mod and "%s@%s" % (lang, mod),
            lang,
        ):
            if cand and cand not in out:
                out.append(cand)
    return out


def localized(d: Dict[str, str], key: str, locales: List[str]) -> str:
    for loc in locales:
        v = d.get("%s[%s]" % (key, loc))
        if v:
            return unescape(v)
    return unescape(d.get(key, ""))


# ---------------------------------------------------------------------------
# Directories


def user_data_dir(env: Optional[Dict[str, str]] = None) -> str:
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    d = env.get("XDG_DATA_HOME") or ""
    return d if os.path.isabs(d) else os.path.join(home, ".local", "share")


def user_apps_dir(env: Optional[Dict[str, str]] = None) -> str:
    return os.path.join(user_data_dir(env), "applications")


def application_dirs(env: Optional[Dict[str, str]] = None) -> List[str]:
    """All application directories, highest precedence first."""
    env = os.environ if env is None else env
    # Per the base dir spec, the defaults apply only when XDG_DATA_DIRS is unset.
    data_dirs = [d for d in (env.get("XDG_DATA_DIRS") or "").split(":") if os.path.isabs(d)]
    if not data_dirs:
        data_dirs = ["/usr/local/share", "/usr/share"]
    out: List[str] = []
    for d in [user_data_dir(env)] + data_dirs:
        p = os.path.normpath(os.path.join(d, "applications"))
        if p not in out:
            out.append(p)
    return out


def desktop_id(apps_dir: str, path: str) -> str:
    """kde4/foo.desktop under an applications dir has the ID kde4-foo.desktop."""
    return os.path.relpath(path, apps_dir).replace(os.sep, "-")


# ---------------------------------------------------------------------------
# Entries


@dataclass
class Entry:
    """One .desktop file as found on disk."""
    id: str
    path: str
    data: Dict[str, str]
    in_user_dir: bool


@dataclass
class App:
    """An application as the user sees it.

    `effective` is the file launchers use (highest precedence). `display` is
    where names and icons come from: the effective file, unless it is a bare
    override, in which case the next file down. `base` is the highest file
    outside the user's folder: what the app looks like with no override."""
    id: str
    name: str
    generic_name: str = ""
    comment: str = ""
    icon: str = ""
    exec: str = ""
    no_display: bool = False       # its package asks to keep it out of menus
    hidden: bool = False           # launchers don't show it (Hidden or NoDisplay)
    source_path: str = ""          # the file the app's details come from
    override_path: str = ""        # user-level file with the same ID, if any
    override_managed: bool = False  # that file was made by this app
    system: bool = True            # a copy exists outside the user's dir
    base_path: str = ""            # that copy (the highest one), if any
    base_hidden: bool = False      # launchers would hide it without an override
    keywords: str = ""
    shadowed: List[str] = field(default_factory=list)
    # Filled in by health.check() after a scan.
    source: str = ""               # system, flatpak, snap, appimage, steam or user
    missing: str = ""              # the program it runs, if that isn't installed
    # Names of other entries for the same app (same icon and first word of the
    # name) that are in the opposite state: shown when this one is hidden, or
    # hidden when this one is shown.
    related: Tuple[str, ...] = ()
    customised: bool = False       # the user's file for a system app changes more than hiding
    created: bool = False          # a launcher made with App Entries
    # OnlyShowIn/NotShowIn rules that leave it out on the current desktop.
    only_show_in: Tuple[str, ...] = ()
    not_show_in: Tuple[str, ...] = ()
    excluded_here: bool = False
    mime_types: Tuple[str, ...] = ()   # the file types it says it opens (MimeType)

    @property
    def has_override(self) -> bool:
        return bool(self.override_path)

    @property
    def executable(self) -> str:
        return executable_name(self.exec)

    def search_text(self) -> str:
        return " ".join((self.name, self.generic_name, self.comment, self.exec,
                         self.id, self.keywords, self.source,
                         "local" if self.source == "user" else "")).casefold()


def executable_name(exec_line: str) -> str:
    try:
        parts = shlex.split(exec_line)
    except ValueError:
        parts = exec_line.split()
    # Skip `env VAR=x` wrappers and field codes.
    while parts and (parts[0] == "env" or ("=" in parts[0] and not parts[0].startswith("/"))):
        parts.pop(0)
    parts = [p for p in parts if not (len(p) == 2 and p.startswith("%"))]
    return os.path.basename(parts[0]) if parts else ""


def scan_dir(apps_dir: str, in_user_dir: bool) -> Dict[str, Entry]:
    found: Dict[str, Entry] = {}
    if not os.path.isdir(apps_dir):
        return found
    for root, dirs, files in os.walk(apps_dir, followlinks=True):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith(".desktop"):
                continue
            path = os.path.join(root, name)
            try:
                df = DesktopFile.load(path)
            except OSError:
                continue
            if not df.has_group(GROUP):
                continue
            did = desktop_id(apps_dir, path)
            found.setdefault(did, Entry(did, path, df.group_dict(GROUP), in_user_dir))
    return found


def current_desktops(env: Optional[Dict[str, str]] = None) -> List[str]:
    env = os.environ if env is None else env
    return [d for d in (env.get("XDG_CURRENT_DESKTOP") or "").split(":") if d]


def _list(value: str) -> Tuple[str, ...]:
    return tuple(v for v in value.split(";") if v.strip())


def excluded_on(data: Dict[str, str], desktops: List[str]) -> bool:
    """Whether OnlyShowIn/NotShowIn leave this entry out on these desktops,
    the way launchers check it (any match counts, case-insensitively)."""
    current = {d.casefold() for d in desktops}
    only = {d.casefold() for d in _list(data.get("OnlyShowIn", ""))}
    never = {d.casefold() for d in _list(data.get("NotShowIn", ""))}
    if only and not (only & current):
        return True
    return bool(never & current)


def scan(env: Optional[Dict[str, str]] = None, include_no_display: bool = True) -> List[App]:
    """Every launchable application, sorted by name."""
    dirs = application_dirs(env)
    user_dir = os.path.normpath(user_apps_dir(env))
    locales = locale_names(env)
    desktops = current_desktops(env)
    stacks: Dict[str, List[Entry]] = {}
    for d in dirs:
        for did, entry in scan_dir(d, d == user_dir).items():
            stacks.setdefault(did, []).append(entry)

    apps = []
    for did, stack in stacks.items():
        app = build_app(did, stack, locales, desktops)
        if app and (include_no_display or not app.no_display):
            apps.append(app)
    apps.sort(key=lambda a: (a.name.casefold(), a.id))
    return apps


def is_bare_override(data: Dict[str, str]) -> bool:
    """A user file that only exists to change state, with no Exec of its own."""
    return not data.get("Exec", "").strip()


def build_app(did: str, stack: List[Entry], locales: List[str], desktops: Optional[List[str]] = None
              ) -> Optional[App]:
    desktops = desktops or []
    effective = stack[0]
    eff = effective.data
    override = effective if effective.in_user_dir else None
    lower = [e for e in stack if not e.in_user_dir]

    display = effective
    if override and is_bare_override(eff) and lower:
        display = lower[0]
    d = display.data
    if d.get("Type", "").strip() != "Application":
        return None
    if not d.get("Exec", "").strip():
        return None

    # Whether it's hidden comes from the file launchers actually read. A bare
    # hide file only adds Hidden/NoDisplay; its desktop rules are the system's.
    rules = d if display is not effective else eff
    excluded = excluded_on(rules, desktops)
    hidden = is_true(eff.get("Hidden")) or is_true(eff.get("NoDisplay")) or excluded
    # What its package intends comes from the system copy, or for an app that
    # only exists in the user's folder, from that file unless App Entries hid it.
    if lower:
        base = lower[0].data
        no_display = is_true(base.get("NoDisplay"))
        base_hidden = no_display or is_true(base.get("Hidden")) or excluded_on(base, desktops)
    else:
        no_display = is_true(eff.get("NoDisplay")) and not is_true(eff.get(HIDDEN_KEY))
        base_hidden = False

    return App(
        id=did,
        name=localized(d, "Name", locales) or did[:-len(".desktop")],
        generic_name=localized(d, "GenericName", locales),
        comment=localized(d, "Comment", locales),
        icon=localized(d, "Icon", locales),
        exec=unescape(d.get("Exec", "")),
        no_display=no_display,
        hidden=hidden,
        source_path=display.path,
        override_path=override.path if override else "",
        override_managed=bool(override) and is_true(eff.get(MANAGED_KEY)),
        system=bool(lower),
        base_path=lower[0].path if lower else "",
        base_hidden=base_hidden,
        only_show_in=_list(rules.get("OnlyShowIn", "")),
        not_show_in=_list(rules.get("NotShowIn", "")),
        excluded_here=excluded,
        created=bool(override) and not lower and is_true(eff.get("X-AppEntries-Created")),
        keywords=localized(d, "Keywords", locales),
        shadowed=[e.path for e in stack[1:]],
        mime_types=_list(d.get("MimeType", "")),
    )
