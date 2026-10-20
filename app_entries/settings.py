"""Preferences, stored in GSettings when the schema is installed.

When running from a source checkout without an installed schema, values
fall back to a JSON file in $XDG_CONFIG_HOME/io.github.HypestHyper.AppEntries/.
"""
import json
import os

from gi.repository import Gio, GLib

from . import APP_ID

DEFAULTS = {
    "filter": "all",            # all | hidden | system
    "show-no-display": True,
    "show-hidden": True,
    "source": "any",            # any, system, flatpak, snap, appimage, steam or user
    "theme": "system",          # system | light | dark
    "accent": "53dbb0",         # six hex digits, "desktop" or "palette"
    "palette": "generated",     # generated, or one of theme.PRESETS
    "themed-icon": True,
    "size": "auto",             # auto | compact | default | large
    "reduce-motion": False,
    "window-controls": True,
    "window-width": 1100,
    "window-height": 760,
    "maximized": False,
    "check-updates": True,
    "update-notify": True,
    "update-test": False,
    "last-update-check": 0,
    "latest-version": "",
    "recent-colors": [],
}


def _schema_source():
    """The default source, plus a compiled schema dir next to the sources."""
    default = Gio.SettingsSchemaSource.get_default()
    extra = os.environ.get("APP_ENTRIES_SCHEMA_DIR")
    if extra and os.path.exists(os.path.join(extra, "gschemas.compiled")):
        try:
            return Gio.SettingsSchemaSource.new_from_directory(extra, default, False)
        except GLib.Error:
            pass
    return default


class Settings:
    def __init__(self):
        self._listeners = []
        self._gs = None
        src = _schema_source()
        schema = src.lookup(APP_ID, True) if src else None
        if schema is not None:
            self._gs = Gio.Settings.new_full(schema, None, None)
            self._gs.connect("changed", lambda _s, key: self._notify(key))
            self.backend = "gsettings"
        else:
            self._path = os.path.join(GLib.get_user_config_dir(), APP_ID, "settings.json")
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._data = {k: v for k, v in json.load(f).items() if k in DEFAULTS}
            except (OSError, ValueError):
                self._data = {}
            self.backend = "json"

    def get(self, key):
        if self._gs is not None:
            return self._gs.get_value(key).unpack()
        return self._data.get(key, DEFAULTS[key])

    def set(self, key, value):
        if self.get(key) == value:
            return
        if self._gs is not None:
            self._gs.set_value(key, GLib.Variant(self._gs.get_value(key).get_type_string(), value))
            return
        self._data[key] = value
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=1)
        except OSError:
            pass
        self._notify(key)

    def connect(self, cb):
        """cb(key) after any change."""
        self._listeners.append(cb)

    def _notify(self, key):
        for cb in self._listeners:
            cb(key)
