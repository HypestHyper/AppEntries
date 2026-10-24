"""Whether the desktop is in dark mode, and when that changes.

Asked in this order, first answer wins:
1. XDG Desktop Portal (org.freedesktop.appearance color-scheme)
2. GSettings (org.gnome.desktop.interface color-scheme)
3. GTK settings: gtk-application-prefer-dark-theme, or a theme name ending in "dark"
4. Light, as a default
"""
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk

PORTAL = ("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
          "org.freedesktop.portal.Settings")
NAMESPACE, KEY = "org.freedesktop.appearance", "color-scheme"


def _unwrap(value):
    while isinstance(value, GLib.Variant):
        value = value.unpack()
    if isinstance(value, tuple) and len(value) == 1:
        return _unwrap(value[0])
    return value


def _new_scheme_setting(settings) -> bool:
    """GTK 4.20 replaced gtk-application-prefer-dark-theme with this."""
    return hasattr(Gtk, "InterfaceColorScheme") and settings.find_property("gtk-interface-color-scheme") is not None


def gtk_prefers_dark(settings) -> bool:
    if settings is None:
        return False
    if _new_scheme_setting(settings):
        return settings.get_property("gtk-interface-color-scheme") == Gtk.InterfaceColorScheme.DARK
    return bool(settings.get_property("gtk-application-prefer-dark-theme"))


def set_gtk_dark(settings, dark: bool) -> None:
    if settings is None:
        return
    if _new_scheme_setting(settings):
        scheme = Gtk.InterfaceColorScheme.DARK if dark else Gtk.InterfaceColorScheme.LIGHT
        settings.set_property("gtk-interface-color-scheme", scheme)
    else:
        settings.set_property("gtk-application-prefer-dark-theme", dark)


class ColorScheme:
    """Calls on_change() whenever the answer to is_dark() may have changed."""

    def __init__(self, on_change):
        self._cb = on_change
        self._portal = None    # 0 no preference, 1 dark, 2 light
        self._gsettings = None
        self._proxy = None

        # Read GTK's own setting now: the app sets it later to match its choice.
        gtk = Gtk.Settings.get_default()
        self._gtk_dark = gtk_prefers_dark(gtk)
        if gtk is not None:
            gtk.connect("notify::gtk-theme-name", lambda *_: self._cb())

        try:
            self._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None, *PORTAL, None)
            reply = self._proxy.call_sync("Read", GLib.Variant("(ss)", (NAMESPACE, KEY)),
                                          Gio.DBusCallFlags.NONE, 500, None)
            self._portal = int(_unwrap(reply))
            self._proxy.connect("g-signal", self._on_portal_signal)
        except (GLib.Error, TypeError, ValueError):
            self._proxy = None

        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup("org.gnome.desktop.interface", True) if source else None
        if schema is not None and schema.has_key("color-scheme"):
            self._gsettings = Gio.Settings.new("org.gnome.desktop.interface")
            self._gsettings.connect("changed::color-scheme", lambda *_: self._cb())

    def _on_portal_signal(self, _proxy, _sender, signal, params):
        if signal != "SettingChanged":
            return
        ns, key, value = params.unpack()
        if ns == NAMESPACE and key == KEY:
            try:
                self._portal = int(_unwrap(value))
            except (TypeError, ValueError):
                return
            self._cb()

    def is_dark(self) -> bool:
        if self._portal in (1, 2):
            return self._portal == 1
        if self._gsettings is not None:
            scheme = self._gsettings.get_string("color-scheme")
            if scheme in ("prefer-dark", "prefer-light"):
                return scheme == "prefer-dark"
        if self._gtk_dark:
            return True
        gtk = Gtk.Settings.get_default()
        name = (gtk.get_property("gtk-theme-name") or "") if gtk else ""
        return name.lower().endswith("dark")


class DesktopAccent:
    """The desktop's accent colour, kept up to date. Calls on_change() when it
    may have changed. See desktop_colors for where it comes from."""

    def __init__(self, on_change):
        from .. import desktop_colors as dc
        from .. import desktop_entries as de
        self._dc = dc
        self._cb = on_change
        self._portal = None
        self._gnome = None
        self._monitors = {}
        self._timer = 0
        self._prefer_portal = dc.prefers_portal(de.current_desktops())

        try:
            self._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None, *PORTAL, None)
            reply = self._proxy.call_sync("Read", GLib.Variant("(ss)", (NAMESPACE, "accent-color")),
                                          Gio.DBusCallFlags.NONE, 500, None)
            self._portal = dc.portal_color(_unwrap(reply))
            self._proxy.connect("g-signal", self._on_portal_signal)
        except (GLib.Error, TypeError, ValueError):
            self._proxy = None

        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup("org.gnome.desktop.interface", True) if source else None
        if schema is not None and schema.has_key("accent-color"):
            self._gnome = Gio.Settings.new("org.gnome.desktop.interface")
            self._gnome.connect("changed::accent-color", lambda *_: self._changed())
        self._watch()

    # -- sources --------------------------------------------------------------

    def _on_portal_signal(self, _proxy, _sender, signal, params):
        if signal != "SettingChanged":
            return
        ns, key, value = params.unpack()
        if ns == NAMESPACE and key == "accent-color":
            self._portal = self._dc.portal_color(_unwrap(value))
            self._changed()

    def _gnome_named(self):
        if self._gnome is None:
            return None
        return self._dc.GNOME_ACCENTS.get(self._gnome.get_string("accent-color"))

    def value(self):
        """(#rrggbb, where it came from in plain words), or (None, "") when
        the desktop doesn't say."""
        dc = self._dc
        gtk, path, _watch = dc.gtk_accent()
        home = GLib.get_home_dir()
        short = ("~" + path[len(home):]) if path.startswith(home) else path
        sources = [
            (self._portal, _("your desktop's accent setting")),
            (gtk, short),
            (dc.kde_accent(), "kdeglobals"),
            (self._gnome_named(), _("GNOME's accent setting")),
        ]
        if not self._prefer_portal:
            sources[0], sources[1] = sources[1], sources[0]
        for color, where in sources:
            if color:
                return color, where
        return None, ""

    # -- watching files -------------------------------------------------------

    def _watch(self):
        """Watch the GTK theme files (and the ones they import) and kdeglobals,
        including ones that don't exist yet."""
        _c, _p, files = self._dc.gtk_accent()
        files = list(files) + [GLib.build_filenamev([self._dc.config_home(), "kdeglobals"])]
        for path in files:
            if path in self._monitors:
                continue
            try:
                m = Gio.File.new_for_path(path).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
            except GLib.Error:
                continue
            m.connect("changed", lambda *_a: self._changed())
            self._monitors[path] = m

    def _changed(self):
        # Theme tools often write several files in a row: wait for them to finish.
        if self._timer:
            GLib.source_remove(self._timer)

        def fire():
            self._timer = 0
            self._watch()   # an @import may point somewhere new
            self._cb()
            return False

        self._timer = GLib.timeout_add(250, fire)
