"""App icon that follows the accent colour.

Launchers can't restyle an app icon, so the app writes its own icon, coloured
from the current accent, to the user's icon folder and rewrites it when the
accent changes. The shipped icon (data/icons/, made by render() with the
default colours) is the fallback until the app first runs.
"""
import os
import shutil

from . import APP_ID, desktop_entries, theme

# Marks icons written by the app, so uninstall.sh only removes its own copy.
MARKER = "App Entries accent icon"


def colors_for(seed):
    """A gentle top-to-bottom gradient in the accent's hue, deep enough to
    read on both light and dark panels."""
    return theme.tone(seed, 0.56), theme.tone(seed, 0.42)


def render(seed=theme.DEFAULT_SEED, marker=True):
    """Two tiles, a dashed (hidden) tile and a plus, in outlines."""
    top, bottom = colors_for(seed)
    note = "  <!-- %s -->\n" % MARKER if marker else ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">\n'
        "  <title>App Entries</title>\n"
        + note +
        '  <defs><linearGradient id="g" x1="0" y1="14" x2="0" y2="114" gradientUnits="userSpaceOnUse">'
        '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/>'
        "</linearGradient></defs>\n"
        '  <g fill="none" stroke="url(#g)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round">\n'
        '    <rect x="18" y="18" width="38" height="38" rx="12"/>\n'
        '    <rect x="72" y="18" width="38" height="38" rx="19"/>\n'
        '    <rect x="18" y="72" width="38" height="38" rx="19" stroke-dasharray="9 9"/>\n'
        '    <path d="M91 76v30M76 91h30"/>\n'
        "  </g>\n"
        "</svg>\n" % (top, bottom)
    )


def _icons_dir():
    return os.path.join(desktop_entries.user_data_dir(), "icons", "hicolor")


def is_installed():
    """Only manage the icon for an installed app, not a source checkout."""
    return any(os.path.isfile(os.path.join(d, APP_ID + ".desktop"))
               for d in desktop_entries.application_dirs())


def update(seed, themed=True):
    """Write the icon if it changed. Safe to call on every accent change."""
    if not is_installed():
        return
    svg = render(seed if themed else theme.DEFAULT_SEED)
    target = os.path.join(_icons_dir(), "scalable", "apps", APP_ID + ".svg")
    try:
        with open(target, encoding="utf-8") as f:
            if f.read() == svg:
                return
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(svg)
        os.replace(tmp, target)
    except OSError as err:
        print("app-entries: couldn't update the app icon: %s" % err)
        return
    _refresh_cache(_icons_dir())


def _refresh_cache(theme_dir):
    if not os.path.exists(os.path.join(theme_dir, "icon-theme.cache")):
        return  # no cache: icon lookups read the folder directly
    tool = shutil.which("gtk4-update-icon-cache") or shutil.which("gtk-update-icon-cache")
    if tool is None:
        return
    from gi.repository import Gio, GLib
    try:
        Gio.Subprocess.new([tool, "-q", "-t", "-f", theme_dir], Gio.SubprocessFlags.NONE)
    except GLib.Error:
        pass
