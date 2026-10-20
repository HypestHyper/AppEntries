"""Remove an AppImage and everything that was set up for it: the file, every
entry in your folder that starts it, and the icons and file types only
those entries used. Pure Python, no GTK.

Nothing is removed here: plan() lists what would go, and the caller shows
it first. Entries, icons and file types become overrides.Change deletions
(Undo puts them back); the AppImage itself goes to the Trash.
"""
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from . import desktop_entries as de
from .overrides import Change, read_bytes, read_text

ICON_EXTS = (".png", ".svg", ".svgz", ".xpm")
# appimaged and AppImageLauncher name what they install appimagekit_<md5 of the path>…
_KIT = re.compile(r"appimagekit_[0-9a-f]{32}")


def appimage_of(exec_line: str) -> str:
    """The AppImage file an Exec line runs, or ""."""
    try:
        parts = shlex.split(exec_line)
    except ValueError:
        parts = exec_line.split()
    for p in parts:
        if p.lower().endswith(".appimage") and os.path.isabs(p):
            return p
    return ""


@dataclass
class Removal:
    appimage: str                                         # the file (to the Trash)
    entries: List[str] = field(default_factory=list)      # .desktop files in your folder
    icons: List[str] = field(default_factory=list)
    others: List[str] = field(default_factory=list)       # file type definitions and the like
    blocked: List[str] = field(default_factory=list)      # entries outside your folder that start it
    settings: List[str] = field(default_factory=list)     # folders that look like its settings (opt-in)
    size: int = 0

    @property
    def files(self) -> List[str]:
        return self.entries + self.icons + self.others


def _same(a: str, b: str) -> bool:
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except OSError:
        return a == b


def _entries(env) -> Dict[str, Dict[str, str]]:
    """Every .desktop file (path -> its main group), user folder first."""
    out = {}
    for folder in de.application_dirs(env):
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.endswith(".desktop"):
                    path = os.path.join(root, name)
                    try:
                        out[path] = de.DesktopFile.load(path).group_dict()
                    except OSError:
                        continue
    return out


def _icon_files(name: str, data_dir: str) -> List[str]:
    """Files for an icon name in your own icon folders."""
    found = []
    for base in (os.path.join(data_dir, "icons"), os.path.join(data_dir, "pixmaps")):
        for root, _dirs, files in os.walk(base):
            for f in files:
                stem, ext = os.path.splitext(f)
                if stem == name and ext.lower() in ICON_EXTS:
                    found.append(os.path.join(root, f))
    return sorted(found)


def plan(app: de.App, env=None) -> Removal:
    env = os.environ if env is None else env
    path = appimage_of(app.exec)
    if not path:
        raise ValueError("%s doesn't start an AppImage." % app.name)
    data_dir = de.user_data_dir(env)
    user_apps = os.path.normpath(de.user_apps_dir(env))
    r = Removal(path)
    try:
        r.size = os.path.getsize(path)
    except OSError:
        pass

    all_entries = _entries(env)
    mine: Dict[str, Dict[str, str]] = {}
    for p, d in all_entries.items():
        target = appimage_of(de.unescape(d.get("Exec", "")))
        if target and _same(target, path):
            if os.path.normpath(p).startswith(user_apps + os.sep):
                mine[p] = d
            else:
                r.blocked.append(p)
    r.entries = sorted(mine)

    # Icons those entries use, unless another entry uses them too.
    others_use: Set[str] = {de.unescape(d.get("Icon", "")) for p, d in all_entries.items() if p not in mine}
    icons: List[str] = []
    for d in mine.values():
        icon = de.unescape(d.get("Icon", "")).strip()
        if not icon or icon in others_use:
            continue
        if os.path.isabs(icon):
            if icon.startswith(data_dir + os.sep) and os.path.isfile(icon):
                icons.append(icon)
        else:
            icons += _icon_files(icon, data_dir)
    # What appimaged / AppImageLauncher installed under the same appimagekit_ name.
    kits = {m.group(0) for p in mine for m in [_KIT.search(os.path.basename(p))] if m}
    for kit in kits:
        for base in (os.path.join(data_dir, "icons"), os.path.join(data_dir, "mime", "packages")):
            for root, _dirs, files in os.walk(base):
                for f in files:
                    if f.startswith(kit):
                        p = os.path.join(root, f)
                        (icons if base.endswith("icons") else r.others).append(p)
    r.icons = sorted(set(icons))
    r.others = sorted(set(r.others))
    r.settings = settings_folders(app.name, path, env)
    return r


def _names(app_name: str, path: str) -> Set[str]:
    """Names its settings folders are likely to have: Obsidian-1.6.2-x86_64.AppImage -> obsidian."""
    base = os.path.basename(path)[:-len(".appimage")]
    stem = re.split(r"[-_. ](?:v?\d|x86|amd64|aarch64|arm|linux)", base, maxsplit=1, flags=re.I)[0]
    names = {stem, app_name, app_name.replace(" ", ""), app_name.replace(" ", "-")}
    return {n.casefold() for n in names if len(n) >= 3}


# Folders that are never offered, whatever their name.
_KEEP = {"app-entries", "applications", "icons", "mime", "trash", "fonts", "themes", "autostart", "systemd",
         "flatpak", "gtk-3.0", "gtk-4.0", "dconf", "pulse", "fontconfig"}


def settings_folders(app_name: str, path: str, env=None) -> List[str]:
    """Folders in ~/.config, ~/.local/share and ~/.cache named like the app.
    Only a guess, so they're shown and removed only when asked."""
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    config = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    cache = env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    wanted = _names(app_name, path)
    found = []
    for base in (config, de.user_data_dir(env), cache):
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for e in entries:
            full = os.path.join(base, e)
            if e.casefold() in wanted and e.casefold() not in _KEEP and os.path.isdir(full) \
                    and not os.path.islink(full):
                found.append(full)
    return sorted(found)


def refresh_mime(env=None) -> None:
    """Rebuild your file-type cache after file types were removed or put back,
    when there is one to keep up to date."""
    mime = os.path.join(de.user_data_dir(env), "mime")
    tool = shutil.which("update-mime-database")
    if tool and os.path.isfile(os.path.join(mime, "mime.cache")):
        try:
            subprocess.run([tool, mime], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass


def changes(r: Removal, app_id: str, name: str) -> List[Change]:
    out = []
    for p in r.entries:
        out.append(Change(app_id, name, p, read_text(p), None, False))
    for p in r.icons + r.others:
        text_like = p.endswith((".svg", ".xml", ".xpm"))
        out.append(Change(app_id, name, p, read_text(p) if text_like else read_bytes(p), None, False))
    return out


def problem(r: Removal) -> Optional[str]:
    """Why the AppImage can't be removed, or None. (When the file is already
    gone, what was set up for it can still be removed.)"""
    if os.path.isfile(r.appimage) and not os.access(os.path.dirname(r.appimage), os.W_OK):
        return "The AppImage is in a folder you can't change (%s)." % os.path.dirname(r.appimage)
    return None
