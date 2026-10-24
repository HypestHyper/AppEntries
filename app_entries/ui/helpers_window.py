"""Shortcuts to helper apps for one app (helpers.py). Each opens the
helper; one that isn't installed shows what it does and how to get it."""
import os
import re
import subprocess
from gettext import gettext as _

from gi.repository import Gdk, Gio, GLib, Gtk

from .. import helpers, pkgmanagers, terminal, uninstall
from .app_card import gicon_for
from .dialogs import Dialog, error_dialog, run_bg
from .widgets import button, card, hbox, icon, label, vbox

FLATSEAL_BUS = ("com.github.tchx84.Flatseal", "/com/github/tchx84/Flatseal")


def _handler(scheme):
    info = Gio.AppInfo.get_default_for_uri_scheme(scheme)
    return info.get_display_name() if info is not None else ""


def shortcuts_for(app, apps):
    kind = uninstall.kind_of(app)
    extra = {}
    if kind == "flatpak":
        extra["flatpak_id"] = uninstall._flatpak_id(app)
    elif kind == "snap":
        extra["snap_name"] = uninstall._snap_name(app)
    elif kind == "appimage":
        extra["appimage"] = uninstall.appimages.appimage_of(app.exec)
    elif kind == "steam":
        m = re.search(r"steam://rungameid/(\d+)", app.exec)
        extra["steam_id"] = m.group(1) if m else ""
    return helpers.for_app(app, kind, helpers.installed_ids(apps), uri_handler=_handler, **extra)


def _tile(name):
    img = Gtk.Image(pixel_size=32, accessible_role=Gtk.AccessibleRole.PRESENTATION)
    img.set_from_gicon(gicon_for(name))
    tile = Gtk.Box(valign=Gtk.Align.CENTER)
    tile.add_css_class("icon-tile")
    tile.add_css_class("small-tile")
    tile.append(img)
    return tile


class HelpersWindow(Gtk.Window):
    def __init__(self, win, app, apps):
        super().__init__(transient_for=win, modal=True, title=_("Helper apps"))
        self.win = win
        self.app = app
        self.add_css_class("prefs")
        self.set_default_size(520, 560)
        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(label(_("Helper apps for {name}").format(name=app.name), ("title",)))
        close = button(icon_name="close", style="text close", small=True, tooltip=_("Close"),
                       cb=lambda *_a: self.close())
        close.set_valign(Gtk.Align.CENTER)
        hb.pack_end(close)
        self.set_titlebar(hb)

        page = vbox(10)
        for side in ("start", "end", "bottom"):
            getattr(page, "set_margin_" + side)(20)
        page.append(label(_("Shortcuts to apps that set up what App Entries doesn't: permissions, versions and the "
                            "like. Each opens that app, on {name} where it can.").format(name=app.name),
                          ("small", "dim"), wrap=True, chars=60))
        items = shortcuts_for(app, apps)
        have = [x for x in items if x.installed]
        missing = [x for x in items if not x.installed]
        if not items:
            page.append(label(_("No helper apps fit {name}.").format(name=app.name), ("body", "dim"), wrap=True))
        elif not have:
            page.append(label(_("None of the helper apps for {name} are installed yet.").format(name=app.name),
                              ("body", "dim"), wrap=True, chars=50))
        for x in have:
            page.append(self._row(x))
        if missing:
            more = vbox(10)
            for x in missing:
                more.append(self._row(x))
            reveal = Gtk.Revealer(child=more, reveal_child=False,
                                  transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
            add = Gtk.ToggleButton(halign=Gtk.Align.START)
            add.set_child(hbox(6, icon("add"), Gtk.Label(label=_("Helper apps you don't have ({n})")
                                                         .format(n=len(missing)))))
            add.add_css_class("tonal")
            add.add_css_class("small")
            add.set_tooltip_text(_("Show helper apps that would fit but aren't installed"))
            add.connect("toggled", lambda b: reveal.set_reveal_child(b.get_active()))
            add.set_margin_top(4)
            page.append(add)
            page.append(reveal)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(page)
        self.set_child(scroll)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a: kv == Gdk.KEY_Escape and (self.close() or True))
        self.add_controller(keys)

    def _row(self, s):
        name = label(s.name, ("body", "app-name"), ellipsize=True)
        what = label(s.what, ("small", "dim"), wrap=True, chars=44)
        text = vbox(2, name, what)
        if not s.installed:
            text.append(label(_("Not installed"), ("small", "faint")))
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        if s.installed:
            b = button(_("Open"), "open_in_new", "tonal", small=True, cb=lambda *_a: self._open(s))
        else:
            b = button(_("Install…"), "download", "tonal", small=True, cb=lambda *_a: self._install(s))
        b.set_valign(Gtk.Align.CENTER)
        c = card()
        c.add_css_class("helper-row")
        if not s.installed:
            c.add_css_class("is-off")
        c.append(hbox(14, _tile(s.icon), text, b))
        return c

    # -- opening ------------------------------------------------------------

    def _fail(self, s, why):
        error_dialog(self, _("Couldn't open {name}").format(name=s.name), str(why))

    def _launch_desktop(self, s, did, files):
        info = Gio.DesktopAppInfo.new(did)
        if info is None:
            self._fail(s, _("Its menu entry is gone."))
            return False
        try:
            info.launch([Gio.File.new_for_path(f) for f in files], None)
        except GLib.Error as e:
            self._fail(s, e.message)
            return False
        return True

    def _open(self, s):
        kind = s.action[0]
        if kind == "desktop":
            ok = self._launch_desktop(s, s.action[1], s.action[2])
        elif kind == "flatseal":
            ok = self._launch_desktop(s, s.action[1], [])
            if ok:
                _flatseal_show(s.action[2])
        elif kind == "argv":
            ok = _spawn(self, s, s.action[1])
        elif kind == "uri":
            try:
                Gio.AppInfo.launch_default_for_uri(s.action[1], None)
                ok = True
            except GLib.Error as e:
                self._fail(s, e.message)
                ok = False
        elif kind == "kde-permissions":
            app_id, module = s.action[1], s.action[2]

            def ref():
                r = pkgmanagers.run(["flatpak", "info", "--show-ref", app_id])
                return r[1].strip() if r and r[0] == 0 else ""

            run_bg(ref, lambda r: _spawn(self, s, helpers.kde_argv(app_id, r if isinstance(r, str) else "", module)))
            ok = True
        else:
            ok = False
        if ok:
            self.close()

    def _install(self, s):
        cmd = s.install

        def on_response(resp):
            if resp != "install":
                return
            try:
                terminal.start([cmd])
            except terminal.NoTerminal:
                error_dialog(self, _("No terminal app was found"), _("Run this in a terminal to install it:"),
                             terminal.shown([cmd]))
                return
            except OSError as e:
                error_dialog(self, _("The terminal couldn't be started"), str(e.strerror or e), terminal.shown([cmd]))
                return
            self.win.snackbar.show(_("Opened your terminal to install {name}").format(name=s.name))
            self.close()

        Dialog(self, _("Install {name}?").format(name=s.name),
               _("{what} Your terminal opens running this command, which installs it from Flathub. Flatpak shows "
                 "what it downloads and asks before installing. Afterwards it's listed here with an Open button.")
               .format(what=s.what),
               [("cancel", _("Cancel"), "tonal"), ("install", _("Install in terminal"), "filled")], on_response,
               icon_name="download", detail=terminal.shown([cmd])).present()


def _spawn(parent, s, argv):
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, env=dict(os.environ))
    except OSError as e:
        error_dialog(parent, _("Couldn't open {name}").format(name=s.name), str(e.strerror or e))
        return False
    return True


def _flatseal_show(app_id, tries=20):
    """Ask Flatseal to show this app once it's up (its app.show action).
    Without a session bus Flatseal just opens on its list."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        return
    left = [tries]

    def attempt():
        def done(conn, res):
            try:
                conn.call_finish(res)
            except GLib.Error:
                left[0] -= 1
                if left[0] > 0:
                    GLib.timeout_add(500, lambda: (attempt(), False)[1])

        bus.call(FLATSEAL_BUS[0], FLATSEAL_BUS[1], "org.gtk.Actions", "Activate",
                 GLib.Variant("(sava{sv})", ("show", [GLib.Variant("s", app_id)], {})), None,
                 Gio.DBusCallFlags.NO_AUTO_START, 1000, None, done)

    GLib.timeout_add(700, lambda: (attempt(), False)[1])
