"""The Default apps tab: which app opens links, PDFs, pictures and so on.
Nothing changes until you pick an app, and every change can be undone."""
from gettext import gettext as _

from gi.repository import Gtk

from .. import defaults
from .app_card import gicon_for, label_for_source
from .dialogs import Dialog, run_bg
from .widgets import Clamp, button, card, clear, hbox, icon, label, section, vbox


def N_(s):
    return s


# What a choice does, for the confirmation: "Firefox opens links now".
OPENS = {
    "browser": N_("links"), "mail": N_("email links"), "files": N_("folders"), "text": N_("text files"),
    "pdf": N_("PDFs"), "images": N_("pictures"), "video": N_("videos"), "music": N_("music"),
    "archives": N_("archives"),
}

NAMES = {
    "browser": (N_("Web browser"), N_("Links, and web pages saved on your computer")),
    "mail": (N_("Email"), N_("Email links (mailto:)")),
    "files": (N_("Files and folders"), N_("Opening folders, from other apps and Open containing folder")),
    "text": (N_("Text files"), N_("Plain text files")),
    "pdf": (N_("PDF documents"), N_("PDF files")),
    "images": (N_("Pictures"), N_("PNG, JPEG, GIF, WebP and other images")),
    "video": (N_("Videos"), N_("MP4, MKV, WebM and other videos")),
    "music": (N_("Music"), N_("MP3, FLAC, Ogg and other audio")),
    "archives": (N_("Archives"), N_("ZIP, TAR, 7z, RAR and other archives")),
}


class DefaultsPage(Gtk.ScrolledWindow):
    """`run(plan, message, failed_title, after=…)` is the main window's
    _run_changes; `apps()` lists installed apps."""

    def __init__(self, win, run, apps):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.win = win
        self._run = run
        self._apps = apps
        self._signature = None
        page = vbox(0)
        page.set_margin_bottom(32)
        page.append(section(_("Default apps"),
                            _("Which app opens links and files when you double-click them or an app asks. Your "
                              "choices go in ~/.config/mimeapps.list, which every major desktop and most apps "
                              "read. Reset goes back to your desktop's own choice.")))
        self.list = vbox(10)
        self.list.set_margin_top(10)
        page.append(self.list)
        self.set_child(Clamp(page, 900))

    def reload(self):
        apps = self._apps()
        if not apps:
            return

        def work():
            return [(cat, defaults.candidates(cat, apps), defaults.state(cat, apps)) for cat in defaults.CATEGORIES]

        def done(rows):
            if isinstance(rows, Exception):
                return
            sig = tuple((c.key, tuple(a.id for a in cands), s.app_id, s.mixed, s.chosen_by_you)
                        for c, cands, s in rows)
            if sig != self._signature:
                self._signature = sig
                clear(self.list)
                by_id = {a.id: a for a in apps}
                for cat, cands, s in rows:
                    self.list.append(self._row(cat, cands, s, by_id))

        run_bg(work, done)

    def _row(self, cat, cands, s, by_id):
        name, what = NAMES.get(cat.key, (cat.name, ""))
        glyph = icon(cat.icon)
        glyph.add_css_class("default-glyph")
        text = vbox(2, label(_(name), ("body", "app-name")), label(_(what), ("small", "dim"), wrap=True, chars=40))
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)

        current = by_id.get(s.app_id)
        if not cands:
            picker = label(_("No installed app opens these"), ("small", "dim"))
        else:
            picker = self._picker(cat, cands, current, s)
        picker.set_valign(Gtk.Align.CENTER)
        reset = button(icon_name="restart_alt", style="text", small=True,
                       tooltip=_("Reset: let your desktop choose again"), cb=lambda *_a: self._reset(cat))
        reset.set_valign(Gtk.Align.CENTER)
        reset.set_visible(s.chosen_by_you)
        c = card()
        c.add_css_class("autostart-row")
        c.append(hbox(14, glyph, text, picker, reset))
        if s.mixed:
            c.append(label(_("Some of these open in different apps. Picking one sets it for all of them."),
                           ("small", "warn-text"), wrap=True, chars=70))
        return c

    def _picker(self, cat, cands, current, s):
        """A button showing the current app; it opens the list to choose from."""
        b = Gtk.MenuButton()
        b.add_css_class("tonal")
        b.add_css_class("default-pick")
        if current is not None:
            img = Gtk.Image(pixel_size=24, accessible_role=Gtk.AccessibleRole.PRESENTATION)
            img.set_from_gicon(gicon_for(current.icon))
            b.set_child(hbox(8, img, label(current.name, ("body",), ellipsize=True), icon("expand_more")))
        else:
            b.set_child(hbox(8, label(_("Not chosen"), ("body", "dim")), icon("expand_more")))
        b.set_tooltip_text(_("Choose the app for {what}").format(what=_(NAMES.get(cat.key, (cat.name,))[0]).lower()))

        box = vbox(2)
        names = [a.name.casefold() for a in cands]
        for a in cands:
            img = Gtk.Image(pixel_size=24, accessible_role=Gtk.AccessibleRole.PRESENTATION)
            img.set_from_gicon(gicon_for(a.icon))
            row = Gtk.Button()
            row.add_css_class("flat")
            row.add_css_class("pick-row")
            mark = icon("check")
            mark.set_visible(current is not None and a.id == current.id and not s.mixed)
            name = label(a.name, ("body",), ellipsize=True)
            text = vbox(0, name)
            text.set_hexpand(True)
            if names.count(a.name.casefold()) > 1:
                # Two entries with the same name: say which is which.
                src = a.source or ("system" if a.system else "user")
                text.append(label("%s · %s" % (label_for_source(src), a.id), ("small", "dim", "mono"),
                                  ellipsize=True))
            row.set_child(hbox(10, img, text, mark))
            row.connect("clicked", lambda _r, app=a: (b.popdown(), self._set(cat, app)))
            box.append(row)
        pop = Gtk.Popover()
        pop.add_css_class("options")
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                    max_content_height=420)
        scroll.set_child(box)
        box.set_size_request(260, -1)
        pop.set_child(scroll)
        b.set_popover(pop)
        return b

    def _set(self, cat, app):
        notes = []

        def plan():
            changes, n = defaults.plan_set(cat, app)
            notes.extend(n)
            return changes

        def after(_result):
            if notes:
                Dialog(self.win, _("{app} is set, with a note").format(app=app.name), " ".join(notes),
                       [("ok", _("OK"), "filled")], icon_name="info").present()
            self.reload()
            return []

        what = _(OPENS.get(cat.key, cat.name))
        self._run(plan, lambda n: _("{app} opens {what} now").format(app=app.name, what=what),
                  _("Couldn't set {app}").format(app=app.name), after=after)

    def _reset(self, cat):
        name = _(NAMES.get(cat.key, (cat.name,))[0])

        def after(_result):
            self.reload()
            return []

        self._run(lambda: defaults.plan_reset(cat),
                  lambda n: _("{what}: back to your desktop's choice").format(what=name),
                  _("Couldn't reset {what}").format(what=name.lower()), after=after)

