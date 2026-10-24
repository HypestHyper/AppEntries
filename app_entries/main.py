"""Application entry point."""
from . import timing  # noqa: I001 - first, so its clock starts early
import gettext
import locale
import os
import sys

# GTK's GL renderer starts faster than Vulkan, which newer GTK versions use
# by default (about a tenth of a second on some machines). GSK_RENDERER
# still chooses another.
_OUR_RENDERER = "GSK_RENDERER" not in os.environ
os.environ.setdefault("GSK_RENDERER", "ngl")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION, theme  # noqa: E402

# GTK 4.20 (4.19.2) renamed its GL renderer from "ngl" to "gl", and warns
# about the old name. The renderer is only picked when the window is
# shown, so this is still in time.
if _OUR_RENDERER and (Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()) >= (4, 19, 2):
    os.environ["GSK_RENDERER"] = "gl"

timing.mark("Python and GTK loaded")

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
        # There are no bundled GResources. Without a base path GtkApplication
        # doesn't add an icon search path for them at start-up, which waits
        # for the whole icon theme to load (a quarter of a second with
        # Papirus) before anything else can happen.
        self.set_resource_base_path(None)
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
        timing.mark("GTK started")
        Gtk.Application.do_startup(self)
        timing.mark("GtkApplication start-up")
        # Asking for the icon theme starts loading it on another thread, so
        # it's ready by the time the list shows app icons. Nothing before
        # the first frame looks an icon up, so nothing waits for it.
        from gi.repository import Gdk
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        from .settings import Settings
        from .ui import fonts
        from .ui.appearance import ColorScheme
        from .ui.style import Style

        fonts.register()
        timing.mark("  fonts")

        self.settings = Settings()
        timing.mark("  settings")
        self.scheme = ColorScheme(self._on_scheme_changed)
        timing.mark("  light or dark (portal)")
        from .ui.appearance import DesktopAccent
        self.desktop_accent = DesktopAccent(self._on_desktop_accent)
        timing.mark("  desktop accent")
        size = self.settings.get("size")
        self.style = Style(self.seed(), "default" if size == "auto" else size, self._want_dark(),
                           self._preset())
        self.style.set_reduce_motion(self.settings.get("reduce-motion"))
        timing.mark("  styles")
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
        timing.mark("settings, fonts and styles")
        self.set_accels_for_action("win.search", ["<Control>f"])
        self.set_accels_for_action("win.new-launcher", ["<Control>n"])
        self.set_accels_for_action("win.new-web-app", ["<Control><Shift>n"])
        self.set_accels_for_action("win.history", ["<Control>h"])
        self.set_accels_for_action("win.undo-last", ["<Control>z"])
        for i, key in enumerate(("all", "hidden", "customised", "issues", "mine", "autostart", "defaults",
                                 "settings", "updates"), 1):
            self.set_accels_for_action("win.filter::" + key, ["<Alt>%d" % i])

    def do_activate(self):
        first = self.window is None
        if first:
            from .ui.app import MainWindow
            timing.mark("window code loaded")
            self.window = MainWindow(self, self.settings, self.style)
            timing.mark("window built")
            self.window.connect("realize", self._watch_first_frame)
            # Creating the window looks up its icon, which waits for the whole
            # icon theme (a third of a second with Papirus on Wayland). The
            # icon is given back once the window is up.
            self._icon_unset = _unset_default_icon()
            if timing.ON:
                self.window.connect("map", lambda *_a: timing.mark("  window mapped"))
        self.window.present()
        if first:
            timing.mark("window shown")
            GLib.idle_add(lambda: (self.updates.startup(), False)[1])

    def _watch_first_frame(self, window):
        if timing.ON:
            native = window.get_renderer() if hasattr(window, "get_renderer") else None
            timing.mark("  window created, renderer ready (%s, icon %s)" % (
                type(native).__name__ if native is not None else "?",
                "skipped" if getattr(self, "_icon_unset", False) else "looked up"))
        clock = window.get_frame_clock()
        if clock is None:
            return
        handler = []
        steps = []
        if timing.ON:
            # The first frame's stages, each marked once.
            for signal, name, after in (("layout", "  laying out begins", False),
                                        ("paint", "  laid out, drawing begins", False)):
                def once(*_a, name=name):
                    if name not in steps:
                        steps.append(name)
                        timing.mark(name)
                (clock.connect_after if after else clock.connect)(signal, once)

        def painted(*_a):
            clock.disconnect(handler[0])
            timing.mark("first frame")
            self.after_first_frame()
            if timing.QUIT == "1":
                GLib.idle_add(lambda: (self.quit(), False)[1])

        handler.append(clock.connect("after-paint", painted))

    def after_first_frame(self):
        """Work that can wait until the window is on screen."""
        if getattr(self, "_icon_unset", False):
            Gtk.Window.set_default_icon_name(APP_ID)   # GTK gives it to the open window too
        if self.window is not None:
            self.window.after_first_frame()

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
        if self.window is not None:
            self.window.refresh_logo()

    def _show_tab(self, key):
        if self.window is None:
            self.activate()
        self.settings.set("filter", key)
        self.window.present()

    def _on_preferences(self, *_):
        self._show_tab("settings")

    def _on_updates(self, *_):
        self._show_tab("updates")


def _unset_default_icon() -> bool:
    """Clear the default window icon name (PyGObject won't pass None here).
    Returns whether it worked."""
    try:
        import ctypes
        for lib in (None, "libgtk-4.so.1"):
            try:
                fn = ctypes.CDLL(lib).gtk_window_set_default_icon_name
                break
            except (OSError, AttributeError):
                continue
        else:
            return False
        fn.argtypes = [ctypes.c_char_p]
        fn.restype = None
        fn(None)
        return Gtk.Window.get_default_icon_name() is None
    except Exception:  # noqa: BLE001 - only an optimisation
        return False


def main(argv=None):
    setup_i18n()
    args = sys.argv if argv is None else argv
    # The command line's code loads only when an option asks for it.
    if any(a.startswith("-") for a in args[1:]):
        from . import cli
        if cli.wants_cli(args):
            return cli.main(args)
    # X11 WM_CLASS and the Wayland app ID both match StartupWMClass this way.
    GLib.set_prgname(APP_ID)
    # GtkApplication looks for an icon named after the app unless one is set,
    # and that waits until the whole icon theme has loaded (a third of a
    # second with big themes like Papirus). Naming it first skips the wait.
    Gtk.Window.set_default_icon_name(APP_ID)
    return Application().run(args)


if __name__ == "__main__":
    sys.exit(main())
