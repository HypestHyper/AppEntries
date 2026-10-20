"""The desktop's accent colour, from the files desktops and theme tools write.
Pure Python, no GTK; the portal (the main source on GNOME and KDE) is read
in ui/appearance.py.

- GTK theme files: ~/.config/gtk-4.0/gtk.css (and gtk-3.0), where Noctalia,
  matugen, wallust, pywal templates, Omarchy and most GTK themes define
  @define-color accent_color …, often in a file they @import.
- KDE: AccentColor in ~/.config/kdeglobals.
- GNOME before the portal had it: the named accent-color in GSettings.
"""
import os
import re
from typing import Dict, List, Optional, Tuple

# Names tried in order; the first defined one wins.
ACCENT_NAMES = ("accent_color", "accent_bg_color", "theme_selected_bg_color", "selected_bg_color")

# GNOME 47's named accents (org.gnome.desktop.interface accent-color).
GNOME_ACCENTS = {
    "blue": "#3584e4", "teal": "#2190a4", "green": "#3a944a", "yellow": "#c88800", "orange": "#ed5b00",
    "red": "#e62d42", "pink": "#d56199", "purple": "#9141ac", "slate": "#6f8396",
}

_NAMED = {"white": "#ffffff", "black": "#000000", "red": "#ff0000", "blue": "#0000ff", "green": "#008000",
          "orange": "#ffa500", "purple": "#800080", "pink": "#ffc0cb", "yellow": "#ffff00", "teal": "#008080",
          "gray": "#808080", "grey": "#808080"}


def config_home(env=None) -> str:
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    d = env.get("XDG_CONFIG_HOME") or ""
    return d if os.path.isabs(d) else os.path.join(home, ".config")


def parse_color(text: str, defines: Optional[Dict[str, str]] = None, _depth: int = 0) -> Optional[str]:
    """A CSS colour as #rrggbb: #rgb, #rrggbb, #rrggbbaa, rgb(), rgba(), a
    few names, or @other_name. None if it can't be read."""
    t = (text or "").strip().rstrip(";").strip()
    if not t or _depth > 8:
        return None
    if t.startswith("@") and defines is not None:
        ref = defines.get(t[1:].strip())
        return parse_color(ref, defines, _depth + 1) if ref else None
    m = re.fullmatch(r"#([0-9a-fA-F]{3,8})", t)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            return "#" + "".join(c * 2 for c in h[:3]).lower()
        if len(h) in (6, 8):
            return "#" + h[:6].lower()
        return None
    m = re.fullmatch(r"rgba?\(\s*([^)]*)\)", t)
    if m:
        parts = [p for p in re.split(r"[\s,/]+", m.group(1)) if p]
        if len(parts) < 3:
            return None
        vals = []
        for p in parts[:3]:
            try:
                v = float(p[:-1]) / 100 * 255 if p.endswith("%") else float(p)
            except ValueError:
                return None
            vals.append(max(0, min(255, round(v))))
        return "#%02x%02x%02x" % tuple(vals)
    return _NAMED.get(t.lower())


_DEFINE = re.compile(r"@define-color\s+([\w-]+)\s+([^;]+);")
_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?["']?([^"')\s;]+)["']?\s*\)?\s*;""")


def read_defines(path: str, _seen=None) -> Tuple[Dict[str, str], List[str]]:
    """@define-color values from a GTK CSS file and the files it imports, and
    every file read (to watch). Later definitions win, as in CSS."""
    seen = _seen if _seen is not None else []
    defines: Dict[str, str] = {}
    path = os.path.realpath(path)
    if path in seen or len(seen) > 20:
        return defines, seen
    seen.append(path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return defines, seen
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # Imports and definitions apply in the order they appear.
    for m in re.finditer(r"%s|%s" % (_IMPORT.pattern, _DEFINE.pattern), text):
        if m.group(0).startswith("@import"):
            target = m.group(1)
            if target.startswith("file://"):
                target = target[len("file://"):]
            target = os.path.expanduser(target)
            if not os.path.isabs(target):
                target = os.path.join(os.path.dirname(path), target)
            sub, _ = read_defines(target, seen)
            defines.update(sub)
        else:
            defines[m.group(2)] = m.group(3).strip()
    return defines, seen


def gtk_files(env=None) -> List[str]:
    home = config_home(env)
    return [os.path.join(home, "gtk-4.0", "gtk.css"), os.path.join(home, "gtk-3.0", "gtk.css")]


def gtk_accent(env=None) -> Tuple[Optional[str], str, List[str]]:
    """(colour, the file it came from, every file to watch)."""
    watch: List[str] = []
    for path in gtk_files(env):
        watch.append(path)
        defines, read = read_defines(path)
        watch += [p for p in read if p not in watch]
        for name in ACCENT_NAMES:
            if name in defines:
                color = parse_color(defines[name], defines)
                if color:
                    return color, path, watch
    return None, "", watch


def kde_accent(env=None) -> Optional[str]:
    """AccentColor=r,g,b from kdeglobals (Plasma)."""
    path = os.path.join(config_home(env), "kdeglobals")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"^\s*AccentColor\s*=\s*([^\n]+)$", text, flags=re.M)
    if not m:
        return None
    v = m.group(1).strip()
    if v.startswith("#"):
        return parse_color(v)
    parts = [p.strip() for p in v.split(",")]
    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
        return "#%02x%02x%02x" % tuple(min(255, int(p)) for p in parts[:3])
    return None


def portal_color(value) -> Optional[str]:
    """The portal's accent-color, (r, g, b) from 0 to 1. Values out of range
    mean the desktop has no accent set."""
    try:
        r, g, b = (float(x) for x in value[:3])
    except (TypeError, ValueError):
        return None
    if not all(0.0 <= c <= 1.0 for c in (r, g, b)):
        return None
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def prefers_portal(desktops: List[str]) -> bool:
    """On GNOME and KDE the desktop's own accent setting comes first. Elsewhere
    the portal often reports a default no one chose (the GTK backend says blue),
    so the colours written to GTK theme files win."""
    return any(d.upper() in ("GNOME", "KDE", "UNITY", "BUDGIE", "PANTHEON") for d in desktops)
