"""Default apps: which app opens links, PDFs, pictures and so on. Pure
Python, no GTK.

Follows the freedesktop.org MIME Applications spec, which GNOME, KDE,
Cinnamon, MATE, LXQt, Budgie, xdg-open and GTK and Qt apps all read:
choices go in ~/.config/mimeapps.list. A desktop-specific file
(~/.config/kde-mimeapps.list and the like) wins over it, so an entry
there for the same type is updated too. Xfce keeps its own preferred
browser, mail reader and file manager, and KDE its browser; those are
updated as well when that desktop is running. Every write is an
overrides.Change, so it can be undone.
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import desktop_entries as de
from .overrides import Change, read_text

DEFAULT = "Default Applications"
ADDED = "Added Associations"
REMOVED = "Removed Associations"


@dataclass
class Category:
    key: str
    name: str
    icon: str
    mimes: Tuple[str, ...]
    xfce: str = ""        # Xfce's helpers.rc key
    kde_browser: bool = False


CATEGORIES = [
    Category("browser", "Web browser", "public",
             ("x-scheme-handler/http", "x-scheme-handler/https", "text/html", "application/xhtml+xml"),
             xfce="WebBrowser", kde_browser=True),
    Category("mail", "Email", "mail", ("x-scheme-handler/mailto",), xfce="MailReader"),
    Category("files", "Files and folders", "folder", ("inode/directory",), xfce="FileManager"),
    Category("text", "Text files", "description", ("text/plain",)),
    Category("pdf", "PDF documents", "picture_as_pdf", ("application/pdf",)),
    Category("images", "Pictures", "image",
             ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff", "image/avif",
              "image/heif")),
    Category("video", "Videos", "movie",
             ("video/mp4", "video/x-matroska", "video/webm", "video/quicktime", "video/x-msvideo", "video/mpeg",
              "video/ogg")),
    Category("music", "Music", "music_note",
             ("audio/mpeg", "audio/flac", "audio/ogg", "audio/x-vorbis+ogg", "audio/x-wav", "audio/wav",
              "audio/mp4", "audio/aac", "audio/x-opus+ogg", "audio/opus")),
    Category("archives", "Archives", "folder_zip",
             ("application/zip", "application/x-tar", "application/x-compressed-tar", "application/gzip",
              "application/x-7z-compressed", "application/vnd.rar", "application/x-rar",
              "application/x-xz-compressed-tar", "application/zstd")),
]


def _desktops(env) -> List[str]:
    return [d.lower() for d in de.current_desktops(env)]


def config_home(env=None) -> str:
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    d = env.get("XDG_CONFIG_HOME") or ""
    return d if os.path.isabs(d) else os.path.join(home, ".config")


def files(env=None) -> List[str]:
    """Every mimeapps.list, highest precedence first, per the spec."""
    env = os.environ if env is None else env
    config_dirs = [d for d in (env.get("XDG_CONFIG_DIRS") or "").split(":") if os.path.isabs(d)] or ["/etc/xdg"]
    data_dirs = [d for d in (env.get("XDG_DATA_DIRS") or "").split(":") if os.path.isabs(d)] \
        or ["/usr/local/share", "/usr/share"]
    out = []
    for folder in [config_home(env)] + config_dirs + [de.user_apps_dir(env)] + \
            [os.path.join(d, "applications") for d in data_dirs]:
        for d in _desktops(env):
            out.append(os.path.join(folder, "%s-mimeapps.list" % d))
        out.append(os.path.join(folder, "mimeapps.list"))
    return list(dict.fromkeys(out))


def _ids(value: str) -> List[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


def _read(path: str) -> Dict[str, Dict[str, List[str]]]:
    try:
        df = de.DesktopFile.load(path)
    except OSError:
        return {}
    return {g: {k: _ids(v) for k, v in df.group_dict(g).items()} for g in (DEFAULT, ADDED, REMOVED)}


def default_for(mime: str, installed, env=None) -> Tuple[str, str]:
    """(desktop ID, the file that chose it). The ID is "" when nothing is
    chosen; an ID that isn't installed is skipped, as the spec says."""
    removed = set()
    for path in files(env):
        data = _read(path)
        if not data:
            continue
        for did in data[DEFAULT].get(mime, []):
            if did in installed and did not in removed:
                return did, path
        removed |= set(data[REMOVED].get(mime, []))
    return "", ""


def candidates(cat: Category, apps: List[de.App]) -> List[de.App]:
    """Apps that open these types, the ones that open most of them first.
    Helpers their package keeps out of menus are left out."""
    found = []
    for a in apps:
        n = len(set(a.mime_types) & set(cat.mimes))
        if n and not (a.no_display and not a.has_override):
            found.append((-n, a.name.casefold(), a))
    seen, out = set(), []
    for _n, _name, a in sorted(found, key=lambda x: x[:2]):
        if a.id not in seen:
            seen.add(a.id)
            out.append(a)
    return out


@dataclass
class State:
    app_id: str = ""                  # the default for all its types, or "" if none/mixed
    mixed: bool = False               # its types open in different apps
    chosen_by_you: bool = False       # set in your own mimeapps.list
    per_type: Dict[str, str] = field(default_factory=dict)


def state(cat: Category, apps: List[de.App], env=None) -> State:
    installed = {a.id for a in apps}
    mine = {os.path.normpath(p) for p in files(env) if p.startswith(config_home(env) + os.sep)}
    s = State()
    for m in cat.mimes:
        did, path = default_for(m, installed, env)
        s.per_type[m] = did
        if did and os.path.normpath(path) in mine:
            s.chosen_by_you = True
    # Types no installed app opens don't count towards "mixed".
    opened = {m: d for m, d in s.per_type.items() if d or any(m in a.mime_types for a in apps)}
    values = set(opened.values())
    if len(values) == 1:
        s.app_id = values.pop()
    elif values:
        s.mixed = True
        # The most common choice, to show.
        counts = {}
        for d in opened.values():
            if d:
                counts[d] = counts.get(d, 0) + 1
        s.app_id = max(counts, key=counts.get) if counts else ""
    return s


# ---------------------------------------------------------------------------
# Changing


def _edit(path: str, fn) -> Optional[Change]:
    before = read_text(path)
    df = de.DesktopFile(before or "")
    fn(df)
    after = df.text()
    if after == (before or ""):
        return None
    return Change("", os.path.basename(path), path, before, after, False)


def _user_files(env) -> List[str]:
    """Your own mimeapps.list and, if they exist, the desktop-specific ones
    that take precedence over it."""
    home = config_home(env)
    specific = [os.path.join(home, "%s-mimeapps.list" % d) for d in _desktops(env)]
    return [p for p in specific if os.path.exists(p)] + [os.path.join(home, "mimeapps.list")]


def plan_set(cat: Category, app: de.App, env=None) -> Tuple[List[Change], List[str]]:
    """Changes that make `app` the default for this category, and notes for
    anything that could still override it."""
    env = os.environ if env is None else env
    mimes = [m for m in cat.mimes if m in app.mime_types] or list(cat.mimes)
    main = os.path.join(config_home(env), "mimeapps.list")
    changes, notes = [], []

    for path in _user_files(env):
        def apply(df, is_main=(path == main)):
            current = df.group_dict(DEFAULT)
            for m in mimes:
                if is_main or m in current:
                    df.set(m, app.id + ";", DEFAULT)
                if is_main:
                    added = [x for x in _ids(df.group_dict(ADDED).get(m, "")) if x != app.id]
                    df.set(m, ";".join([app.id] + added) + ";", ADDED)
                removed = _ids(df.group_dict(REMOVED).get(m, ""))
                if app.id in removed:
                    rest = [x for x in removed if x != app.id]
                    if rest:
                        df.set(m, ";".join(rest) + ";", REMOVED)
                    else:
                        df.remove(m, REMOVED)
        c = _edit(path, apply)
        if c is not None:
            changes.append(c)

    desktops = [d.upper() for d in de.current_desktops(env)]
    if cat.xfce and "XFCE" in desktops:
        c, note = _plan_xfce(cat.xfce, app, env)
        if c is not None:
            changes.append(c)
        if note:
            notes.append(note)
    if cat.kde_browser and "KDE" in desktops:
        kdeglobals = os.path.join(config_home(env), "kdeglobals")
        if os.path.exists(kdeglobals):
            c = _edit(kdeglobals, lambda df: df.set("BrowserApplication", app.id, "General"))
            if c is not None:
                changes.append(c)
    if cat.key == "browser" and env.get("BROWSER"):
        notes.append("Your BROWSER variable is set to %s. xdg-open uses it for links before this setting, "
                     "so remove it from your shell or session to use this choice." % env["BROWSER"])
    for c in changes:
        c.app_id, c.app_name = app.id, app.name
    return changes, notes


def plan_reset(cat: Category, env=None) -> List[Change]:
    """Remove your choices for this category, so your desktop's defaults apply."""
    changes = []
    for path in _user_files(env):
        if not os.path.exists(path):
            continue

        def apply(df):
            for m in cat.mimes:
                df.remove(m, DEFAULT)
        c = _edit(path, apply)
        if c is not None:
            changes.append(c)
    return changes


# ---------------------------------------------------------------------------
# Xfce's preferred applications (exo-open, used by xdg-open on Xfce)


def _xfce_helpers(env) -> Dict[str, Tuple[str, List[str]]]:
    """helper ID -> (category, binaries)."""
    env = os.environ if env is None else env
    dirs = [os.path.join(de.user_data_dir(env), "xfce4", "helpers")]
    data_dirs = [d for d in (env.get("XDG_DATA_DIRS") or "").split(":") if os.path.isabs(d)] \
        or ["/usr/local/share", "/usr/share"]
    dirs += [os.path.join(d, "xfce4", "helpers") for d in data_dirs]
    out = {}
    for folder in dirs:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            if n.endswith(".desktop") and n[:-8] not in out:
                try:
                    d = de.DesktopFile.load(os.path.join(folder, n)).group_dict()
                except OSError:
                    continue
                out[n[:-8]] = (d.get("X-XFCE-Category", ""), _ids(d.get("X-XFCE-Binaries", "")))
    return out


def _plan_xfce(key: str, app: de.App, env) -> Tuple[Optional[Change], str]:
    exe = app.executable
    match = next((hid for hid, (cat, bins) in _xfce_helpers(env).items()
                  if cat == key and (exe in bins or any(os.path.basename(b) == exe for b in bins))), None)
    if match is None:
        return None, ("Xfce has its own setting for this and doesn't list %s, so also choose it in Xfce's "
                      "Default Applications." % app.name)
    path = os.path.join(config_home(env), "xfce4", "helpers.rc")
    before = read_text(path)
    lines = [l for l in (before or "").splitlines() if not l.startswith(key + "=")]
    after = "\n".join(lines + ["%s=%s" % (key, match)]) + "\n"
    if after == before:
        return None, ""
    return Change(app.id, app.name, path, before, after, False), ""
