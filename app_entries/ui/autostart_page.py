"""The Autostart tab: programs that start when you log in. Nothing changes
until a switch or button is used, and every change can be undone."""
import os
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk, Pango

from .. import autostart
from .app_card import gicon_for
from .dialogs import Dialog, run_bg
from .widgets import Clamp, Toggle, button, card, clear, hbox, icon, label, option_button, section, vbox


def _tile(icon_name):
    img = Gtk.Image(pixel_size=32, accessible_role=Gtk.AccessibleRole.PRESENTATION)
    img.set_from_gicon(gicon_for(icon_name))
    tile = Gtk.Box(valign=Gtk.Align.CENTER)
    tile.add_css_class("icon-tile")
    tile.add_css_class("small-tile")
    tile.append(img)
    return tile


class AutostartPage(Gtk.ScrolledWindow):
    """`run(plan, message, failed_title)` applies changes with Undo (the main
    window's _run_changes); `apps()` lists installed apps for Add an app."""

    def __init__(self, win, run, apps):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.win = win
        self._run = run
        self._apps = apps
        self._signature = None
        page = vbox(0)
        page.set_margin_bottom(32)

        page.append(section(_("Starts when you log in"),
                            _("Programs your desktop starts for you at login. Turning one off doesn't uninstall "
                              "anything; turning a system one off writes a small file to your own autostart "
                              "folder, and the system file is never changed.")))
        add_app = button(_("Add an app…"), "add", "tonal", lambda *_a: self._add_app(), small=True)
        add_cmd = button(_("Add a command…"), "terminal", "tonal", lambda *_a: self._add_command(), small=True)
        page.append(hbox(10, add_app, add_cmd))
        how = autostart.how_to_run()
        if how:
            hint = label(_(how) + " " + _("The switches here work either way."), ("small", "warn-text"),
                         wrap=True, chars=80)
            hint.set_selectable(True)
            hint.set_margin_top(10)
            page.append(hint)
        self.list = vbox(10)
        self.list.set_margin_top(14)
        page.append(self.list)
        self.set_child(Clamp(page, 900))
        self.reload()

    # -- list ---------------------------------------------------------------

    def reload(self):
        def done(items):
            if isinstance(items, Exception):
                return
            sig = tuple((i.id, i.enabled, i.path, i.user_path, i.name, i.exec) for i in items)
            if sig != self._signature:
                self._signature = sig
                self._fill(items)

        run_bg(autostart.scan, done)

    def _fill(self, items):
        clear(self.list)
        if not items:
            self.list.append(label(_("Nothing starts at login yet. Add an app or a command above."),
                                   ("body", "dim"), wrap=True, chars=60))
            return
        for it in items:
            self.list.append(self._row(it))

    def _row(self, it):
        name = label(it.name, ("body", "app-name"), ellipsize=True)
        cmd = label(it.exec, ("small", "faint", "mono"), ellipsize=True)
        cmd.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        cmd.set_tooltip_text(it.exec + "\n" + it.path)
        lines = vbox(2, name)
        if it.comment:
            lines.append(label(it.comment, ("small", "dim"), ellipsize=True))
        lines.append(cmd)
        badges = []
        if it.created:
            badges.append(_("Added by you"))
        elif it.system:
            badges.append(_("System"))
        else:
            badges.append(_("Yours"))
        if it.user_path and it.system and not it.managed:
            badges.append(_("Changed by you"))
        if it.excluded_here:
            badges.append(_("Not on this desktop"))
        lines.append(label(" · ".join(badges), ("small", "dim")))
        lines.set_hexpand(True)
        lines.set_valign(Gtk.Align.CENTER)

        sw = Toggle(it.enabled, lambda v, i=it: self._toggle(i, v))
        sw.set_valign(Gtk.Align.CENTER)
        sw.update_property([Gtk.AccessibleProperty.LABEL], [_("Start {name} at login").format(name=it.name)])
        sw.set_tooltip_text(_("Turn off to stop {name} starting when you log in").format(name=it.name) if it.enabled
                            else _("Turn on to start {name} when you log in").format(name=it.name))
        more = Gtk.MenuButton(valign=Gtk.Align.CENTER, tooltip_text=_("More options"))
        more.set_child(icon("more_horiz"))
        more.add_css_class("flat")
        more.add_css_class("circle")
        more.set_create_popup_func(lambda mb, i=it: self._menu(mb, i))
        row = hbox(14, _tile(it.icon), lines, sw, more)
        c = card()
        c.add_css_class("autostart-row")
        if not it.enabled:
            c.add_css_class("is-off")
        c.append(row)
        return c

    def _menu(self, mb, it):
        box = vbox(2)
        box.set_size_request(300, -1)

        def act(fn):
            def cb(*_a):
                mb.popdown()
                fn()
            return cb

        if it.user_path and it.system:
            box.append(option_button("restart_alt", _("Restore original"),
                                     _("Deletes your file for this entry, so the system's version is used again. "
                                       "You can undo this."), act(lambda: self._restore(it))))
        if it.user_path and not it.system:
            box.append(option_button("delete", _("Remove from autostart"),
                                     _("Deletes this entry from your autostart folder. The program itself isn't "
                                       "touched. You can undo this."), act(lambda: self._delete(it)), danger=True))
        box.append(option_button("folder_open", _("Open file location"),
                                 _("Opens the folder that holds this entry in your file manager."),
                                 act(lambda: self._open_folder(it))))
        pop = Gtk.Popover()
        pop.add_css_class("options")
        pop.set_child(box)
        mb.set_popover(pop)

    # -- actions ------------------------------------------------------------

    def _toggle(self, it, enabled):
        self._run(lambda: [autostart.plan_set_enabled(it, enabled)],
                  lambda n: (_("{name} starts at login") if enabled else _("{name} won't start at login"))
                  .format(name=it.name), _("Couldn't change {name}").format(name=it.name))

    def _restore(self, it):
        self._run(lambda: [autostart.plan_restore(it)],
                  lambda n: _("Restored the original {name}").format(name=it.name),
                  _("Couldn't restore {name}").format(name=it.name))

    def _delete(self, it):
        self._run(lambda: [autostart.plan_delete(it)],
                  lambda n: _("Removed {name} from autostart").format(name=it.name),
                  _("Couldn't remove {name}").format(name=it.name))

    def _open_folder(self, it):
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(os.path.dirname(it.path)).get_uri(), None)
        except GLib.Error:
            pass

    def _add_app(self):
        AddAppWindow(self.win, self._apps(), lambda app: self._run(
            lambda: [autostart.plan_add_app(app)],
            lambda n: _("{name} starts at login").format(name=app.name),
            _("Couldn't add {name}").format(name=app.name))).present()

    def _add_command(self):
        name = Gtk.Entry(placeholder_text=_("Sync my notes"), hexpand=True)
        cmd = Gtk.Entry(placeholder_text="rclone sync ~/Notes remote:Notes", hexpand=True)
        cmd.add_css_class("mono")
        box = vbox(8, label(_("Name"), ("body", "option-title")), name,
                   label(_("Command"), ("body", "option-title")), cmd,
                   label(_("Written as in a terminal. It runs once when you log in, without a terminal window."),
                         ("small", "dim"), wrap=True, chars=48))

        def on_response(resp):
            if resp == "add":
                try:
                    change = autostart.plan_add_command(name.get_text(), cmd.get_text())
                except ValueError as e:
                    Dialog(self.win, _("Couldn't add it"), str(e), [("ok", _("OK"), "filled")],
                           icon_name="error", icon_class="error-text").present()
                    return
                self._run(lambda: [change], lambda n: _("{name} starts at login").format(name=change.app_name),
                          _("Couldn't add it"))

        d = Dialog(self.win, _("Add a command"), _("Runs a command each time you log in."),
                   [("cancel", _("Cancel"), "tonal"), ("add", _("Add"), "filled")], on_response,
                   icon_name="terminal", extra=box)
        d.present()
        name.grab_focus()


class AddAppWindow(Gtk.Window):
    """Pick an installed app to start at login."""

    def __init__(self, parent, apps, on_pick):
        super().__init__(transient_for=parent, modal=True, title=_("Add an app"))
        self.add_css_class("prefs")
        self.set_default_size(460, 560)
        self._on_pick = on_pick
        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(label(_("Start at login"), ("title",)))
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self.close())
        cancel.set_valign(Gtk.Align.CENTER)
        hb.pack_start(cancel)
        self.set_titlebar(hb)

        self.apps = sorted((a for a in apps if not a.no_display), key=lambda a: a.name.casefold())
        self.search = Gtk.SearchEntry(placeholder_text=_("Search apps"))
        self.search.add_css_class("search-entry")
        self.search.connect("search-changed", lambda *_a: self.listbox.invalidate_filter())
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=True)
        self.listbox.add_css_class("pick-list")
        for a in self.apps:
            r = Gtk.ListBoxRow()
            r.app = a
            r.set_child(hbox(12, _tile(a.icon), label(a.name, ("body",), ellipsize=True)))
            self.listbox.append(r)
        self.listbox.set_filter_func(self._filter)
        self.listbox.connect("row-activated", self._activated)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(self.listbox)
        body = vbox(10, label(_("Choose an app to start each time you log in. A copy of its entry goes in "
                                "your autostart folder."), ("small", "dim"), wrap=True, chars=50),
                    self.search, scroll)
        for side in ("start", "end", "bottom"):
            getattr(body, "set_margin_" + side)(16)
        self.set_child(body)
        self.search.set_key_capture_widget(self)

    def _filter(self, row):
        q = self.search.get_text().strip().casefold()
        return not q or q in row.app.name.casefold() or q in row.app.id.casefold()

    def _activated(self, _lb, row):
        self.close()
        self._on_pick(row.app)
