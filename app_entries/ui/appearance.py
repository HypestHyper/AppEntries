"""Whether the desktop is in dark mode, and when that changes.

Asked in this order, first answer wins:
1. XDG Desktop Portal (org.freedesktop.appearance color-scheme)
2. GSettings (org.gnome.desktop.interface color-scheme)
3. GTK settings: gtk-application-prefer-dark-theme, or a theme name ending in "dark"
4. Light, as a default
"""
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


class ColorScheme:
    """Calls on_change() whenever the answer to is_dark() may have changed."""

    def __init__(self, on_change):
        self._cb = on_change
        self._portal = None    # 0 no preference, 1 dark, 2 light
        self._gsettings = None
        self._proxy = None

        # Read GTK's own setting now: the app sets it later to match its choice.
        gtk = Gtk.Settings.get_default()
        self._gtk_dark = bool(gtk and gtk.get_property("gtk-application-prefer-dark-theme"))
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
