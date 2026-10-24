"""Shortcuts to the apps people use after installing something: Flatseal
for a Flatpak's permissions, Gear Lever for AppImages, ProtonUp-Qt for
Steam games, and so on. App Entries only opens them, pointed at the app
where the helper allows it; it doesn't do their job itself. Pure Python,
no GTK.

A helper that isn't installed is listed with what it does and the
command that installs it from Flathub, which runs only if the user asks.
"""
import glob
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Set, Tuple

from . import desktop_entries as de


@dataclass
class Shortcut:
    key: str
    name: str                    # the helper's name
    what: str                    # what it does for this app
    icon: str
    installed: bool
    # How to open it: ("desktop", desktop ID, [files]), ("argv", [words]),
    # ("uri", uri), ("flatseal", desktop ID, app ID) or ("kde-permissions", app ID).
    action: Tuple = ()
    install: List[str] = field(default_factory=list)   # the command that installs it, if it's missing
    flathub: str = ""            # its Flathub ID


@dataclass
class Helper:
    key: str
    name: str
    flathub: str                 # Flathub ID; its desktop ID is this + ".desktop"
    kinds: Tuple[str, ...]       # the uninstall kinds it's for (see uninstall.kind_of)
    what: str
    other_ids: Tuple[str, ...] = ()   # desktop IDs of other packagings


HELPERS = [
    Helper("flatseal", "Flatseal", "com.github.tchx84.Flatseal", ("flatpak",),
           "See and change what {name} can reach: files, devices, network, Wayland or X11, and environment "
           "variables. Opens on {name}."),
    Helper("warehouse", "Warehouse", "io.github.flattool.Warehouse", ("flatpak",),
           "Manage Flatpaks: go back to an older version, pin one, or clear an app's data."),
    Helper("gearlever", "Gear Lever", "it.mijorus.gearlever", ("appimage",),
           "Keep AppImages in one folder, add them to menus and update them. Opens with {name}'s AppImage."),
    Helper("protonup", "ProtonUp-Qt", "net.davidotek.pupgui2", ("steam",),
           "Install other versions of Proton, like Proton-GE, to pick for a game in Steam."),
    Helper("protontricks", "Protontricks", "com.github.Matoking.protontricks", ("steam",),
           "Install Windows parts (fonts, runtimes) into a game's Proton setup.", ("protontricks.desktop",)),
    Helper("boxbuddy", "BoxBuddy", "io.github.dvlv.boxbuddyrs", ("distrobox",),
           "Manage Distrobox containers: open a terminal in one, upgrade it, or export more apps."),
    Helper("distroshelf", "DistroShelf", "com.ranfdev.DistroShelf", ("distrobox",),
           "Manage Distrobox containers and the apps exported from them."),
]

KDE_PERMISSION_MODULES = ("kcm_app-permissions", "kcm_flatpak")


def _kde_module(env) -> str:
    """The KDE Flatpak permissions page that's installed, or ""."""
    for base in ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu"):
        for name in KDE_PERMISSION_MODULES:
            if glob.glob(os.path.join(base, "qt6", "plugins", "plasma", "kcms", "systemsettings", name + ".so")):
                return name
    return ""


def for_app(app: de.App, kind: str, installed_ids: Set[str], env=None, which: Callable = shutil.which,
            uri_handler: Callable[[str], str] = lambda scheme: "", appimage: str = "", steam_id: str = "",
            flatpak_id: str = "", snap_name: str = "", kde_module: Optional[str] = None) -> List[Shortcut]:
    """The shortcuts that fit this app. `uri_handler(scheme)` names the app
    that opens that kind of link ("" if none)."""
    env = os.environ if env is None else env
    out: List[Shortcut] = []
    stem = app.id[:-len(".desktop")]
    have_flatpak = bool(which("flatpak"))

    for h in HELPERS:
        if kind not in h.kinds:
            continue
        did = next((d for d in (h.flathub + ".desktop",) + h.other_ids if d in installed_ids), "")
        what = h.what.format(name=app.name)
        if not did:
            if have_flatpak:
                out.append(Shortcut(h.key, h.name, what, h.flathub, False, (),
                                    ["flatpak", "install", "flathub", h.flathub], h.flathub))
            continue
        if h.key == "flatseal":
            action = ("flatseal", did, flatpak_id or stem)
        elif h.key == "gearlever" and appimage:
            action = ("desktop", did, [appimage])
        else:
            action = ("desktop", did, [])
        out.append(Shortcut(h.key, h.name, what, h.flathub, True, action, flathub=h.flathub))

    desktops = [d.upper() for d in de.current_desktops(env)]
    if which("gnome-control-center") and any(d in ("GNOME", "UNITY", "UBUNTU") for d in desktops):
        out.append(Shortcut("gnome-settings", "Settings", "{name}'s permissions, notifications, storage and the "
                            "files it opens, in GNOME Settings.".format(name=app.name), "org.gnome.Settings", True,
                            ("argv", ["gnome-control-center", "applications", stem])))
    module = _kde_module(env) if kde_module is None else kde_module
    if kind == "flatpak" and module and (which("kcmshell6") or which("systemsettings")) and "KDE" in desktops:
        out.append(Shortcut("kde-permissions", "System Settings", "{name}'s Flatpak permissions, in KDE's "
                            "System Settings.".format(name=app.name), "preferences-system", True,
                            ("kde-permissions", flatpak_id or stem, module)))

    store = uri_handler("appstream")
    if store and kind in ("flatpak", "package"):
        out.append(Shortcut("software", store, "{name}'s page in {store}: details, updates and, for Flatpaks, "
                            "permissions.".format(name=app.name, store=store), "system-software-install", True,
                            ("uri", "appstream://" + (flatpak_id or stem))))
    snap_store = uri_handler("snap")
    if kind == "snap" and snap_store and snap_name:
        out.append(Shortcut("snap-store", snap_store, "{name}'s page in {store}, with its permissions."
                            .format(name=app.name, store=snap_store), "snap-store", True,
                            ("uri", "snap://" + snap_name)))
    if kind == "steam" and steam_id:
        out.append(Shortcut("steam", "Steam", "The game's page in your Steam library: properties, Proton version "
                            "and launch options.", "steam", True,
                            ("uri", "steam://nav/games/details/" + steam_id)))
    # Installed helpers first.
    out.sort(key=lambda s: not s.installed)
    return out


def kde_argv(app_id: str, ref: str, module: str, which: Callable = shutil.which) -> List[str]:
    """Opens KDE's Flatpak permissions on one app (by its ref, like
    app/org.x.App/x86_64/stable)."""
    if which("kcmshell6"):
        return ["kcmshell6", module, "--args", ref or app_id]
    return ["systemsettings", module, "--args", ref or app_id]


def installed_ids(apps: Sequence[de.App]) -> Set[str]:
    return {a.id for a in apps}
