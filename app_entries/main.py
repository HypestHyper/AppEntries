"""Application entry point."""
import gettext
import locale
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION  # noqa: E402

DOMAIN = "app-entries"
HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_ROOT = os.path.dirname(HERE)  # the repository root when run from a checkout


def setup_i18n(localedir=None):
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    localedir = localedir or os.environ.get("APP_ENTRIES_LOCALEDIR")
    gettext.bindtextdomain(DOMAIN, localedir)
    gettext.textdomain(DOMAIN)


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.add_main_option("version", ord("v"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             gettext.gettext("Print the version and exit"), None)
        self.window = None
        self.settings = None
        self.style = None

    def do_handle_local_options(self, options):
        if options.contains("version"):
            print("%s %s" % (APP_NAME, VERSION))
            return 0
        return -1

    def do_startup(self):
        Gtk.Application.do_startup(self)
        from .settings import Settings
        from .ui import fonts
        from .ui.appearance import ColorScheme
        from .ui.style import Style

        fonts.register()
        dev_icons = os.path.join(SOURCE_ROOT, "data", "icons")
        if os.path.isdir(dev_icons):
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(dev_icons)
        Gtk.Window.set_default_icon_name(APP_ID)

        self.settings = Settings()
        self.scheme = ColorScheme(self._on_scheme_changed)
        size = self.settings.get("size")
        self.style = Style(self.settings.get("accent"), "default" if size == "auto" else size,
                           self._want_dark())
        self.style.set_reduce_motion(self.settings.get("reduce-motion"))
        self.settings.connect(self._on_setting)
        self._update_app_icon()
        from .ui.updates import UpdateManager
        self.updates = UpdateManager(self, self.settings)

        for name, cb, accels in (
            ("refresh", lambda *_: self.window and self.window.rescan(), ["<Control>r", "F5"]),
            ("preferences", self._on_preferences, ["<Control>comma"]),
            ("updates", self._on_updates, []),
            ("quit", lambda *_: self.quit(), ["<Control>q"]),
        ):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
            if accels:
                self.set_accels_for_action("app." + name, accels)
        self.set_accels_for_action("win.search", ["<Control>f"])
        self.set_accels_for_action("win.new-launcher", ["<Control>n"])
        self.set_accels_for_action("win.new-web-app", ["<Control><Shift>n"])
        self.set_accels_for_action("win.history", ["<Control>h"])
        self.set_accels_for_action("win.undo-last", ["<Control>z"])
        for i, key in enumerate(("all", "hidden", "customised", "issues", "mine", "autostart", "defaults",
                                 "settings", "updates"), 1):
            self.set_accels_for_action("win.filter::" + key, ["<Alt>%d" % i])

    def do_activate(self):
        if self.window is None:
            from .ui.app import MainWindow
            self.window = MainWindow(self, self.settings, self.style)
            self.updates.startup()
        self.window.present()

    def _want_dark(self):
        choice = self.settings.get("theme")
        return self.scheme.is_dark() if choice == "system" else choice == "dark"

    def _on_scheme_changed(self):
        self.style.recolor(dark=self._want_dark())

    def _on_setting(self, key):
        if key == "theme":
            self.style.recolor(dark=self._want_dark())
        elif key == "accent":
            self.style.recolor(self.settings.get("accent"))
            self._update_app_icon()
        elif key == "themed-icon":
            self._update_app_icon()
        elif key == "reduce-motion":
            self.style.set_reduce_motion(self.settings.get("reduce-motion"))

    def _update_app_icon(self):
        from . import app_icon
        from .ui.dialogs import run_bg
        seed, themed = self.settings.get("accent"), self.settings.get("themed-icon")
        run_bg(lambda: app_icon.update(seed, themed))

    def _show_tab(self, key):
        if self.window is None:
            self.activate()
        self.settings.set("filter", key)
        self.window.present()

    def _on_preferences(self, *_):
        self._show_tab("settings")

    def _on_updates(self, *_):
        self._show_tab("updates")


def main(argv=None):
    setup_i18n()
    from . import cli
    if cli.wants_cli(sys.argv if argv is None else argv):
        return cli.main(sys.argv if argv is None else argv)
    # X11 WM_CLASS and the Wayland app ID both match StartupWMClass this way.
    GLib.set_prgname(APP_ID)
    return Application().run(sys.argv if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
