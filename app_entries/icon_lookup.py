"""Find an app icon file when the current icon theme can't.

GTK only looks in the active icon theme and hicolor, and trusts a theme's
icon-theme.cache even when icons were added after it was built (Steam's game
icons, for one). Launchers often use another theme. So for icons GTK can't
find, look through the icon folders directly: hicolor, then every other
installed theme, then pixmaps. Pure Python, no GTK.
"""
import os
from typing import Dict, List, Optional

from .desktop_entries import user_data_dir

EXTENSIONS = (".svg", ".png", ".xpm")
# Largest first, so a launcher-sized icon is found before a tiny one.
SIZE_DIRS = (
    "scalable/apps", "512x512/apps", "256x256/apps", "128x128/apps", "96x96/apps",
    "64x64/apps", "48x48/apps", "32x32/apps", "24x24/apps", "22x22/apps", "16x16/apps",
    "apps/scalable", "apps/64", "apps/48", "apps/32",  # Breeze-style layout
    "256x256@2/apps", "128x128@2/apps", "64x64@2/apps", "48x48@2/apps",
)

_cache: Dict[str, Optional[str]] = {}


def data_dirs(env=None) -> List[str]:
    env = os.environ if env is None else env
    dirs = [d for d in (env.get("XDG_DATA_DIRS") or "").split(":") if os.path.isabs(d)]
    return [user_data_dir(env)] + (dirs or ["/usr/local/share", "/usr/share"])


def icon_bases(env=None) -> List[str]:
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    dirs = data_dirs(env)
    return [os.path.join(dirs[0], "icons"), os.path.join(home, ".icons")] + \
        [os.path.join(d, "icons") for d in dirs[1:]]


def _themes(bases: List[str], preferred) -> List[str]:
    found = []
    for base in bases:
        try:
            found += sorted(e.name for e in os.scandir(base) if e.is_dir())
        except OSError:
            continue
    order = [t for t in preferred if t] + ["hicolor"]
    return list(dict.fromkeys(order + found))


def find(name: str, preferred=(), env=None) -> Optional[str]:
    """Path of an icon file for this Icon= value, or None."""
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.isfile(name) else None
    key = "%s\0%s" % (name, ",".join(t for t in preferred if t))
    if key in _cache:
        return _cache[key]

    base_name, ext = os.path.splitext(name)
    if ext.lower() in EXTENSIONS:
        name = base_name
    bases = icon_bases(env)
    result = None
    for theme in _themes(bases, preferred):
        for base in bases:
            folder = os.path.join(base, theme)
            if not os.path.isdir(folder):
                continue
            for sub in SIZE_DIRS:
                for ext in EXTENSIONS:
                    path = os.path.join(folder, sub, name + ext)
                    if os.path.isfile(path):
                        result = path
                        break
                if result:
                    break
            if result:
                break
        if result:
            break
    if result is None:
        for d in data_dirs(env):
            for ext in EXTENSIONS:
                path = os.path.join(d, "pixmaps", name + ext)
                if os.path.isfile(path):
                    result = path
                    break
            if result:
                break
    _cache[key] = result
    return result


def clear_cache() -> None:
    _cache.clear()
