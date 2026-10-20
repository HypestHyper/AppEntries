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

from . import APP_ID, APP_NAME, VERSION, theme  # noqa: E402

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
        self.accent_listeners = []   # called when the desktop's accent changes
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
        from .ui.appearance import DesktopAccent
        self.desktop_accent = DesktopAccent(self._on_desktop_accent)
        size = self.settings.get("size")
        self.style = Style(self.seed(), "default" if size == "auto" else size, self._want_dark(),
                           self._preset())
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
        self._update_app_icon()

    def _preset(self):
        p = self.settings.get("palette")
        return p if p in theme.PRESETS else ""

    def seed(self):
        """The accent to use, as six hex digits, or "" for the palette's own.
        The accent setting is a colour, "desktop" or "palette"."""
        accent, preset = self.settings.get("accent"), self._preset()
        if accent == "desktop":
            color, _where = self.desktop_accent.value()
            if color:
                return color.lstrip("#")
            return "" if preset else theme.DEFAULT_SEED
        if accent == "palette":
            return "" if preset else theme.DEFAULT_SEED
        return theme.valid_seed(accent)

    def effective_seed(self):
        """The accent actually shown, for the app icon."""
        return self.seed() or theme.preset_accent(self._preset(), self._want_dark())

    def _on_desktop_accent(self):
        if self.settings.get("accent") == "desktop":
            self.style.recolor(self.seed())
            self._update_app_icon()
        for cb in list(self.accent_listeners):
            cb()

    def _on_setting(self, key):
        if key == "theme":
            self.style.recolor(dark=self._want_dark())
        elif key in ("accent", "palette"):
            self.style.recolor(self.seed(), preset=self._preset())
            self._update_app_icon()
        elif key == "themed-icon":
            self._update_app_icon()
        elif key == "reduce-motion":
            self.style.set_reduce_motion(self.settings.get("reduce-motion"))

    def _update_app_icon(self):
        from . import app_icon
        from .ui.dialogs import run_bg
        seed, themed = self.effective_seed(), self.settings.get("themed-icon")
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
