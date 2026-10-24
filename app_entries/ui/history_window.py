"""Everything App Entries changed, newest first, each with Undo."""
import os
import time
from gettext import gettext as _

from gi.repository import Gdk, Gtk, Pango

from .. import history, terminal
from .dialogs import Dialog, run_bg
from .widgets import button, card, clear, hbox, icon, label, vbox


def _when(t):
    now = time.localtime()
    then = time.localtime(t)
    clock = time.strftime("%H:%M", then)
    if then.tm_year == now.tm_year and then.tm_yday == now.tm_yday:
        return _("Today, {time}").format(time=clock)
    if then.tm_year == now.tm_year and then.tm_yday == now.tm_yday - 1:
        return _("Yesterday, {time}").format(time=clock)
    return time.strftime("%d %b %Y, %H:%M", then)


def _short(p):
    home = os.path.expanduser("~")
    return "~" + p[len(home):] if p.startswith(home + os.sep) else p


class HistoryWindow(Gtk.Window):
    """`undo(entry_id)` undoes an entry (the main window's undo_entry);
    `reinstall(entry_id)` installs again what an entry uninstalled."""

    def __init__(self, parent, undo, reinstall=None):
        super().__init__(transient_for=parent, title=_("History"))
        self.add_css_class("prefs")
        self.set_default_size(620, 640)
        self._undo = undo
        self._reinstall = reinstall

        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(label(_("History"), ("title",)))
        close = button(icon_name="close", style="text close", small=True, tooltip=_("Close"),
                       cb=lambda *_a: self.close())
        close.set_valign(Gtk.Align.CENTER)
        self.clear_btn = button(_("Clear"), "delete", "tonal", small=True, cb=self._clear,
                                tooltip=_("Forget the history. Your files stay as they are."))
        self.clear_btn.set_valign(Gtk.Align.CENTER)
        hb.pack_start(self.clear_btn)
        hb.pack_end(close)
        self.set_titlebar(hb)

        page = vbox(10)
        for side in ("start", "end", "bottom"):
            getattr(page, "set_margin_" + side)(20)
        page.append(label(_("Every change App Entries made, newest first. Undo puts the files back as they were, "
                            "and anything moved to the Trash comes back too. If a later change touched the same "
                            "file, undo that one first. The last {n} changes are kept, on this computer only.")
                          .format(n=history.KEEP), ("small", "dim"), wrap=True, chars=70))
        self.list = vbox(10)
        page.append(self.list)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(page)
        self.set_child(scroll)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a: kv == Gdk.KEY_Escape and (self.close() or True))
        self.add_controller(keys)
        self.reload()

    def reload(self):
        run_bg(history.load, self._fill)

    def _fill(self, entries):
        clear(self.list)
        if isinstance(entries, Exception):
            entries = []
        self.clear_btn.set_sensitive(bool(entries))
        if not entries:
            empty = vbox(10, icon("history", ("big", "empty-icon")),
                         label(_("Nothing yet"), ("title",), xalign=0.5),
                         label(_("Changes you make in App Entries are listed here, so you can undo them later."),
                               ("body", "dim"), wrap=True, xalign=0.5, chars=40))
            empty.set_margin_top(60)
            empty.set_halign(Gtk.Align.CENTER)
            self.list.append(empty)
            return
        for e in entries:
            self.list.append(self._row(e))

    def _row(self, e):
        title = label(e.message, ("body", "app-name"), wrap=True, chars=40)
        when = label(_when(e.when), ("small", "dim"))
        files = e.paths
        detail = label("\n".join(_short(p) for p in files[:4]) + ("\n…" if len(files) > 4 else ""),
                       ("small", "faint", "mono"), ellipsize=True)
        detail.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        detail.set_tooltip_text("\n".join(files))
        text = vbox(2, title, when, detail)
        text.set_hexpand(True)
        action = vbox(6)
        if e.undone:
            done = label(_("Undone"), ("small", "dim"))
            done.set_tooltip_text(_when(e.undone))
            action.append(done)
        elif e.too_big:
            big = label(_("Too large to undo"), ("small", "dim"))
            big.set_tooltip_text(_("The files were too large to keep a copy of."))
            action.append(big)
        elif e.can_undo:
            undo = button(_("Undo"), "undo", "tonal", small=True, cb=lambda *_a, i=e.id: self._undo(i))
            if e.reinstall:
                undo.set_tooltip_text(_("Puts back the files App Entries removed. Reinstall brings back the app."))
            action.append(undo)
        if e.reinstall and self._reinstall is not None:
            again = button(_("Reinstall"), "download", "tonal", small=True,
                           cb=lambda *_a, i=e.id: self._reinstall(i))
            again.set_tooltip_text((_("Opens Steam to install it again:") if e.reinstall_steam else
                                    _("Opens your terminal running:")) + "\n" + terminal.shown(e.reinstall))
            action.append(again)
        action.set_valign(Gtk.Align.CENTER)
        c = card()
        c.add_css_class("history-row")
        if e.undone:
            c.add_css_class("is-off")
        c.append(hbox(14, text, action))
        return c

    def _clear(self, *_a):
        def on_response(resp):
            if resp == "clear":
                history.clear()
                self.reload()

        Dialog(self, _("Clear the history?"),
               _("The list of changes is forgotten, so they can't be undone from here any more. Your files stay "
                 "exactly as they are now."),
               [("cancel", _("Cancel"), "tonal"), ("clear", _("Clear"), "danger")], on_response,
               icon_name="history").present()

