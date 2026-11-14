"""Status chips: what needs your attention, wherever you are in App Entries.
Each chip goes where it's about: issues to Issues, an update to Updates,
unsaved edits to that app. With nothing to say, the bar is empty."""
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gtk

from .widgets import WrapBox, hbox, icon, label, spinner


def _chip(glyph, text, kind, tooltip, cb):
    b = Gtk.Button(valign=Gtk.Align.CENTER)
    b.add_css_class("status-chip")
    b.add_css_class(kind)
    inner = hbox(6, icon(glyph) if glyph else spinner(), label(text, ("small",)))
    b.set_child(inner)
    b.set_tooltip_text(tooltip)
    b.update_property([Gtk.AccessibleProperty.LABEL], [text])
    if cb is not None:
        b.connect("clicked", lambda *_a: cb())
    else:
        b.set_can_target(False)
    return b


class StatusBar(Gtk.Box):
    """`win` is the main window: the chips read its state and use its actions."""

    def __init__(self, win):
        super().__init__(valign=Gtk.Align.START)
        self.add_css_class("status-bar")
        self.win = win
        self.chips = WrapBox(8, 6)
        self.chips.set_hexpand(True)
        self.chips.set_halign(Gtk.Align.END)
        self.append(self.chips)
        self._sig = None
        self.has_items = False
        self.on_change = lambda: None   # the window places the bar

    def update(self):
        w = self.win
        items = []
        if getattr(w, "_scanning", False) and w._loaded:
            items.append(("", _("Scanning…"), "neutral", _("Looking for changes to your apps"), None))
        if getattr(w, "_scan_failed", False):
            items.append(("error", _("Couldn't read apps"), "error",
                          _("The application folders couldn't be read. Refresh to try again."),
                          w.rescan))
        here = w.settings.get("filter")
        n = w.report.count if w.report is not None else 0
        if n and here != "issues":
            items.append(("healing", ngettext("{n} issue", "{n} issues", n).format(n=n), "warn",
                          _("Leftover files, missing programs or duplicates. Open Issues to see them."),
                          lambda: w.settings.set("filter", "issues")))
        ups = w.get_application().updates
        if here == "updates":
            pass
        elif ups.release is not None:
            items.append(("system_update_alt", _("Update {version}").format(version=ups.release.version), "accent",
                          _("A new version of App Entries is out. Open Updates to see what's new."),
                          lambda: w.settings.set("filter", "updates")))
        elif ups.installed:
            items.append(("restart_alt", _("Restart to finish updating"), "accent",
                          _("Version {version} is installed. Restart App Entries to use it.")
                          .format(version=ups.installed), lambda: w.settings.set("filter", "updates")))
        for did in list(w.drafts):
            item = w.apps.by_id.get(did)
            if item is None or item is w._current:
                continue
            items.append(("edit_note", _("Unsaved: {name}").format(name=item.app.name), "accent",
                          _("You changed {name} but haven't saved. Open it to save or discard.")
                          .format(name=item.app.name), lambda it=item: w.open_draft(it)))
        sig = tuple((t, k) for _g, t, k, _tip, _cb in items)
        if sig == self._sig:
            return
        self._sig = sig
        self.chips.remove_all()
        for glyph, text, kind, tip, cb in items:
            self.chips.append(_chip(glyph, text, kind, tip, cb))
        self.has_items = bool(items)
        self.on_change()
