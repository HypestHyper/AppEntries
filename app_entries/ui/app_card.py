"""Shared pieces for showing apps: icons looked up in the background, badges,
sources, and the options menu for one app."""
import os
import queue
import threading
from gettext import gettext as _

from gi.repository import Gdk, Gio, GLib, Gtk

from .. import APP_ID, icon_lookup, packages, uninstall
from .widgets import glyph, icon, option_button, set_text, vbox


def N_(s):
    """Marks a string for translation; it's translated where it's shown."""
    return s


FALLBACK_ICON = "application-x-executable"


def gicon_for(name: str) -> Gio.Icon:
    """The current icon theme's icon if it has one, else a file found by
    searching the icon folders (other themes, pixmaps), else a generic icon."""
    if name and not os.path.isabs(name):
        base, ext = os.path.splitext(name)
        if ext.lower() in icon_lookup.EXTENSIONS:
            name = base
        display = Gdk.Display.get_default()
        theme = Gtk.IconTheme.get_for_display(display) if display else None
        if theme is not None and theme.has_icon(name):
            return Gio.ThemedIcon.new(name)
        current = theme.get_theme_name() if theme is not None else None
        path = icon_lookup.find(name, (current,))
    else:
        path = icon_lookup.find(name)
    if path:
        return Gio.FileIcon.new(Gio.File.new_for_path(path))
    return Gio.ThemedIcon.new(FALLBACK_ICON)


# Icons for the list, looked up off the main thread. The first lookup waits
# until the whole icon theme has loaded (about 0.4 s with Papirus), and ones
# the theme doesn't have are searched for in the icon folders; done here, the
# list appears at once and each icon fills in when it's found. GTK's icon
# theme allows lookups from other threads.
_found = {}       # icon name -> Gio.Icon
_waiting = {}     # icon name -> callbacks
_todo = queue.Queue()
_worker = []


def _look_up():
    while True:
        name = _todo.get()
        try:
            found = gicon_for(name)
        except Exception:  # noqa: BLE001 - a missing icon mustn't stop the rest
            found = Gio.ThemedIcon.new(FALLBACK_ICON)
        GLib.idle_add(_deliver, name, found)


def _deliver(name, found):
    _found[name] = found
    for cb in _waiting.pop(name, []):
        cb(found)
    return False


def gicon_later(name: str, apply) -> None:
    """apply(gicon) now if the icon is known, else once it's been found."""
    name = name or ""
    if name in _found:
        apply(_found[name])
        return
    _waiting.setdefault(name, []).append(apply)
    if len(_waiting[name]) == 1:
        _todo.put(name)
        if not _worker:
            t = threading.Thread(target=_look_up, daemon=True, name="icon lookups")
            _worker.append(t)
            t.start()


def forget_icons() -> None:
    """Look icons up again next time (after installs and removals)."""
    _found.clear()


class Badge(Gtk.Box):
    """A small labelled pill; its tooltip says what it means."""

    def __init__(self, icon_name="", text="", kind="neutral", tooltip=""):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, valign=Gtk.Align.CENTER,
                         halign=Gtk.Align.START)
        self.add_css_class("badge")
        self._icon = icon(icon_name or "info", ("filled",))
        self._label = Gtk.Label()
        self.append(self._icon)
        self.append(self._label)
        self._kind = ""
        self.set(icon_name, text, kind, tooltip)

    def set(self, icon_name, text, kind="neutral", tooltip=""):
        set_text(self._icon, glyph(icon_name))
        set_text(self._label, text)
        if kind != self._kind:
            if self._kind:
                self.remove_css_class(self._kind)
            self.add_css_class(kind)
            self._kind = kind
        if self.get_tooltip_text() != tooltip:
            self.set_tooltip_text(tooltip or None)


# icon, label, explanation (shown as the badge's tooltip)
SOURCES = {
    "system": ("computer", N_("System"), N_("Installed by your package manager ({manager}).")),
    "flatpak": ("package_2", N_("Flatpak"), N_("Installed as a Flatpak.")),
    "snap": ("package_2", N_("Snap"), N_("Installed as a Snap.")),
    "appimage": ("deployed_code", N_("AppImage"), N_("Starts an AppImage file rather than an installed program.")),
    "steam": ("sports_esports", N_("Steam"), N_("A game shortcut that Steam added to your applications folder.")),
    "distrobox": ("deployed_code", N_("Distrobox"), N_("Runs inside a Distrobox container, added to your menus "
                                                       "with distrobox-export.")),
    "webapp": ("language", N_("Web app"), N_("A site that opens in its own window, without the browser's address "
                                            "bar. Made with App Entries.")),
    "user": ("person", N_("Local"), N_("A launcher in your own applications folder (~/.local/share/applications), "
                                       "not installed by a package.")),
}


# What Uninstall does, by how the app was installed. Each shows the full list first.
UNINSTALL_HINTS = {
    "flatpak": N_("Removes the Flatpak and everything set up for it. Shows the full list first."),
    "snap": N_("Removes the snap with snap's own command, in your terminal. Shows the full list first."),
    "appimage": N_("Moves the AppImage to the Trash and removes its menu entries, icons and file types. Shows "
                   "the full list first."),
    "steam": N_("Asks Steam to uninstall the game, then removes its menu entry. Shows the full list first."),
    "distrobox": N_("Removes what distrobox-export added to your menus. Shows the full list first."),
    "package": N_("Removes its package with your package manager, in your terminal. Shows what else goes, and "
                  "which apps need it, first."),
}


def label_for_source(key):
    """What a source is called in the UI; system apps are named after the
    package manager, like pacman or apt."""
    if key == "system":
        return packages.system_manager() or _("System")
    return _(SOURCES[key][1])


def _source_tip(key):
    tip = _(SOURCES[key][2])
    return tip.format(manager=packages.system_manager() or _("unknown")) if key == "system" else tip


def menu_box(a, act, hide_item=False):
    """The options for one app, for its ⋯ menu or right-click menu. `act(name)`
    returns the callback for an action name; `hide_item` adds Hide or Show and
    Open at the top."""
    box = vbox(2)
    box.set_size_request(300, -1)
    if hide_item:
        is_self = a.id == APP_ID + ".desktop" and not a.hidden
        if not is_self:
            box.append(option_button(
                "visibility" if a.hidden else "visibility_off", _("Show") if a.hidden else _("Hide"),
                (_("Shows it in launcher menus again.") if a.hidden else
                 _("Keeps it out of launcher menus. It still opens files and links.")), act("toggle-hidden")))
        if not (a.missing or a.uninstalled):
            box.append(option_button("play_arrow", _("Open"), _("Starts the app."), act("launch")))
    box.append(option_button(
        "edit_note", _("Edit…"),
        (_("Change what it runs, its name, icon and folders. Nothing is saved until you press Save.")
         if a.created else
         _("Change the name, icon, command and where it appears. Nothing is saved until you press Save.")),
        act("edit")))
    if a.created:
        box.append(option_button(
            "content_copy", _("Duplicate"),
            _("Makes a new launcher with the same settings, named “(copy)”, to change from there."),
            act("duplicate")))
    if a.has_override and a.system:
        box.append(option_button(
            "restart_alt", _("Restore original"),
            _("Deletes your file for this app, so the version installed by the system is used again. "
              "You can undo this."), act("restore")))
    if a.source == "webapp":
        box.append(option_button(
            "delete", _("Delete this web app"),
            _("Deletes this web app from your menus. Your browser and its sign-ins aren't touched. "
              "You can undo this."), act("delete"), danger=True))
    elif (a.source == "user" or a.created) and a.override_path and not a.override_managed:
        box.append(option_button(
            "delete", _("Delete this launcher"),
            _("Deletes this launcher file from your applications folder. "
              "The program itself isn't touched. You can undo this."), act("delete"), danger=True))
    if a.mime_types:
        box.append(option_button(
            "star", _("File types…"),
            _("The file types it opens, and which of them open with it by default. Opens Default apps."),
            act("file-types")))
    box.append(option_button(
        "open_in_new", _("Helper apps…"),
        _("Shortcuts to apps that change its permissions, versions or setup, like Flatseal. Each opens that "
          "app."), act("helpers")))
    kind = uninstall.kind_of(a)
    if kind:
        box.append(option_button(
            "delete_forever", _("Uninstall {name}…").format(name=a.name),
            _(UNINSTALL_HINTS[kind]), act("uninstall"), danger=True))
    box.append(option_button(
        "folder_open", _("Open file location"),
        _("Opens the folder that holds this app's entry file in your file manager."), act("open-folder")))
    return box
